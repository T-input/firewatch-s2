"""
05_burned_area.py — KORAK 5: Procjena ukupne opožarene površine (dNBR).

Metoda (Key & Benson / USGS):
    NBR  = (B08 - B12) / (B08 + B12)            # koristi NIR i SWIR
    dNBR = NBR_prije - NBR_poslije              # opožareno = visok pozitivan dNBR

Uspoređuju se dvije Sentinel-2 snimke iz istog doba godine (rujan), da
prirodno sezonsko sušenje vegetacije ne ulazi u dNBR kao lažni požar:
    PRE  (prošli rujan, prije požara) : 2025-09-22
    POST (ovaj rujan, aktualno)       : 2026-09-02
(možeš ih promijeniti dolje ili predati kao argumente:
    python 05_burned_area.py 2025-09-22 2026-09-02 )

Računa površinu po razredima težine i UKUPNO, unutar granice zaštićenog
područja. Sprema:
    data/output/rasters/dnbr_<PRE>_<POST>.tif      (dNBR, za QGIS)
    data/output/rasters/burnclass_<PRE>_<POST>.tif (razredi 0-3, za QGIS)
    data/output/opozarena_povrsina_<PRE>_<POST>.png (karta + legenda)
    data/output/opozarena_povrsina_<PRE>_<POST>.txt (sažetak površina)

VAŽNO: procjena je približna. Oblaci, sjene, vodene površine i poljoprivredne
promjene mogu lažno podići/spustiti dNBR. Za službenu brojku validiraj na
vedrim snimkama i po mogućnosti maskiraj oblake.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

import config as cfg
import sh_utils as sh
import evalscripts as ev

# --- Datumi snimaka (možeš promijeniti ili predati kao argumenti) ----------
PRE_DATE = "2025-09-22"    # prošli rujan (prije ovogodišnjeg požara)
POST_DATE = "2026-09-02"   # ovaj rujan (aktualno stanje)

# --- Pragovi težine opožarenosti (dNBR, prema USGS/Key & Benson) -----------
# granice razreda i njihove boje/oznake
CLASS_EDGES = [0.10, 0.27, 0.66]         # < .10 neopožareno; ... ; > .66 visok
CLASS_LABELS = ["Neopožareno",
                "Niski intenzitet",
                "Umjeren intenzitet",
                "Visok intenzitet"]
CLASS_COLORS = ["#A9DBAA", "#ffffb2", "#fd8d3c", "#bd0026"]
BURN_THRESHOLD = 0.27    # "jasno opožareno" (naslovna brojka)


def get_nbr(bbox, size, day):
    """
    Vrati (nbr, mask) za dan. Koristi već preuzeti GeoTIFF ako postoji;
    inače se spaja na Copernicus i preuzme (credentials trebaju samo tada).
    """
    tif = cfg.RASTER_DIR / f"{day}_nbr.tif"
    if tif.exists():
        arr = sh.read_geotiff(tif)
        print(f"  {day}: učitano iz {tif.name}")
    else:
        print(f"  {day}: preuzimam NBR sa Copernicusa...")
        config = sh.get_config()
        arr = sh.fetch_array(config, bbox, size, day, ev.NBR)
        sh.save_geotiff(arr, bbox, tif)
    return arr[:, :, 0], arr[:, :, 1]


def classify(dnbr):
    """Vrati polje razreda 0..3 prema CLASS_EDGES."""
    cls = np.zeros(dnbr.shape, dtype="uint8")
    cls[dnbr >= CLASS_EDGES[0]] = 1
    cls[dnbr >= CLASS_EDGES[1]] = 2
    cls[dnbr >= CLASS_EDGES[2]] = 3
    return cls


def main():
    pre = sys.argv[1] if len(sys.argv) > 1 else PRE_DATE
    post = sys.argv[2] if len(sys.argv) > 2 else POST_DATE
    print(f"dNBR usporedba:  PRE={pre}  ->  POST={post}\n")

    # Rastersku mrežu (bbox/size) uzimamo iz glavne granice — ista kao u
    # ostatku pipelinea, da se NBR rasteri iz koraka 2 mogu ponovno iskoristiti.
    _grid_gdf, bbox, size = sh.load_aoi()
    # Za račun površine i prikaz koristimo granicu BEZ DUNAVA.
    gdf = sh.load_boundary(cfg.AOI_GPKG_BURN)
    print(f"Granica (račun): {cfg.AOI_GPKG_BURN.name}")

    nbr_pre, m_pre = get_nbr(bbox, size, pre)
    nbr_post, m_post = get_nbr(bbox, size, post)

    # dNBR i maska valjanih piksela unutar granice
    dnbr = nbr_pre - nbr_post
    aoi = sh.aoi_pixel_mask(gdf, bbox, (size[1], size[0]))
    valid = (m_pre >= 0.5) & (m_post >= 0.5) & aoi

    # upozorenje ako neka snimka ne pokriva cijelo područje
    cov_pre = sh.data_coverage(m_pre >= 0.5, aoi)
    cov_post = sh.data_coverage(m_post >= 0.5, aoi)
    print(f"\nPokrivenost AOI: PRE {cov_pre*100:.0f}%, POST {cov_post*100:.0f}%")
    if min(cov_pre, cov_post) < cfg.MIN_COVERAGE:
        print("  ! UPOZORENJE: snimka ne pokriva cijelo područje — "
              "procjena je nepotpuna. Odaberi datume s punom pokrivenošću.")

    # razredi + površine
    cls = classify(dnbr)
    cls_masked = np.where(valid, cls, 0)

    px_area_ha = (cfg.RESOLUTION ** 2) / 10_000.0   # m2 -> ha
    total_aoi_ha = int(aoi.sum()) * px_area_ha

    print("\n" + "=" * 58)
    print(f"  OPOŽARENA POVRŠINA — Deliblato ({pre} -> {post})")
    print("=" * 58)
    print(f"  Ukupno područje (AOI): {total_aoi_ha:9.1f} ha  "
          f"({total_aoi_ha/100:.1f} km2)")
    print("-" * 58)
    lines = []
    for i, label in enumerate(CLASS_LABELS):
        n = int(np.sum((cls_masked == i) & valid))
        ha = n * px_area_ha
        pct = 100 * ha / total_aoi_ha if total_aoi_ha else 0
        row = f"  {label:24s}: {ha:9.1f} ha  ({pct:4.1f}%)"
        print(row)
        lines.append(row)

    burned_ha = int(np.sum((dnbr >= BURN_THRESHOLD) & valid)) * px_area_ha
    burned_low_ha = int(np.sum((dnbr >= CLASS_EDGES[0]) & valid)) * px_area_ha
    print("-" * 58)
    print(f"  >> JASNO OPOŽARENO (dNBR>={BURN_THRESHOLD}): {burned_ha:8.1f} ha "
          f"({burned_ha/100:.2f} km2, {100*burned_ha/total_aoi_ha:.1f}% područja)")
    print(f"     uključujući niski intenzitet (dNBR>={CLASS_EDGES[0]}): "
          f"{burned_low_ha:.1f} ha")
    print("=" * 58)

    # --- spremi GeoTIFF-ove (za QGIS) --------------------------------------
    dnbr_out = np.where(valid, dnbr, np.nan).astype("float32")
    sh.save_geotiff(dnbr_out[:, :, np.newaxis], bbox,
                    cfg.RASTER_DIR / f"dnbr_{pre}_{post}.tif")
    sh.save_geotiff(cls_masked[:, :, np.newaxis], bbox,
                    cfg.RASTER_DIR / f"burnclass_{pre}_{post}.tif")

    # --- karta težine opožarenosti -----------------------------------------
    cmap = ListedColormap(CLASS_COLORS)
    norm = BoundaryNorm([0, 1, 2, 3, 4], cmap.N)
    show = np.ma.masked_where(~valid, cls_masked)
    extent = (bbox.min_x, bbox.max_x, bbox.min_y, bbox.max_y)

    fig, ax = plt.subplots(figsize=(9, 9.4), dpi=130)
    ax.imshow(show, extent=extent, origin="upper", cmap=cmap, norm=norm)
    gdf.boundary.plot(ax=ax, edgecolor="black", linewidth=1.4)
    ax.set_xlim(bbox.min_x, bbox.max_x); ax.set_ylim(bbox.min_y, bbox.max_y)
    ax.set_axis_off()
    ax.set_title(f"Deliblato — Gubitak pokrova i opožarena površina\n(dNBR, {pre} → {post})",
                 fontsize=14, fontweight="bold", loc="left")
    legend = [Patch(facecolor=CLASS_COLORS[i], edgecolor="k", label=CLASS_LABELS[i])
              for i in range(len(CLASS_LABELS))]
    ax.legend(handles=legend, loc="lower left", fontsize=9, framealpha=0.9)
    ax.text(0.99, 0.01,
            f"Jasno opožareno: {burned_ha:.0f} ha ({burned_ha/100:.1f} km²)",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=11,
            fontweight="bold",
            bbox=dict(facecolor="white", alpha=0.85, pad=3))
    png = cfg.OUT_DIR / f"opozarena_povrsina_{pre}_{post}.png"
    fig.savefig(png, dpi=130, bbox_inches="tight")
    plt.close(fig)

    # --- tekstualni sažetak -------------------------------------------------
    txt = cfg.OUT_DIR / f"opozarena_povrsina_{pre}_{post}.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"Deliblato — procjena opožarene površine (dNBR)\n")
        f.write(f"PRE={pre}  POST={post}\n")
        f.write(f"Pokrivenost AOI: PRE {cov_pre*100:.0f}%, POST {cov_post*100:.0f}%\n")
        f.write(f"Ukupno područje: {total_aoi_ha:.1f} ha\n\n")
        f.write("\n".join(l.strip() for l in lines))
        f.write(f"\n\nJASNO OPOŽARENO (dNBR>={BURN_THRESHOLD}): {burned_ha:.1f} ha "
                f"({burned_ha/100:.2f} km2)\n")
        f.write(f"Uključujući niski intenzitet (dNBR>={CLASS_EDGES[0]}): "
                f"{burned_low_ha:.1f} ha\n")

    print(f"\n✓ Karta:    {png}")
    print(f"✓ Sažetak:  {txt}")
    print(f"✓ GeoTIFF:  dnbr_{pre}_{post}.tif, burnclass_{pre}_{post}.tif (u rasters/)")


if __name__ == "__main__":
    main()
