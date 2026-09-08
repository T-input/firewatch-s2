"""
03_build_gif.py — KORAK 3: Izrada animiranog GIF-a s preklopljenom granicom.

Pokretanje:
    python 03_build_gif.py                # svi proizvodi
    python 03_build_gif.py falsecolor     # samo jedan proizvod

Što radi:
  Učita GeoTIFF-ove iz koraka 2, preko svake snimke nacrta granicu zaštićenog
  područja i datum, te ih spoji u GIF. Za svaki proizvod nastaje jedan GIF:
    data/output/deliblato_truecolor.gif
    data/output/deliblato_falsecolor.gif
    data/output/deliblato_nbr.gif

  U GIF ulaze SAMO kadrovi gdje snimka pokriva gotovo cijelo područje
  (>= config.MIN_COVERAGE). Poluprazne snimke (spoj Sentinel-2 orbita, gdje se
  vidi samo dio AOI-ja) se preskaču.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import sh_utils as sh
import viz

FPS = 1.0   # kadrova po sekundi u GIF-u


def _valid_mask(arr, product):
    """Boolean maska valjanih (ne-nodata) piksela za dani proizvod."""
    if product == "nbr":
        return arr[:, :, 1] >= 0.5          # dataMask pojas
    return arr[:, :, 3] > 0                 # alpha pojas (RGBA)


def frames_for(product, gdf, bbox, aoi_mask):
    """Renderiraj kadrove za jedan proizvod, preskačući slabo pokrivene snimke."""
    tifs = sorted(cfg.RASTER_DIR.glob(f"*_{product}.tif"))
    frame_paths, skipped = [], []

    for tif in tifs:
        m = re.match(r"(\d{4}-\d{2}-\d{2})_", tif.name)
        if not m:
            continue
        day = m.group(1)
        arr = sh.read_geotiff(tif)

        # --- filter pokrivenosti: preskoči ako snimka ne pokriva cijeli AOI ---
        cov = sh.data_coverage(_valid_mask(arr, product), aoi_mask)
        if cov < cfg.MIN_COVERAGE:
            skipped.append((day, cov))
            print(f"    · {day}  preskočen (pokrivenost {cov*100:.0f}%)")
            continue

        png = cfg.FRAMES_DIR / f"{day}_{product}.png"
        if product == "nbr":
            nbr, mask = arr[:, :, 0], arr[:, :, 1]
            viz.render_nbr(nbr, mask, gdf, bbox,
                           title="Deliblato — Normalised Burn Ratio", subtitle=day, out_path=png)
        else:
            label = "RGB" if product == "truecolor" else "SWIR"
            viz.render_rgb(arr, gdf, bbox,
                           title=f"Deliblato — {label}", subtitle=day, out_path=png)
        frame_paths.append(str(png))
        print(f"    ✓ {day}  ({cov*100:.0f}% pokriveno)")

    if skipped:
        print(f"    -> preskočeno {len(skipped)} slabo pokrivenih kadrova")
    return frame_paths


def main():
    products = sys.argv[1:] or ["truecolor", "falsecolor", "nbr"]
    gdf, bbox, size = sh.load_aoi()
    # maska AOI-ja na rasterskoj mreži (size = (širina, visina))
    aoi_mask = sh.aoi_pixel_mask(gdf, bbox, (size[1], size[0]))

    for product in products:
        print(f"\n=== {product} ===")
        paths = frames_for(product, gdf, bbox, aoi_mask)
        if not paths:
            print(f"  Nema dovoljno pokrivenih kadrova za '{product}'.")
            continue
        gif = cfg.OUT_DIR / f"deliblato_{product}.gif"
        viz.build_gif(paths, gif, fps=FPS)
        print(f"  ✓ GIF: {gif}  ({len(paths)} kadrova)")


if __name__ == "__main__":
    main()
