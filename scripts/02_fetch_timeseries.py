"""
02_fetch_timeseries.py — KORAK 2: Preuzimanje snimaka (cijela serija).

Pokretanje:
    python 02_fetch_timeseries.py

Što radi:
  Za svaki dan sa snimkom (1.7.2026 - danas) preuzme tri proizvoda:
    - truecolor  (prirodne boje)
    - falsecolor (SWIR kompozit — vatra/opožarene površine)
    - nbr        (Normalized Burn Ratio, float)
  i spremi ih kao georeferencirane GeoTIFF-ove u data/output/rasters/.
  Te iste GeoTIFF-ove kasnije koriste skripte 03 (GIF) i 04 (usporedba),
  a možeš ih otvoriti i u QGIS-u.

  Preuzimanje se NE ponavlja za datoteke koje već postoje (možeš prekinuti i
  nastaviti). Za ponovno preuzimanje obriši datoteke iz rasters/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import sh_utils as sh
from evalscripts import PRODUCTS


def main():
    config = sh.get_config()
    gdf, bbox, size = sh.load_aoi()
    print(f"AOI: {size[0]} x {size[1]} px @ {cfg.RESOLUTION} m")

    days = sh.search_days(config, bbox, cfg.START_DATE, cfg.END_DATE,
                          cfg.MAX_CLOUD)
    print(f"Preuzimam {len(days)} dana x {len(PRODUCTS)} proizvoda "
          f"({len(days) * len(PRODUCTS)} slika)...\n")

    for i, (day, _cc) in enumerate(days, 1):
        print(f"[{i}/{len(days)}] {day}")
        for name, spec in PRODUCTS.items():
            out = cfg.RASTER_DIR / f"{day}_{name}.tif"
            if out.exists():
                print(f"    · {name:11s} već postoji")
                continue
            try:
                arr = sh.fetch_array(config, bbox, size, day, spec["evalscript"])
                sh.save_geotiff(arr, bbox, out)
                print(f"    ✓ {name:11s} -> {out.name}")
            except Exception as e:
                print(f"    ! {name:11s} GREŠKA: {e}")

    print("\n✓ Gotovo. Rasteri su u:", cfg.RASTER_DIR)


if __name__ == "__main__":
    main()
