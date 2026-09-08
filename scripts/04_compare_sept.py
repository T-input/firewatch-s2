"""
04_compare_sept.py — KORAK 4: Usporedba rujan 2025. vs rujan 2026.

Pokretanje:
    python 04_compare_sept.py

Što radi:
  Za svaku godinu (2025, 2026) nađe NAJVEDRIJU snimku u rujnu (najmanje oblaka),
  preuzme tri proizvoda (truecolor / falsecolor / nbr) i složi usporednu sliku
  3 reda (proizvodi) x 2 stupca (godine) s granicom područja.

  Izlaz:
    data/output/usporedba_rujan_2025_2026.png
    + pojedinačni GeoTIFF-ovi u rasters/ (za QGIS)
"""
import calendar
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config as cfg
import sh_utils as sh
import viz
from evalscripts import PRODUCTS


def best_day(config, bbox, gdf, year: int, month: int):
    """
    Nađi najvedriji dan u mjesecu KOJI POKRIVA CIJELO područje.
    Ide po danima od najmanje oblaka; za svaki provjeri pokrivenost (jeftino,
    gruba maska) i vrati prvi koji zadovolji config.MIN_COVERAGE.
    Ako nijedan ne zadovolji prag — vrati najbolje pokriven dan (uz upozorenje).
    """
    start = dt.date(year, month, 1)
    last = calendar.monthrange(year, month)[1]
    end = min(dt.date(year, month, last), dt.date.today())
    if start > dt.date.today():
        return None
    days = sh.search_days(config, bbox, start, end, max_cloud=100)
    if not days:
        return None

    def avg_cc(ccs):
        vals = [c for c in ccs if c is not None]
        return sum(vals) / len(vals) if vals else 100.0

    ordered = sorted(days, key=lambda d: avg_cc(d[1]))   # najvedriji prvi
    fallback = None
    for day, ccs in ordered:
        cov = sh.fetch_coverage(config, bbox, gdf, day)
        print(f"    {day}: oblaci~{avg_cc(ccs):.0f}%, pokrivenost {cov*100:.0f}%")
        if fallback is None or cov > fallback[1]:
            fallback = (day, cov)
        if cov >= cfg.MIN_COVERAGE:
            return day

    if fallback:
        print(f"    ! nijedan dan ne pokriva {cfg.MIN_COVERAGE*100:.0f}% — "
              f"uzimam najbolje pokriven: {fallback[0]} ({fallback[1]*100:.0f}%)")
        return fallback[0]
    return None


def main():
    config = sh.get_config()
    gdf, bbox, size = sh.load_aoi()

    picks = {}
    for year in cfg.COMPARE_YEARS:
        print(f"Rujan {year} — biram najvedriji potpuno pokriven dan:")
        day = best_day(config, bbox, gdf, year, cfg.COMPARE_MONTH)
        if day is None:
            print(f"! Nema snimke za rujan {year}.")
        else:
            print(f"  -> odabrano: {day}")
        picks[year] = day

    # preuzmi proizvode za odabrane dane
    data = {}   # (year, product) -> array
    for year, day in picks.items():
        if day is None:
            continue
        for name, spec in PRODUCTS.items():
            out = cfg.RASTER_DIR / f"{day}_{name}.tif"
            if out.exists():
                arr = sh.read_geotiff(out)
            else:
                arr = sh.fetch_array(config, bbox, size, day, spec["evalscript"])
                sh.save_geotiff(arr, bbox, out)
            data[(year, name)] = arr
            print(f"  {year} {name}: OK")

    # složi mrežu 3 (proizvodi) x 2 (godine)
    products = list(PRODUCTS.keys())
    years = list(cfg.COMPARE_YEARS)
    extent = (bbox.min_x, bbox.max_x, bbox.min_y, bbox.max_y)
    prod_label = {"truecolor": "RGB",
                  "falsecolor": "SWIR",
                  "nbr": "Normalised Burn Ratio"}

    fig, axes = plt.subplots(len(products), len(years),
                             figsize=(11, 15.5), dpi=130)
    for r, product in enumerate(products):
        for c, year in enumerate(years):
            ax = axes[r, c]
            ax.set_axis_off()
            arr = data.get((year, product))
            if arr is None:
                ax.text(0.5, 0.5, f"nema snimke\n{prod_label[product]} {year}",
                        ha="center", va="center", transform=ax.transAxes)
                continue
            if product == "nbr":
                nbr = np.ma.masked_where(arr[:, :, 1] < 0.5, arr[:, :, 0])
                ax.imshow(nbr, extent=extent, origin="upper",
                          cmap=viz.NBR_CMAP, vmin=-0.5, vmax=0.8)
                gdf.boundary.plot(ax=ax, edgecolor="black", linewidth=1.2)
            else:
                ax.imshow(arr, extent=extent, origin="upper")
                gdf.boundary.plot(ax=ax, edgecolor=viz.BORDER_COLOR, linewidth=1.4)
            ax.set_xlim(bbox.min_x, bbox.max_x)
            ax.set_ylim(bbox.min_y, bbox.max_y)
            day = picks[year]
            ax.set_title(f"{prod_label[product]} — {day}", fontsize=11)

    fig.suptitle("Deliblatska pješčara — usporedba rujan 2025. / 2026.",
                 fontsize=16, fontweight="bold", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    out = cfg.OUT_DIR / "usporedba_rujan_2025_2026.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"\n✓ Usporedba: {out}")


if __name__ == "__main__":
    main()
