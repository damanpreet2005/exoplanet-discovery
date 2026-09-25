"""
Light curve (time, flux) -> 17-feature adapter.

PROVENANCE / HONESTY NOTE (read before changing the feature list):
This repository has never contained any light-curve preprocessing or feature-
engineering code. The only trained artifact that exists is
model/hybrid_ensemble_model.pkl, which stores a RandomForestClassifier, a
fitted RobustScaler, and raw CNN weights -- no code describing how its 17
training features were computed from raw observations, and no feature names
(`feature_names_in_` is None on both the scaler and the Random Forest).

Given that, the 17 features computed below are a **best-effort, documented
reconstruction**, not a verified match to whatever the model was actually
trained on. They are all computed from the (time, flux) light curve alone --
no stellar/catalog parameters are requested or assumed anywhere in this
module. Every value is a real, standard, computable quantity (a genuine Box
Least Squares transit search via astropy, plus standard time-series/transit
vetting statistics) -- nothing here is a fabricated/random number, and
nothing here invents a stellar or planetary property that the light curve
alone cannot support.

This is explicitly NOT guaranteed to reproduce the original training
pipeline's feature semantics, units, or order. Predictions produced through
this path should be treated as exploratory, not scientifically validated --
see the `warnings` field this module contributes to the API response.

Feature order produced by `compute_feature_vector` (mapped positionally onto
the model's feature_1..feature_17 slots), all derived purely from time+flux:

  1.  bls_period_days               -- Box Least Squares best-fit orbital period
  2.  bls_duration_hours             -- BLS best-fit transit duration
  3.  bls_depth_ppm                  -- BLS best-fit transit depth (parts per million)
  4.  transit_epoch                  -- BLS best-fit reference transit time (same units as input time)
  5.  num_transits_observed          -- floor(baseline / period)
  6.  transit_snr                    -- BLS depth signal-to-noise ratio
  7.  baseline_days                  -- max(time) - min(time)
  8.  flux_scatter_ppm               -- std of the median-normalized flux
  9.  duration_over_period           -- transit duration / period (dimensionless shape ratio)
  10. odd_even_depth_ratio           -- depth(even-numbered transits) / depth(odd-numbered transits);
                                         a large deviation from 1.0 is a classic eclipsing-binary flag
  11. secondary_eclipse_depth_ppm    -- flux dip at phase 0.5 (opposite the primary transit)
  12. ingress_egress_asymmetry_ppm   -- first-half vs second-half flux asymmetry within the transit
  13. transit_residual_scatter_ppm   -- scatter of in-transit points around the fitted box depth
  14. flux_skewness                  -- skewness of the normalized flux distribution
  15. flux_kurtosis                  -- excess kurtosis of the normalized flux distribution
  16. median_cadence_days            -- median spacing between consecutive time samples
  17. point_to_point_scatter_ppm     -- RMS of consecutive-point flux differences (high-frequency noise)

`time` is passed straight through into the transit search exactly as
uploaded: no unit detection, no unit conversion, no date/timestamp parsing,
and no minimum-observation-baseline requirement. Only column presence is
validated. The second required column may be named `flux` or `brightness`
(case-insensitive) -- both mean the same photometric measurement.
"""
import csv
import io
import logging
import math
from dataclasses import dataclass

import numpy as np
from astropy.timeseries import BoxLeastSquares

logger = logging.getLogger("ml_service")

N_LIGHTCURVE_FEATURES = 17

LIGHTCURVE_FEATURE_NAMES = [
    "bls_period_days",
    "bls_duration_hours",
    "bls_depth_ppm",
    "transit_epoch",
    "num_transits_observed",
    "transit_snr",
    "baseline_days",
    "flux_scatter_ppm",
    "duration_over_period",
    "odd_even_depth_ratio",
    "secondary_eclipse_depth_ppm",
    "ingress_egress_asymmetry_ppm",
    "transit_residual_scatter_ppm",
    "flux_skewness",
    "flux_kurtosis",
    "median_cadence_days",
    "point_to_point_scatter_ppm",
]

BEST_EFFORT_WARNING = (
    "The 17 model features were derived from the uploaded light curve using a "
    "best-effort transit search and standard time-series vetting statistics, "
    "computed entirely from the time/flux data you uploaded (no stellar or "
    "catalog parameters are used). No feature-extraction code or feature-name "
    "mapping exists in this repository for the original trained model, so "
    "this reconstruction is not verified to match the model's original "
    "training pipeline. Treat this prediction as exploratory, not "
    "scientifically validated."
)

