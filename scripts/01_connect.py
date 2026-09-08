"""
01_connect.py — Spajanje na Copernicus (CDSE) + popis snimaka.

Pokretanje (u VS Code terminalu, iz mape scripts/):
    python 01_connect.py

  1) Postavi vezu prema Copernicus Data Space Ecosystem (OAuth).
  2) Učitaj granicu i izračunaj područje snimanja (bbox).
  3) Preko STAC kataloga ispiši sve dane sa Sentinel-2 snimkama u danom razdoblju.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import sh_utils as sh


def main():
    print("=" * 64)
    print("  Deliblato — test spajanja na Copernicus (CDSE)")
    print("=" * 64)

    config = sh.get_config()
    print("Credentials učitani. Učitavam granicu područja...")

    gdf, bbox, size = sh.load_aoi()
    print(f"  AOI CRS      : EPSG:{cfg.CRS_EPSG} (UTM 34N)")
    print(f"  bbox         : {bbox}")
    print(f"  veličina     : {size[0]} x {size[1]} px  @ {cfg.RESOLUTION} m")

    print(f"\nTražim snimke {cfg.START_DATE} — {cfg.END_DATE} (max oblaka: "
          f"{cfg.MAX_CLOUD}%)...")
    days = sh.search_days(config, bbox, cfg.START_DATE, cfg.END_DATE,
                          cfg.MAX_CLOUD)

    if not days:
        print("  Nije pronađena nijedna snimka za zadano razdoblje.")
        return

    print(f"\nPronađeno {len(days)} dana sa snimkama:")
    for day, ccs in days:
        clouds = [c for c in ccs if c is not None]
        if clouds:
            cc_txt = f"oblaci {min(clouds):.0f}-{max(clouds):.0f}%"
        else:
            cc_txt = "oblaci n/a"
        print(f"   {day}   ({len(ccs)} pločica, {cc_txt})")

    print("\n" + "=" * 64)
    print("  ✓ Spajanje uspješno. Pokreni 02_fetch_timeseries.py")
    print("=" * 64)


if __name__ == "__main__":
    main()
