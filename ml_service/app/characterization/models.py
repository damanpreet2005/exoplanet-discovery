"""
Structured, serialisable records for the characterization engine.

Every reported quantity is a `Parameter`: never a bare float. A parameter
carries its value, unit, provenance, uncertainty (or an explicit statement
that none is available), how it was calculated, which assumptions it rests
on, which other parameters it was computed from, and -- separately -- whether
the calculation *ran* (`status`) and whether the result is scientifically
*reliable* (`reliability`). A calculation can run successfully and still
produce an unreliable estimate (e.g. a planet radius from a 4-sigma transit).

These are deliberately kept apart from the 17-feature ML vector
(app/feature_engine.py): ML features are classifier inputs; these are
physical characterization outputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# ---- provenance categories ------------------------------------------------
CATALOG = "catalog"                  # read from the local NASA KOI catalogue
OBSERVED = "observed"                # measured directly from the light curve (no model)
FITTED = "fitted"                    # parameter of the transit-model fit
DERIVED = "derived"                  # computed from other parameters via a physical relation
MODEL_ESTIMATED = "model_estimated"  # empirical/statistical model (e.g. mass-radius relation), not a measurement
MANUAL_OVERRIDE = "manual_override"  # supplied by an expert, replacing the automatic value
UNAVAILABLE = "unavailable"          # could not be determined; value is None, never 0
ASSUMED = "assumed"                  # adopted by assumption (e.g. circular orbit, Bond albedo), never measured

PROVENANCES = (CATALOG, OBSERVED, FITTED, DERIVED, MODEL_ESTIMATED, MANUAL_OVERRIDE, ASSUMED, UNAVAILABLE)

# Evidence class: what kind of knowledge a value represents, mapped from the
# provenance (one status system; `evidence` only refines it). A catalogue
# value is catalogue-derived unless its source marks it as a measurement.
MEASURED = "measured"
CATALOGUE_DERIVED = "catalogue_derived"
EVIDENCE_BY_PROVENANCE = {
    CATALOG: CATALOGUE_DERIVED, OBSERVED: MEASURED, FITTED: MEASURED, DERIVED: "derived",
    MODEL_ESTIMATED: "model_estimated", MANUAL_OVERRIDE: "expert_override", ASSUMED: "assumed",
    UNAVAILABLE: "unavailable",
}

# ---- calculation status (did it run?) --------------------------------------
STATUS_COMPUTED = "computed"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_APPLICABLE = "not_applicable"

# ---- reliability (is the result trustworthy?) ------------------------------
RELIABLE = "reliable"            # inputs well constrained, validity conditions met
LOW = "low_confidence"           # computed, but poorly constrained or relies on strong assumptions
UNRELIABLE = "unreliable"        # computed, but a validity condition failed -- do not interpret
NOT_ASSESSED = "not_assessed"    # nothing to assess (unavailable)

_RELIABILITY_ORDER = {RELIABLE: 0, LOW: 1, UNRELIABLE: 2, NOT_ASSESSED: 3}


def worst_reliability(*levels: str) -> str:
    """Combines reliabilities: a result is only as reliable as its weakest input."""
    known = [lvl for lvl in levels if lvl != NOT_ASSESSED]
    if not known:
        return RELIABLE
    return max(known, key=lambda lvl: _RELIABILITY_ORDER[lvl])


@dataclass
class Uncertainty:
    """A 1-sigma-equivalent interval around the reported value.

    `lower`/`upper` are positive distances below/above the value (so
    value - lower .. value + upper is the interval). `method` says how the
    interval was obtained; `complete` is False when at least one input had
    no uncertainty and was therefore held fixed (the interval then
    *underestimates* the true uncertainty, listed in `excluded_inputs`).
    `systematic` lists effects NOT included in the statistical interval.
    """
    lower: float
    upper: float
    method: str            # "catalog" | "fit_covariance" | "analytic_first_order" | "monte_carlo" | "manual"
    interval: str = "68% (16th-84th percentile)"
    complete: bool = True
    excluded_inputs: list[str] = field(default_factory=list)
    systematic: list[str] = field(default_factory=list)


@dataclass
class Parameter:
    name: str
    label: str
    value: float | str | None
    unit: str
    provenance: str
    status: str = STATUS_COMPUTED
    reliability: str = RELIABLE
    uncertainty: Uncertainty | None = None
    method: str = ""
    equation: str = ""
    assumptions: list[str] = field(default_factory=list)   # assumption ids, see engine.ASSUMPTIONS
    depends_on: list[str] = field(default_factory=list)    # parameter names actually used
    source: str = ""                                       # catalog column / fit / formula reference
    validation: list[str] = field(default_factory=list)    # validity checks and their outcome
    missing_inputs: list[str] = field(default_factory=list)
    reason: str = ""                                       # why unavailable / why low reliability
    depends_on_override: list[str] = field(default_factory=list)
    original: dict | None = None                           # the automatic value an override replaced
    systematic_range: dict | None = None                   # value range under alternative assumptions
    alternate_units: list[dict] = field(default_factory=list)  # same quantity in other units
    display: str = ""
    evidence: str = ""                                     # see EVIDENCE_BY_PROVENANCE; set on insertion

    def to_dict(self) -> dict:
        return asdict(self)


def unavailable(name: str, label: str, unit: str, reason: str, missing: list[str] | None = None,
                depends_on: list[str] | None = None, status: str = STATUS_UNAVAILABLE) -> Parameter:
    return Parameter(
        name=name, label=label, value=None, unit=unit, provenance=UNAVAILABLE, status=status,
        reliability=NOT_ASSESSED, reason=reason, missing_inputs=list(missing or []),
        depends_on=list(depends_on or []), display="Unavailable",
    )


@dataclass
class Classification:
    name: str
    label: str
    category: str | None
    basis: str
    probability: float | None = None          # MC fraction of samples in this category, when meaningful
    probabilities: dict[str, float] | None = None
    caveats: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    status: str = STATUS_COMPUTED

    def to_dict(self) -> dict:
        return asdict(self)