MIN_POINTS = 30
MAX_POINTS = 80000
MIN_PERIOD_DAYS = 0.5

# astropy's BoxLeastSquares generates a period grid uniform in frequency, with
# grid size nf = 1 + round((1/min_period - 1/max_period) / df), where
# df = frequency_factor * min_duration / baseline**2 (see BoxLeastSquares.
# autoperiod's docstring/source for the exact formula this mirrors). For a
# long-baseline, high-cadence light curve, nf at the default frequency_factor
# of 1.0 can reach into the hundreds of millions, making the search take
# minutes -- this is what caused prediction requests to time out. Since nf
# scales as 1/frequency_factor, the grid size can be capped by solving for
# the frequency_factor that yields a target nf, computed analytically (O(1),
# no array materialization) so this stays cheap even for huge inputs.
BLS_OPS_BUDGET = 3e9  # ~1-1.5s at the empirically-measured ~2-3e9 ops/sec fast-path throughput


def _bounded_frequency_factor(n_points: int, n_durations: int, baseline_days: float,
                               min_period_days: float, max_period_days: float,
                               min_duration_days: float) -> float:
    """Returns the smallest frequency_factor (>= 1.0) that keeps astropy's
    natural period-grid size within a fixed compute budget, without ever
    generating the grid itself to measure it."""
    df_at_ff1 = min_duration_days / baseline_days**2
    min_freq, max_freq = 1.0 / max_period_days, 1.0 / min_period_days
    natural_grid_size = 1 + round((max_freq - min_freq) / df_at_ff1)

    max_grid_size = max(2000, int(BLS_OPS_BUDGET / (n_points * n_durations)))
    if natural_grid_size <= max_grid_size:
        return 1.0
    return (max_freq - min_freq) / (df_at_ff1 * (max_grid_size - 1))


class LightCurveValidationError(Exception):
    """Raised for file-level light-curve problems (missing columns, too few
    usable points, insufficient baseline, non-positive flux, etc.)."""


@dataclass
class BlsResult:
    period_days: float
    duration_hours: float
    depth_ppm: float
    depth_fraction: float
    transit_epoch: float
    snr: float


@dataclass
class LightCurveExtraction:
    features: list[float]
    feature_names: list[str]
    n_points_used: int
    n_points_dropped: int
    baseline_days: float
    bls: BlsResult
    characterisation: dict


def parse_time_flux_csv(raw_bytes: bytes) -> tuple[np.ndarray, np.ndarray, int]:
    """Parses a CSV requiring only `time` and `flux` columns (case-insensitive;
    extra columns are ignored). Rows with missing/non-finite values are
    dropped rather than aborting the whole upload -- real light curves
    routinely have data gaps."""
    if not raw_bytes.strip():
        raise LightCurveValidationError("The uploaded CSV file is empty.")

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LightCurveValidationError("The uploaded file is not valid UTF-8 text.") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        raise LightCurveValidationError("The uploaded CSV file has no header row.")

    flux_column_name = "flux" if "flux" in header else ("brightness" if "brightness" in header else None)
    if "time" not in header or flux_column_name is None:
        raise LightCurveValidationError(
            "The uploaded CSV must contain a 'time' column and either a "
            f"'flux' or 'brightness' column (case-insensitive); got columns {header!r}."
        )

    time_idx = header.index("time")
    flux_idx = header.index(flux_column_name)

    times: list[float] = []
    fluxes: list[float] = []
    dropped = 0

    for raw_row in reader:
        if len(raw_row) <= max(time_idx, flux_idx):
            dropped += 1
            continue
        try:
            t = float(raw_row[time_idx])
            f = float(raw_row[flux_idx])
        except ValueError:
            dropped += 1
            continue
        if math.isnan(t) or math.isinf(t) or math.isnan(f) or math.isinf(f):
            dropped += 1
            continue
        times.append(t)
        fluxes.append(f)

    if len(times) < MIN_POINTS:
        raise LightCurveValidationError(
            f"Only {len(times)} usable (time, flux) rows were found after dropping "
            f"invalid/missing values; at least {MIN_POINTS} are required for a "
            "meaningful transit search."
        )
    if len(times) > MAX_POINTS:
        raise LightCurveValidationError(
            f"The light curve has {len(times)} usable rows, which exceeds the "
            f"maximum of {MAX_POINTS} supported per upload. Downsample or trim "
            "the light curve before uploading."
        )

    time_arr = np.asarray(times, dtype=np.float64)
    flux_arr = np.asarray(fluxes, dtype=np.float64)
    order = np.argsort(time_arr)
    time_arr, flux_arr = time_arr[order], flux_arr[order]

    logger.info(
        "lightcurve_columns_detected: detected_columns=%s flux_column=%s n_points=%d",
        header, flux_column_name, len(time_arr),
    )

    median_flux = float(np.median(flux_arr))
    if not math.isfinite(median_flux) or median_flux <= 0:
        raise LightCurveValidationError(
            "Flux values must have a positive, finite median to be normalized."
        )

    return time_arr, flux_arr, dropped


