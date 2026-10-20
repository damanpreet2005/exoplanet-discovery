"""
Stage 2: Physics Validation.

Independent, read-only cross-checks of a candidate's reported/derived transit
and orbital parameters against standard transit-photometry and orbital-
mechanics relations (Seager & Mallen-Ornelas 2003; Winn 2010 transit-timing
review; Kepler's third law). This module is entirely separate from -- and
never influences or is influenced by -- the trained Random Forest + CNN
ensemble in app/predictor.py. It answers a different question: "is this
candidate's *reported geometry* physically self-consistent?", not "does the
classifier think this is a planet?". The two reports are never combined into
a single probability.

Every test returns exactly one of three statuses (never more, never a
numeric "confidence" blending the two systems):

  PASS             Consistent with the adopted physical model within the
                    documented tolerance.
  REVIEW_REQUIRED  A real discrepancy or geometric inconsistency was found.
                    This never means "false positive" -- genuine planets can
                    have noisy/incomplete catalog parameters, and orbital
                    mechanics alone cannot distinguish a planet from a
                    small/dim stellar companion (eclipsing binary). It means
                    a human should look closer, nothing more.
  NOT_EVALUATED    A required input was missing, non-finite, or physically
                    invalid (e.g. non-positive radius), so no comparison was
                    performed. Never a fabricated numeric result.

Units in: koi_period (days), koi_impact (dimensionless), koi_duration
(hours), koi_depth (ppm -- same convention used throughout this service, see
app/feature_aliases.FEATURE_DEFINITIONS and app/feature_engine.py), koi_prad
(Earth radii), koi_srad (Solar radii), koi_steff (K), koi_slogg
(log10(cm/s^2)). These are exactly the units the rest of this service already
uses for these fields -- nothing here re-defines a convention.

Tolerances are explicit module-level constants, each with a documented
rationale -- reasonable engineering judgment calls for a first-pass physical-
plausibility screen, not values taken from a single universally agreed
published standard.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.astrophysics import (
    AU_M,
    R_EARTH_M,
    R_SUN_M,
    semi_major_axis_au,
    stellar_mass_from_logg_radius,
)

# Rearth / Rsun -- the exact constant behind the user-facing form of Test 1's
# equation: delta_ppm ~= 1e6 * (0.0091577 * Rp[earth] / Rstar[solar])^2
RADIUS_RATIO_EARTH_TO_SUN = R_EARTH_M / R_SUN_M  # ~0.0091577

PASS = "PASS"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
NOT_EVALUATED = "NOT_EVALUATED"

# ---- documented tolerances -------------------------------------------------
# Test 1 (planet size / transit depth): delta ~= (Rp/Rstar)^2 assumes a
# uniformly bright stellar disk, a centrally-crossing (non-grazing) transit,
# and no third-light dilution. Limb darkening alone typically shifts the
# *measured* depth by roughly 5-20% depending on the star's limb-darkening
# coefficients and the impact parameter (Mandel & Agol 2002); grazing
# geometry (b close to 1 + Rp/Rstar) can suppress it far more. 30% is a
# generous first-pass screen that absorbs ordinary limb-darkening-scale
# effects while still catching gross (factor-of-2-or-more) inconsistencies.
PLANET_SIZE_RELATIVE_TOLERANCE = 0.30

# Test 2 (transit duration): T14 depends on a/Rstar (itself only available
# via the assumed-circular Kepler's-third-law estimate below), the impact
# parameter, and Rp/Rstar -- each individually uncertain here. 25% reflects
# that duration responds to these inputs less steeply than depth does to
# Rp/Rstar, while still being forgiving of the circular-orbit assumption's
# effect for a typical (non-extreme) eccentricity.
TRANSIT_DURATION_RELATIVE_TOLERANCE = 0.25


def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _positive_finite(x) -> bool:
    return _finite(x) and x > 0


@dataclass
class Measurement:
    """A single numeric value with its unit -- never a bare float, so a
    frontend or report can never accidentally display a value without
    knowing what it means."""

    value: float | None
    unit: str

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit}


@dataclass
class Discrepancy:
    absolute: Measurement
    relative: float | None
    relative_valid: bool
    note: str

    def to_dict(self) -> dict:
        return {
            "absolute": self.absolute.to_dict(),
            "relative": self.relative,
            "relative_valid": self.relative_valid,
            "note": self.note,
        }


@dataclass
class Tolerance:
    relative_tolerance: float | None
    rationale: str

    def to_dict(self) -> dict:
        return {"relative_tolerance": self.relative_tolerance, "rationale": self.rationale}


@dataclass
class CalculationDetails:
    equation: str
    inputs: dict[str, Measurement]
    derived: dict[str, Measurement]

    def to_dict(self) -> dict:
        return {
            "equation": self.equation,
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "derived": {k: v.to_dict() for k, v in self.derived.items()},
        }


@dataclass
class PhysicsTestResult:
    test_id: str
    name: str
    status: str
    summary: str
    observed: dict[str, Measurement]
    expected: dict[str, Measurement]
    discrepancy: Discrepancy | None
    tolerance: Tolerance
    assumptions: list[str]
    missing_data: list[str]
    calculation: CalculationDetails
    consistency_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "observed": {k: v.to_dict() for k, v in self.observed.items()},
            "expected": {k: v.to_dict() for k, v in self.expected.items()},
            "discrepancy": self.discrepancy.to_dict() if self.discrepancy else None,
            "tolerance": self.tolerance.to_dict(),
            "assumptions": self.assumptions,
            "missing_data": self.missing_data,
            "calculation": self.calculation.to_dict(),
            "consistency_checks": self.consistency_checks,
        }


@dataclass
class PhysicsValidationReport:
    object_id: str | None
    tests: list[PhysicsTestResult]
    generated_at: str

    @property
    def counts(self) -> dict[str, int]:
        counts = {PASS: 0, REVIEW_REQUIRED: 0, NOT_EVALUATED: 0}
        for t in self.tests:
            counts[t.status] += 1
        return counts

    @property
    def overall_status(self) -> str:
        c = self.counts
        if c[REVIEW_REQUIRED] > 0:
            return REVIEW_REQUIRED
        if c[PASS] > 0 and c[NOT_EVALUATED] > 0:
            return "PARTIAL"
        if c[NOT_EVALUATED] == len(self.tests):
            return NOT_EVALUATED
        return PASS

    def summary_message(self) -> str:
        c = self.counts
        return (
            f"{c[PASS]} of {len(self.tests)} test(s) passed, "
            f"{c[REVIEW_REQUIRED]} require investigation, "
            f"{c[NOT_EVALUATED]} could not be evaluated."
        )

    def issues_and_recommendations(self) -> tuple[list[str], list[str]]:
        """Derived entirely from the actual per-test results -- never
        populated with manufactured warnings just to fill the section."""
        issues: list[str] = []
        recommendations: list[str] = []
        for t in self.tests:
            if t.status == REVIEW_REQUIRED:
                issues.append(f"{t.name}: {t.summary}")
                recommendations.append(
                    f"Re-examine the inputs behind {t.name} (see its calculation details) "
                    "and, if available, cross-check against an independent catalog or a "
                    "fresh light-curve fit before treating this candidate as confirmed."
                )
            elif t.status == NOT_EVALUATED and t.missing_data:
                issues.append(
                    f"{t.name} could not be evaluated -- missing or invalid: {', '.join(t.missing_data)}."
                )
                recommendations.append(
                    f"Supply or correct {', '.join(t.missing_data)} to enable {t.name}."
                )
        return issues, recommendations

    def to_dict(self) -> dict:
        issues, recommendations = self.issues_and_recommendations()
        c = self.counts
        return {
            "object_id": self.object_id,
            "overall_status": self.overall_status,
            "summary": {
                "tests_passed": c[PASS],
                "tests_review_required": c[REVIEW_REQUIRED],
                "tests_not_evaluated": c[NOT_EVALUATED],
                "message": self.summary_message(),
            },
            "tests": [t.to_dict() for t in self.tests],
            "issues": issues,
            "recommendations": recommendations,
            "generated_at": self.generated_at,
        }


# ---- Test 1: Planet Size Validation ---------------------------------------

def _test_planet_size(f: dict[str, float | None]) -> PhysicsTestResult:
    depth_ppm = f.get("koi_depth")
    prad = f.get("koi_prad")
    srad = f.get("koi_srad")

    assumptions = [
        "The planet crosses the stellar disk centrally (grazing geometry is not modeled); "
        "a transit with impact parameter close to 1 + Rp/Rstar will show a shallower "
        "measured depth than this formula predicts.",
        "The stellar disk is treated as uniformly bright (no limb-darkening correction), "
        "which can shift the true relation by roughly 5-20% depending on the star.",
        "No third-light dilution: no unresolved companion star is contaminating the "
        "measured flux.",
    ]
    equation = "delta_ppm ~= 1e6 * (0.0091577 * Rp[Earth radii] / Rstar[Solar radii])^2"
    inputs = {
        "koi_depth": Measurement(depth_ppm, "ppm"),
        "koi_prad": Measurement(prad, "Earth radii"),
        "koi_srad": Measurement(srad, "Solar radii"),
    }
    tolerance = Tolerance(
        PLANET_SIZE_RELATIVE_TOLERANCE,
        "Generous first-pass screen absorbing ordinary limb-darkening-scale effects "
        "(~5-20%) while still catching gross (factor-of-2+) inconsistencies.",
    )

    missing: list[str] = []
    if not _positive_finite(depth_ppm):
        missing.append("koi_depth")
    if not _positive_finite(prad):
        missing.append("koi_prad")
    if not _positive_finite(srad):
        missing.append("koi_srad")

    if missing:
        return PhysicsTestResult(
            test_id="planet_size",
            name="Planet Size Validation",
            status=NOT_EVALUATED,
            summary=(
                "Could not be evaluated: " + ", ".join(missing) +
                " is missing, non-numeric, or not a positive value."
            ),
            observed={"transit_depth": Measurement(depth_ppm, "ppm")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=missing,
            calculation=CalculationDetails(equation, inputs, {}),
        )

    k = RADIUS_RATIO_EARTH_TO_SUN * prad / srad
    expected_ppm = 1e6 * k ** 2
    abs_disc = abs(depth_ppm - expected_ppm)
    rel_disc = abs_disc / depth_ppm
    status = PASS if rel_disc <= PLANET_SIZE_RELATIVE_TOLERANCE else REVIEW_REQUIRED

    if status == PASS:
        summary = (
            f"Observed transit depth ({depth_ppm:.1f} ppm) is consistent with the depth "
            f"expected from the reported planet/stellar radii ({expected_ppm:.1f} ppm) "
            f"within the {PLANET_SIZE_RELATIVE_TOLERANCE:.0%} tolerance."
        )
    else:
        summary = (
            f"Observed transit depth ({depth_ppm:.1f} ppm) differs from the depth expected "
            f"from the reported planet/stellar radii ({expected_ppm:.1f} ppm) by "
            f"{rel_disc:.0%}, beyond the {PLANET_SIZE_RELATIVE_TOLERANCE:.0%} tolerance -- "
            "the reported radii, the measured depth, or an unmodeled grazing/dilution "
            "effect may be inconsistent."
        )

    return PhysicsTestResult(
        test_id="planet_size",
        name="Planet Size Validation",
        status=status,
        summary=summary,
        observed={"transit_depth": Measurement(depth_ppm, "ppm")},
        expected={"transit_depth": Measurement(expected_ppm, "ppm")},
        discrepancy=Discrepancy(
            absolute=Measurement(abs_disc, "ppm"),
            relative=rel_disc,
            relative_valid=True,
            note="Relative to the observed transit depth.",
        ),
        tolerance=tolerance,
        assumptions=assumptions,
        missing_data=[],
        calculation=CalculationDetails(
            equation, inputs,
            {
                "radius_ratio_k": Measurement(k, "Rp/Rstar"),
                "expected_depth": Measurement(expected_ppm, "ppm"),
            },
        ),
    )


# ---- Test 2: Transit Duration Validation -----------------------------------

def _test_transit_duration(f: dict[str, float | None]) -> PhysicsTestResult:
    period = f.get("koi_period")
    impact = f.get("koi_impact")
    duration_hours = f.get("koi_duration")
    prad = f.get("koi_prad")
    srad = f.get("koi_srad")
    slogg = f.get("koi_slogg")

    assumptions = [
        "Circular orbit (eccentricity = 0) -- none of the 17 model inputs constrain "
        "eccentricity, so this is the same simplifying assumption used elsewhere in this "
        "service (see app/astrophysics.py).",
        "Stellar mass is derived from the candidate's own koi_slogg and koi_srad via "
        "g = G*M/R^2 -- not an independent mass measurement, and not a solar-density "
        "assumption.",
        "The impact parameter (koi_impact) is taken at face value.",
    ]
    equation = (
        "T14 ~= (P / pi) * arcsin( sqrt((1+k)^2 - b^2) / (a/Rstar) ), "
        "k = Rp/Rstar, with a/Rstar from Kepler's third law"
    )
    inputs = {
        "koi_period": Measurement(period, "days"),
        "koi_impact": Measurement(impact, "dimensionless"),
        "koi_duration": Measurement(duration_hours, "hours"),
        "koi_prad": Measurement(prad, "Earth radii"),
        "koi_srad": Measurement(srad, "Solar radii"),
        "koi_slogg": Measurement(slogg, "log10(cm/s^2)"),
    }
    tolerance = Tolerance(
        TRANSIT_DURATION_RELATIVE_TOLERANCE,
        "Reflects combined uncertainty from the circular-orbit assumption and the "
        "derived (not independently measured) stellar mass and a/Rstar.",
    )

    missing: list[str] = []
    if not _positive_finite(period):
        missing.append("koi_period")
    if not _finite(impact) or impact < 0:
        missing.append("koi_impact")
    if not _positive_finite(duration_hours):
        missing.append("koi_duration")
    if not _positive_finite(prad):
        missing.append("koi_prad")
    if not _positive_finite(srad):
        missing.append("koi_srad")
    if not _finite(slogg):
        missing.append("koi_slogg")

    def not_evaluated(reason: str, extra_missing: list[str] | None = None) -> PhysicsTestResult:
        return PhysicsTestResult(
            test_id="transit_duration",
            name="Transit Duration Validation",
            status=NOT_EVALUATED,
            summary=reason,
            observed={"transit_duration": Measurement(duration_hours, "hours")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=missing + (extra_missing or []),
            calculation=CalculationDetails(equation, inputs, {}),
        )

    if missing:
        return not_evaluated(
            "Could not be evaluated: " + ", ".join(missing) + " is missing, non-numeric, "
            "or physically invalid."
        )

    mass_solar = stellar_mass_from_logg_radius(slogg, srad)
    if mass_solar is None:
        return not_evaluated(
            "Could not be evaluated: stellar mass could not be derived from koi_slogg and "
            "koi_srad."
        )

    a_au = semi_major_axis_au(period, mass_solar)
    if a_au is None:
        return not_evaluated(
            "Could not be evaluated: the semi-major axis could not be derived from the "
            "orbital period and the derived stellar mass."
        )

    a_over_rstar = (a_au * AU_M) / (srad * R_SUN_M)
    k = RADIUS_RATIO_EARTH_TO_SUN * prad / srad
    geometry_term = (1 + k) ** 2 - impact ** 2

    derived = {
        "stellar_mass": Measurement(mass_solar, "Solar masses"),
        "semi_major_axis": Measurement(a_au, "AU"),
        "a_over_rstar": Measurement(a_over_rstar, "dimensionless"),
        "radius_ratio_k": Measurement(k, "Rp/Rstar"),
    }

    if geometry_term < 0:
        return PhysicsTestResult(
            test_id="transit_duration",
            name="Transit Duration Validation",
            status=REVIEW_REQUIRED,
            summary=(
                "The reported impact parameter is larger than 1 + Rp/Rstar: for this "
                "planet/stellar radius ratio, the reported geometry implies the planet "
                "never actually crosses the stellar disk, so no transit duration can be "
                "predicted from it."
            ),
            observed={"transit_duration": Measurement(duration_hours, "hours")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=[],
            calculation=CalculationDetails(equation, inputs, derived),
        )

    ratio = math.sqrt(geometry_term) / a_over_rstar
    if ratio > 1:
        return PhysicsTestResult(
            test_id="transit_duration",
            name="Transit Duration Validation",
            status=REVIEW_REQUIRED,
            summary=(
                "The derived orbit (a/Rstar from Kepler's third law) is too small relative "
                "to the reported impact parameter and radius ratio for this formula to "
                "produce a valid transit duration -- the reported period, stellar "
                "parameters, or impact parameter may be inconsistent with each other."
            ),
            observed={"transit_duration": Measurement(duration_hours, "hours")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=[],
            calculation=CalculationDetails(equation, inputs, derived),
        )

    expected_duration_days = (period / math.pi) * math.asin(ratio)
    expected_duration_hours = expected_duration_days * 24.0
    abs_disc = abs(duration_hours - expected_duration_hours)
    rel_disc = abs_disc / duration_hours
    status = PASS if rel_disc <= TRANSIT_DURATION_RELATIVE_TOLERANCE else REVIEW_REQUIRED

    if status == PASS:
        summary = (
            f"Observed transit duration ({duration_hours:.2f} h) is consistent with the "
            f"duration expected from the orbital configuration ({expected_duration_hours:.2f} h) "
            f"within the {TRANSIT_DURATION_RELATIVE_TOLERANCE:.0%} tolerance."
        )
    else:
        summary = (
            f"Observed transit duration ({duration_hours:.2f} h) differs from the duration "
            f"expected from the orbital configuration ({expected_duration_hours:.2f} h) by "
            f"{rel_disc:.0%}, beyond the {TRANSIT_DURATION_RELATIVE_TOLERANCE:.0%} tolerance."
        )

    derived["expected_duration"] = Measurement(expected_duration_hours, "hours")

    return PhysicsTestResult(
        test_id="transit_duration",
        name="Transit Duration Validation",
        status=status,
        summary=summary,
        observed={"transit_duration": Measurement(duration_hours, "hours")},
        expected={"transit_duration": Measurement(expected_duration_hours, "hours")},
        discrepancy=Discrepancy(
            absolute=Measurement(abs_disc, "hours"),
            relative=rel_disc,
            relative_valid=True,
            note="Relative to the observed transit duration.",
        ),
        tolerance=tolerance,
        assumptions=assumptions,
        missing_data=[],
        calculation=CalculationDetails(equation, inputs, derived),
    )


# ---- Test 3: Orbital Physics Validation ------------------------------------

def _test_orbital_physics(f: dict[str, float | None]) -> PhysicsTestResult:
    period = f.get("koi_period")
    srad = f.get("koi_srad")
    slogg = f.get("koi_slogg")
    impact = f.get("koi_impact")
    prad = f.get("koi_prad")

    assumptions = [
        "The planet's mass is negligible compared with the star's, so Kepler's third law "
        "is applied using the stellar mass alone (P^2 = 4*pi^2*a^3 / (G*Mstar)).",
        "Stellar mass is derived from the candidate's own koi_slogg and koi_srad via "
        "g = G*M/R^2, not assumed to be solar.",
        "Kepler's third law describes orbital mechanics only -- it cannot by itself "
        "distinguish a planet from a low-mass stellar companion (e.g. an eclipsing "
        "binary); it only checks whether the reported orbit is internally consistent.",
    ]
    equation = "a ~= (G * Mstar * P^2 / (4*pi^2))^(1/3), via Kepler's third law"
    inputs = {
        "koi_period": Measurement(period, "days"),
        "koi_srad": Measurement(srad, "Solar radii"),
        "koi_slogg": Measurement(slogg, "log10(cm/s^2)"),
    }
    tolerance = Tolerance(None, "This test checks geometric self-consistency, not a tolerance band.")

    missing: list[str] = []
    if not _positive_finite(period):
        missing.append("koi_period")
    if not _positive_finite(srad):
        missing.append("koi_srad")
    if not _finite(slogg):
        missing.append("koi_slogg")

    if missing:
        return PhysicsTestResult(
            test_id="orbital_physics",
            name="Orbital Physics Validation",
            status=NOT_EVALUATED,
            summary=(
                "Could not be evaluated: " + ", ".join(missing) + " is missing, non-numeric, "
                "or not a positive value."
            ),
            observed={"orbital_period": Measurement(period, "days")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=missing,
            calculation=CalculationDetails(equation, inputs, {}),
        )

    mass_solar = stellar_mass_from_logg_radius(slogg, srad)
    if mass_solar is None:
        return PhysicsTestResult(
            test_id="orbital_physics",
            name="Orbital Physics Validation",
            status=NOT_EVALUATED,
            summary="Could not be evaluated: stellar mass could not be derived from koi_slogg and koi_srad.",
            observed={"orbital_period": Measurement(period, "days")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=["koi_slogg", "koi_srad"],
            calculation=CalculationDetails(equation, inputs, {}),
        )

    a_au = semi_major_axis_au(period, mass_solar)
    if a_au is None:
        return PhysicsTestResult(
            test_id="orbital_physics",
            name="Orbital Physics Validation",
            status=NOT_EVALUATED,
            summary="Could not be evaluated: the semi-major axis could not be derived from the orbital period and the derived stellar mass.",
            observed={"orbital_period": Measurement(period, "days")},
            expected={},
            discrepancy=None,
            tolerance=tolerance,
            assumptions=assumptions,
            missing_data=[],
            calculation=CalculationDetails(equation, inputs, {"stellar_mass": Measurement(mass_solar, "Solar masses")}),
        )

    a_over_rstar = (a_au * AU_M) / (srad * R_SUN_M)
    derived = {
        "stellar_mass": Measurement(mass_solar, "Solar masses"),
        "semi_major_axis": Measurement(a_au, "AU"),
        "a_over_rstar": Measurement(a_over_rstar, "dimensionless"),
    }

    consistency_checks: list[str] = []
    status = PASS
    issues: list[str] = []

    if a_over_rstar <= 1:
        status = REVIEW_REQUIRED
        issues.append(
            f"a/Rstar = {a_over_rstar:.2f} implies the orbit is not larger than the star "
            "itself, which is physically implausible for a transiting companion."
        )
    else:
        consistency_checks.append(
            f"a/Rstar = {a_over_rstar:.2f} > 1: the orbit is larger than the star, as required."
        )

    if _positive_finite(prad) and _finite(impact) and impact >= 0:
        k = RADIUS_RATIO_EARTH_TO_SUN * prad / srad
        geometry_term = (1 + k) ** 2 - impact ** 2
        if geometry_term < 0 or math.sqrt(max(geometry_term, 0.0)) / a_over_rstar > 1:
            status = REVIEW_REQUIRED
            issues.append(
                "Cross-check against the reported impact parameter and planet radius "
                "(Transit Duration Validation's geometry) finds no consistent transit "
                "geometry for this orbit."
            )
        else:
            consistency_checks.append(
                "Cross-check against the reported impact parameter and planet radius "
                "finds a geometrically consistent transit for this orbit."
            )
    else:
        consistency_checks.append(
            "Cross-check against transit geometry skipped: koi_impact and/or koi_prad unavailable."
        )

    if status == PASS:
        summary = (
            f"The reported orbital period ({period:.4f} days) and derived stellar mass "
            f"({mass_solar:.2f} Msun) yield a self-consistent orbit (a = {a_au:.4f} AU, "
            f"a/Rstar = {a_over_rstar:.2f}). This confirms orbital-mechanics "
            "self-consistency only -- it does not by itself confirm a planetary (as "
            "opposed to stellar) companion."
        )
    else:
        summary = "Orbital configuration is not self-consistent: " + " ".join(issues)

    return PhysicsTestResult(
        test_id="orbital_physics",
        name="Orbital Physics Validation",
        status=status,
        summary=summary,
        observed={"orbital_period": Measurement(period, "days")},
        expected={},
        discrepancy=None,
        tolerance=tolerance,
        assumptions=assumptions,
        missing_data=[],
        calculation=CalculationDetails(equation, inputs, derived),
        consistency_checks=consistency_checks,
    )


def run_physics_validation(features: dict[str, float | None], object_id: str | None = None) -> PhysicsValidationReport:
    """Runs all three independent physics checks against the subset of the
    17 model features they need (koi_period, koi_impact, koi_duration,
    koi_depth, koi_prad, koi_srad, koi_slogg). Missing keys are treated as
    unavailable (None), never fabricated. This function has no FastAPI/
    Pydantic dependency -- it is plain Python, so it can be unit-tested and
    reused without standing up the web service."""
    tests = [
        _test_planet_size(features),
        _test_transit_duration(features),
        _test_orbital_physics(features),
    ]
    return PhysicsValidationReport(
        object_id=object_id,
        tests=tests,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
