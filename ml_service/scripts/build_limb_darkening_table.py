"""
Builds data/limb_darkening_kepler_atlas9.csv: quadratic limb-darkening
coefficients in the Kepler band at every node of ExoCTK's ATLAS9 model grid.

Run OFFLINE, once, by a developer. ExoCTK is NOT a runtime dependency of the
ML service: the service only reads the CSV this script writes
(app/characterization/limb_darkening.py) and interpolates it.

Requirements (in a separate virtualenv, not the service's):
    pip install exoctk
    ExoCTK's ATLAS9 grid (modelgrid_ATLAS9.tar.gz from the ExoCTK data
    release, ~70 MB) extracted so that the FITS files are in
    $EXOCTK_DATA/modelgrid/ATLAS9/

Usage (from ml_service/):
    EXOCTK_DATA=/path/to/exoctk_data python scripts/build_limb_darkening_table.py

Method: for each grid node, ExoCTK's LDC.calculate applies the svo_filters
Kepler.K bandpass to the ATLAS9 specific-intensity spectra and fits the
quadratic law I(mu)/I(1) = 1 - u1 (1 - mu) - u2 (1 - mu)^2 (ExoCTK defaults:
mu > 0.05, mu rescaled so the limb is at I/I(1) = 0.01). Coefficients are
computed at the grid nodes only (no interpolation by ExoCTK); u1_err/u2_err
are the curve-fit errors of that law to the model intensities, not
astrophysical uncertainties.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "limb_darkening_kepler_atlas9.csv"
BANDPASS = "Kepler.K"


def main(output: Path = OUTPUT) -> None:
    if not os.environ.get("EXOCTK_DATA"):
        sys.exit("Set EXOCTK_DATA to the directory containing modelgrid/ATLAS9/.")
    from exoctk import modelgrid
    from exoctk.limb_darkening.limb_darkening_fit import LDC
    from svo_filters import svo

    grid = modelgrid.ATLAS9(resolution=700)
    ldc = LDC(grid)
    band = svo.Filter(BANDPASS)
    nodes = sorted({(float(r["Teff"]), float(r["logg"]), float(r["FeH"])) for r in grid.data})

    rows = []
    for teff, logg, feh in nodes:
        n_before = len(ldc.results)
        ldc.calculate(teff, logg, feh, "quadratic", bandpass=band)
        if len(ldc.results) == n_before:
            print(f"skipped node Teff={teff:g} logg={logg:g} [Fe/H]={feh:g}: fit failed", file=sys.stderr)
            continue
        r = ldc.results[-1]
        if (float(r["Teff"]), float(r["logg"]), float(r["FeH"])) != (teff, logg, feh):
            raise RuntimeError(f"ExoCTK returned a different node for {(teff, logg, feh)}")
        rows.append((int(teff), logg, feh, float(r["c1"]), float(r["c2"]), float(r["e1"]), float(r["e2"])))

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="") as fh:
        fh.write(f"# Quadratic limb darkening, Kepler band ({BANDPASS}, svo_filters {version('svo_filters')}), "
                 f"ExoCTK {version('exoctk')} LDC on the ATLAS9 model grid.\n")
        fh.write("# Law: I(mu)/I(1) = 1 - u1 (1 - mu) - u2 (1 - mu)^2. Computed at grid nodes only; "
                 "u*_err are law-fit errors, not astrophysical uncertainties.\n")
        fh.write(f"# Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} by "
                 "scripts/build_limb_darkening_table.py. Do not edit by hand.\n")
        writer = csv.writer(fh)
        writer.writerow(["teff", "logg", "feh", "u1", "u2", "u1_err", "u2_err"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} of {len(nodes)} grid nodes to {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT)