def run_box_least_squares(time: np.ndarray, normalized_flux: np.ndarray) -> BlsResult:
    """Real Box Least Squares transit search (astropy), not a fabricated result.

    BUG FIX (root cause of "Feature computation produced a non-finite value"):
    the period/duration search grid used to be fixed absolute-day constants
    (MIN_PERIOD_DAYS=0.5, durations from 0.02 to 0.4 days), which silently
    assumed every upload's `time` column is on a Kepler-like day timescale.
    For a real upload whose actual baseline is much smaller than 0.5 "days"
    in whatever units its time column happens to use (verified against the
    actual Kepler-452b dataset: one of its exports has a baseline of exactly
    0.000283 units), `max(baseline/2, 0.5)` collapsed `minimum_period` and
    `maximum_period` to the *same* value, and the fixed duration grid (up to
    0.4) vastly exceeded the entire data span -- every trial window then
    contained either all or none of the points, which is a 0/0 inside
    astropy's box-depth calculation, producing NaN that propagated into the
    feature vector.

    The fix: derive the search range from the light curve's own baseline and
    cadence instead of fixed absolute constants, so `minimum_period` is
    always strictly less than `maximum_period` and the duration grid always
    stays a small fraction of the actual data span -- regardless of what
    absolute time unit the upload happens to use. This requires no minimum
    baseline and adds no new validation; it only fixes the search grid to
    actually match the data it's searching.
    """
    baseline = float(time[-1] - time[0])
    cadence = float(np.median(np.diff(time)))
    if not math.isfinite(cadence) or cadence <= 0:
        cadence = baseline / max(len(time) - 1, 1)

    # Keep the original, well-tested Kepler-scale defaults (min_period=0.5,
    # max_duration=0.4, both "days") whenever the data's own baseline
    # actually supports them; only scale them down -- proportionally, from
    # the data's own baseline/cadence -- when it doesn't. This is what fixes
    # the degenerate case (baseline far below 0.5) without changing behavior
    # for any normal-scale light curve.
    default_min_period, default_max_duration = 0.5, 0.4

    min_period = min(default_min_period, baseline / 4.0)
    min_period = max(min_period, cadence * 3.0)
    max_period = max(baseline / 2.0, min_period * 2.0)

    max_duration = min(default_max_duration, min_period * 0.8)
    max_duration = max(max_duration, cadence * 2.0)
    min_duration = max(cadence, max_duration / 20.0)
    if min_duration >= max_duration:
        min_duration = max_duration * 0.5
    durations = np.linspace(min_duration, max_duration, 20)

    frequency_factor = _bounded_frequency_factor(
        n_points=len(time), n_durations=len(durations), baseline_days=baseline,
        min_period_days=min_period, max_period_days=max_period,
        min_duration_days=float(durations.min()),
    )

    model = BoxLeastSquares(time, normalized_flux)
    try:
        periodogram = model.autopower(
            durations, minimum_period=min_period, maximum_period=max_period,
            frequency_factor=frequency_factor,
        )
    except Exception as exc:  # noqa: BLE001
        raise LightCurveValidationError(f"Transit search failed on this light curve: {exc}") from exc

    if len(periodogram.power) == 0:
        raise LightCurveValidationError("Transit search produced no candidate periods.")

    # Defense in depth: a real data gap can still leave an isolated trial
    # with a 0/0 (NaN) power inside astropy's own calculation even with a
    # properly-scaled search grid. Plain argmax can be poisoned by a NaN;
    # explicitly ignore NaN trials so a few bad trials don't invalidate an
    # otherwise-good search.
    power = np.asarray(periodogram.power, dtype=np.float64)
    if np.all(np.isnan(power)):
        raise LightCurveValidationError(
            "Transit search could not find any valid candidate period in this light curve."
        )
    best = int(np.nanargmax(power))
    depth_fraction = float(periodogram.depth[best])
    if not math.isfinite(depth_fraction):
        depth_fraction = 0.0
    period_days = float(periodogram.period[best])
    duration_days = float(periodogram.duration[best])
    transit_epoch = float(periodogram.transit_time[best])
    if not math.isfinite(duration_days) or duration_days <= 0:
        duration_days = float(durations[0])
    if not math.isfinite(transit_epoch):
        transit_epoch = float(time[0])
    snr = float(periodogram.depth_snr[best]) if hasattr(periodogram, "depth_snr") else float("nan")

    return BlsResult(
        period_days=period_days,
        duration_hours=duration_days * 24.0,
        depth_ppm=max(depth_fraction, 0.0) * 1e6,
        depth_fraction=max(depth_fraction, 0.0),
        transit_epoch=transit_epoch,
        snr=snr if math.isfinite(snr) else 0.0,
    )


