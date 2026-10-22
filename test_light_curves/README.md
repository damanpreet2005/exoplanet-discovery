# Test light curves

Two `time,flux` CSVs for testing the app end to end: one confirmed planet, one
star with no planet. Upload each with its **Object ID** below.

Both are **synthetic**: generated with the app's own limb-darkened transit
model (`ml_service/app/characterization/transit_model.py`) from the real NASA
KOI catalogue values for each target, at Kepler long cadence (29.4 min) with
Gaussian noise. They are not downloaded Kepler photometry.

| File | Object ID to enter | Kepler Input Catalog (KIC) | KOI | Catalogue disposition |
|---|---|---|---|---|
| `1_confirmed_planet_Kepler-227b_KIC10797460.csv` | `K00752.01` | KIC 10797460 | K00752.01 (Kepler-227 b) | CONFIRMED planet |
| `2_no_planet_eclipsing_binary_KIC5534814.csv` | `K00838.01` | KIC 5534814 | K00838.01 | FALSE POSITIVE (stellar eclipse) |

`KIC 10797460` and `KIC 5534814` also work as the Object ID (they resolve to
the same catalogue star).

## 1. Confirmed planet: Kepler-227 b

- Period 9.488 d, 10 transits over 100 days, noise 150 ppm.
- Catalogue geometry: Rp 2.26 R⊕, R⋆ 0.927 R☉, Teff 5455 K, log g 4.467, b = 0.146.
- Shallow (~0.05 %), flat-bottomed planetary transit; no secondary eclipse.

Expected in the app: ML class 1 (~97 %), Neptune-size planet of ~2.3 R⊕, no
secondary eclipse in Transit Vetting.

## 2. No planet: eclipsing binary K00838.01

- Period 4.859 d, 90 days, noise 300 ppm (fainter star, Kp 15.3).
- Catalogue: FALSE POSITIVE, KOI score 0, stellar-eclipse flag set; implied
  companion radius 38 R⊕ (larger than any planet), grazing geometry b = 1.26.
- Light curve: grazing primary eclipse plus a **secondary eclipse at phase 0.5**
  (40 % of the primary depth) from the luminous stellar companion, the
  classic signature that the companion is a star, not a planet.

Expected in the app: ML class 0 (~9 %), a secondary eclipse of ~1800 ppm in
Transit Vetting. The characterization engine still fits the dip and labels
its size (radius-only rules), which is why the classifier, the vetting
metrics and the Discovery Report's evidence section matter here.