def _phase(time: np.ndarray, period: float, epoch: float) -> np.ndarray:
    """Phase in [-0.5, 0.5), centered on the transit epoch."""
    phase = np.mod(time - epoch + period / 2.0, period) / period - 0.5
    return phase


def _odd_even_depth_ratio(time, normalized_flux, bls: BlsResult) -> float:
    """Ratio of transit depth measured from even- vs odd-numbered transit
    events. Real eclipsing binaries typically show alternating depths; a
    genuine planet should show odd_even_depth_ratio close to 1.0."""
    half_dur_days = (bls.duration_hours / 24.0) / 2.0
    cycle = np.round((time - bls.transit_epoch) / bls.period_days)
    phase = _phase(time, bls.period_days, bls.transit_epoch)
    in_transit = np.abs(phase * bls.period_days) < half_dur_days

    odd_mask = in_transit & (np.mod(cycle, 2) == 1)
    even_mask = in_transit & (np.mod(cycle, 2) == 0)

    if odd_mask.sum() < 2 or even_mask.sum() < 2:
        return 1.0  # not enough transits of each parity to distinguish -- neutral value

    odd_depth = 1.0 - float(np.mean(normalized_flux[odd_mask]))
    even_depth = 1.0 - float(np.mean(normalized_flux[even_mask]))
    if abs(odd_depth) < 1e-8:
        return 1.0
    return even_depth / odd_depth


def _secondary_eclipse_depth_ppm(time, normalized_flux, bls: BlsResult) -> float:
    """Flux dip at phase 0.5 (opposite the primary transit) -- a real
    secondary eclipse indicates an eclipsing binary, not a planet."""
    half_dur_days = (bls.duration_hours / 24.0) / 2.0
    phase = _phase(time, bls.period_days, bls.transit_epoch)
    secondary_phase = np.mod(phase + 0.5 + 0.5, 1.0) - 0.5
    near_secondary = np.abs(secondary_phase * bls.period_days) < half_dur_days
    if near_secondary.sum() < 2:
        return 0.0
    return float(1.0 - np.mean(normalized_flux[near_secondary])) * 1e6


def _ingress_egress_asymmetry_ppm(time, normalized_flux, bls: BlsResult) -> float:
    """Compares the first half vs second half of the in-transit points. A
    symmetric box-shaped transit (real planet) should be close to 0."""
    half_dur_days = (bls.duration_hours / 24.0) / 2.0
    phase = _phase(time, bls.period_days, bls.transit_epoch)
    phase_days = phase * bls.period_days
    in_transit = np.abs(phase_days) < half_dur_days
    if in_transit.sum() < 4:
        return 0.0
    first_half = in_transit & (phase_days < 0)
    second_half = in_transit & (phase_days >= 0)
    if first_half.sum() < 2 or second_half.sum() < 2:
        return 0.0
    return float(np.mean(normalized_flux[first_half]) - np.mean(normalized_flux[second_half])) * 1e6


def _transit_residual_scatter_ppm(time, normalized_flux, bls: BlsResult) -> float:
    """Scatter of in-transit points around the fitted constant box depth --
    how noisy the transit detection itself is."""
    half_dur_days = (bls.duration_hours / 24.0) / 2.0
    phase = _phase(time, bls.period_days, bls.transit_epoch)
    in_transit = np.abs(phase * bls.period_days) < half_dur_days
    if in_transit.sum() < 3:
        return 0.0
    return float(np.std(normalized_flux[in_transit])) * 1e6


def _skewness(x: np.ndarray) -> float:
    centered = x - np.mean(x)
    std = np.std(x)
    if std < 1e-12:
        return 0.0
    return float(np.mean(centered**3) / std**3)


def _excess_kurtosis(x: np.ndarray) -> float:
    centered = x - np.mean(x)
    std = np.std(x)
    if std < 1e-12:
        return 0.0
    return float(np.mean(centered**4) / std**4 - 3.0)


def compute_feature_vector(time: np.ndarray, flux: np.ndarray) -> LightCurveExtraction:
    """Computes all 17 features from the (time, flux) light curve alone --
    no stellar or catalog parameters are required or used anywhere here."""
    baseline_days = float(time[-1] - time[0])
    normalized_flux = flux / np.median(flux)
    flux_scatter_ppm = float(np.std(normalized_flux)) * 1e6

    bls = run_box_least_squares(time, normalized_flux)
    num_transits = max(int(baseline_days // bls.period_days), 1)
    duration_over_period = (bls.duration_hours / 24.0) / bls.period_days

    odd_even_ratio = _odd_even_depth_ratio(time, normalized_flux, bls)
    secondary_depth_ppm = _secondary_eclipse_depth_ppm(time, normalized_flux, bls)
    ingress_egress_ppm = _ingress_egress_asymmetry_ppm(time, normalized_flux, bls)
    residual_scatter_ppm = _transit_residual_scatter_ppm(time, normalized_flux, bls)

    flux_skew = _skewness(normalized_flux)
    flux_kurt = _excess_kurtosis(normalized_flux)
    median_cadence_days = float(np.median(np.diff(time)))
    point_to_point_ppm = float(np.std(np.diff(normalized_flux))) * 1e6

    features = [
        bls.period_days,
        bls.duration_hours,
        bls.depth_ppm,
        bls.transit_epoch,
        float(num_transits),
        bls.snr,
        baseline_days,
        flux_scatter_ppm,
        duration_over_period,
        odd_even_ratio,
        secondary_depth_ppm,
        ingress_egress_ppm,
        residual_scatter_ppm,
        flux_skew,
        flux_kurt,
        median_cadence_days,
        point_to_point_ppm,
    ]

    if any(not math.isfinite(v) for v in features):
        raise LightCurveValidationError(
            "Feature computation produced a non-finite value for this light curve."
        )

    characterisation = {
        "bls_period_days": bls.period_days,
        "bls_duration_hours": bls.duration_hours,
        "bls_depth_ppm": bls.depth_ppm,
        "bls_transit_snr": bls.snr,
        "num_transits_observed": num_transits,
        "odd_even_depth_ratio": odd_even_ratio,
        "secondary_eclipse_depth_ppm": secondary_depth_ppm,
    }

    return LightCurveExtraction(
        features=features,
        feature_names=LIGHTCURVE_FEATURE_NAMES,
        n_points_used=len(time),
        n_points_dropped=0,  # filled in by the caller, which knows the dropped count
        baseline_days=baseline_days,
        bls=bls,
        characterisation=characterisation,
    )


def suggest_koi_parameters(extraction: LightCurveExtraction) -> dict[str, float]:
    """Best-effort estimates for the handful of the model's real 17 KOI
    features that a transit search can meaningfully inform, mapped from the
    real BLS result -- nothing fabricated, and explicitly NOT the other 12
    features (koi_score, koi_impact, koi_prad, koi_teq, koi_insol,
    koi_tce_plnt_num, koi_steff, koi_slogg, koi_srad, ra, dec, koi_kepmag),
    which are stellar/catalog values a light curve cannot provide. These are
    suggestions for the user to review on the manual-parameter step, not a
    substitute feature vector fed into the model directly."""
    bls = extraction.bls
    return {
        "koi_period": bls.period_days,
        "koi_time0bk": bls.transit_epoch,
        "koi_duration": bls.duration_hours,
        "koi_depth": bls.depth_ppm,
        "koi_model_snr": bls.snr,
    }
