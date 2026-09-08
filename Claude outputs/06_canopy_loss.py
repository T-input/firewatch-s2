"""
06_canopy_loss.py — KORAK 6: Karta izgubljene visine krosnje (metri).

Ideja: ETH Global Canopy Height 2020 (10 m) daje PRETPOZARNU visinu krosnje u
metrima. Ondje gdje je nasa dNBR maska pokazala pozar, ta visina je (uz
pretpostavku pozara koji uklanja krosnju) priblizno IZGUBLJENA visina.

    izgubljena_visina[m] = ETH_visina_2020[m]   tamo gdje je dNBR >= prag pozara

Izvor pretpozarne visine:
    ETH Global Canopy Height 2020, 10 m (Lang et al. 2023, CC BY 4.0)
    https://langnico.github.io/globalcanopyheight/
    GeoTIFF plocice (uint8 = metri, nodata=255, EPSG:4326).
    ETH server ne podrzava range-zahtjeve, pa skripta jednom preuzme potrebne
    plocice u data/eth_tiles/ (moze biti nekoliko stotina MB), a zatim lokalno
    izreze prozor nad AOI. Sljedeci put se koristi kesirana verzija.

Pozar (dNBR) racuna se iz NBR snimaka (korak 2 / 05):  PRE -> POST rujan.

Definicija "sume" dolazi iz CORINE Land Cover 2018 (klase 311/312/313) preko
EEA discomap ArcGIS REST servisa (bez logina). Ako CORINE nije dostupan,
koristi se rezervni prag visine (FOREST_MIN_H).

Izlazi (data/output/):
    rasters/eth_canopy_height_aoi.tif   — ETH visina, poravnata na nasu mrezu
    rasters/lost_canopy_height_<PRE>_<POST>.tif — izgubljena visina (m)
    izgubljena_visina_krosnje_<PRE>_<POST>.png  — karta + statistika
    izgubljena_visina_krosnje_<PRE>_<POST>.txt  — sazetak

Pokretanje:
    python 06_canopy_loss.py                       # zadani datumi
    python 06_canopy_loss.py 2025-09-22 2026-09-02  # drugi datumi
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
import urllib.parse
import urllib.request

import numpy as np
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds, reproject, Resampling

import config as cfg
import sh_utils as sh

# --- Datumi (isti kao u 05) ------------------------------------------------
PRE_DATE = "2025-09-22"
POST_DATE = "2026-09-02"

# --- Pragovi ---------------------------------------------------------------
BURN_THRESHOLD = 0.27    # dNBR prag "jasno opozareno" (kao u 05)
FOREST_MIN_H = 5.0       # m — rezervni prag SUME ako CORINE nije dostupan

# --- CORINE Land Cover 2018 (definicija sume) ------------------------------
# Sumske klase: 311 listopadna, 312 crnogoricna, 313 mjesovita suma.
# INCLUDE_SHRUB dodaje 324 (prijelazna suma/sikara).
CORINE_QUERY = ("https://image.discomap.eea.europa.eu/arcgis/rest/services/"
                "Corine/CLC2018_LAEA/MapServer/0/query")
FOREST_CODES = ["311", "312", "313"]
INCLUDE_SHRUB = False

# --- ETH izvor -------------------------------------------------------------
ETH_BASE = ("https://share.phys.ethz.ch/~pf/nlangdata/"
            "ETH_GlobalCanopyHeight_10m_2020_version1/3deg_cogs/")
ETH_PREFIX = "ETH_GlobalCanopyHeight_10m_2020_"
ETH_NODATA = 255
# ETH server ne podrzava HTTP range-zahtjeve (vsicurl daje 500), pa plocice
# preuzimamo cijele u lokalni cache i onda lokalno rezemo prozor.
ETH_CACHE = cfg.DATA_DIR / "eth_tiles"


# ==========================================================================
#  ETH dohvat (mreza; ne treba credentials, ETH je otvoren)
# ==========================================================================
def eth_tiles_for_bounds(w, s, e, n):
    """Nazivi 3° ETH plocica (po JZ kutu) koje pokrivaju WGS84 raspon."""
    tiles = []
    lat = math.floor(s / 3) * 3
    while lat < n:
        lon = math.floor(w / 3) * 3
        while lon < e:
            la = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            lo = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
            tiles.append(f"{la}{lo}")
            lon += 3
        lat += 3
    return tiles


def _valid_tif(path):
    """Je li datoteka ispravan (dovoljno velik) GeoTIFF?"""
    try:
        with rasterio.open(path) as ds:
            return ds.count >= 1 and ds.width > 100
    except Exception:
        return False


def _download(url, dest, attempts=3):
    """Puni GET s ponovnim pokusajima + provjera da je stvarno GeoTIFF."""
    ETH_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for k in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (canopy-dl)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                ctype = r.headers.get("Content-Type", "")
                if "html" in ctype.lower():
                    raise RuntimeError(f"server vratio HTML ({ctype})")
                total = int(r.headers.get("Content-Length", 0))
                with open(tmp, "wb") as f:
                    done, chunk = 0, 1 << 20
                    while True:
                        buf = r.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        done += len(buf)
                        msg = (f"{done/1e6:6.0f}/{total/1e6:.0f} MB" if total
                               else f"{done/1e6:6.0f} MB")
                        print(f"\r    {dest.name}: {msg}", end="", flush=True)
                print()
            if _valid_tif(tmp):
                tmp.replace(dest)
                return True
            raise RuntimeError("preuzeto nije ispravan GeoTIFF")
        except Exception as ex:
            if tmp.exists():
                tmp.unlink()
            print(f"    pokusaj {k}/{attempts} nije uspio: {ex}")
            if k < attempts:
                time.sleep(3 * k)
    return False


def _local_tile(tile):
    """Vrati lokalnu putanju plocice; preuzmi je ako je nema (ili je neispravna)."""
    fn = f"{ETH_PREFIX}{tile}_Map.tif"
    dest = ETH_CACHE / fn
    if dest.exists():
        if _valid_tif(dest):
            return dest
        print(f"  brisem neispravan kes {tile}")
        dest.unlink()
    print(f"  preuzimam ETH plocicu {tile} (jednokratno)...")
    return dest if _download(f"{ETH_BASE}{fn}", dest) else None


def fetch_eth_chm(bbox, size):
    """
    Vrati ETH visinu krosnje (float32, metri, NaN=nodata) poravnatu na nasu
    rastersku mrezu (UTM 34N, ista kao dNBR). Cita samo prozor nad AOI.
    Rezultat se kesira u rasters/eth_canopy_height_aoi.tif.
    """
    cache = cfg.RASTER_DIR / "eth_canopy_height_aoi.tif"
    if cache.exists():
        print(f"ETH visina: ucitavam iz {cache.name}")
        arr = sh.read_geotiff(cache)[:, :, 0].astype("float32")
        arr[arr == ETH_NODATA] = np.nan
        return arr

    W, H = size
    w, s, e, n = transform_bounds(f"EPSG:{cfg.CRS_EPSG}", "EPSG:4326",
                                  bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y)
    pad = 0.02
    w, s, e, n = w - pad, s - pad, e + pad, n + pad
    tiles = eth_tiles_for_bounds(w, s, e, n)
    print(f"ETH plocice nad AOI: {tiles}")

    srcs, missing = [], []
    for t in tiles:
        p = _local_tile(t)
        if p is not None:
            srcs.append(rasterio.open(p))
        else:
            missing.append(t)
        time.sleep(1)   # blaga pauza (izbjegava rate-limit servera)

    if missing:
        print(f"  ! nedostaju plocice: {missing}")
    if not srcs:
        man = "\n".join(f"      {ETH_BASE}{ETH_PREFIX}{t}_Map.tif" for t in tiles)
        raise RuntimeError(
            "ETH server trenutno ne servira plocice (500 / greske).\n\n"
            "  RUCNO RJESENJE: preuzmi ove datoteke u web-pregledniku (radi i\n"
            "  kad skripta ne uspije) i spremi ih u mapu:\n"
            f"      {ETH_CACHE}\n"
            "  a zatim ponovno pokreni skriptu. URL-ovi:\n" + man +
            "\n\n  (ili preko karte s linkovima: "
            "https://langnico.github.io/globalcanopyheight/assets/tile_index.html)")

    print("  rezem prozor nad AOI...")
    mosaic, mtransform = merge(srcs, bounds=(w, s, e, n), nodata=ETH_NODATA)
    for ds in srcs:
        ds.close()

    src = mosaic[0].astype("float32")
    src[src == ETH_NODATA] = np.nan

    dst_transform = from_bounds(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y, W, H)
    dst = np.full((H, W), np.nan, dtype="float32")
    reproject(
        source=src, destination=dst,
        src_transform=mtransform, src_crs="EPSG:4326",
        dst_transform=dst_transform, dst_crs=f"EPSG:{cfg.CRS_EPSG}",
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    # kesiraj (nan -> 255 natrag u uint8-kompatibilan zapis kao float)
    sh.save_geotiff(np.nan_to_num(dst, nan=ETH_NODATA)[:, :, np.newaxis], bbox, cache)
    print(f"  spremljeno: {cache.name}")
    return dst


def get_dnbr(bbox, size, pre, post):
    """dNBR + maska valjanih piksela iz NBR rastera (korak 2/05)."""
    tif_pre = cfg.RASTER_DIR / f"{pre}_nbr.tif"
    tif_post = cfg.RASTER_DIR / f"{post}_nbr.tif"
    for t in (tif_pre, tif_post):
        if not t.exists():
            raise RuntimeError(
                f"Nedostaje {t.name}. Prvo pokreni 05_burned_area.py "
                f"(ili 02_fetch_timeseries.py) za te datume.")
    a = sh.read_geotiff(tif_pre)
    b = sh.read_geotiff(tif_post)
    dnbr = a[:, :, 0] - b[:, :, 0]
    valid = (a[:, :, 1] >= 0.5) & (b[:, :, 1] >= 0.5)
    return dnbr, valid


# ==========================================================================
#  CORINE sumska maska (definicija "sume")
# ==========================================================================
def fetch_corine_forest(bbox, size):
    """
    Vrati boolean masku (H,W): True gdje je CORINE 2018 sumska klasa.
    Upit na EEA discomap ArcGIS REST (bez logina), poligoni -> rasterizacija
    na nasu mrezu. Rezultat se kesira u rasters/corine_forest_aoi.tif.
    """
    cache = cfg.RASTER_DIR / "corine_forest_aoi.tif"
    if cache.exists():
        print(f"CORINE suma: ucitavam iz {cache.name}")
        return sh.read_geotiff(cache)[:, :, 0].astype(bool)

    codes = list(FOREST_CODES) + (["324"] if INCLUDE_SHRUB else [])
    where = "Code_18 IN (" + ",".join(f"'{c}'" for c in codes) + ")"
    feats, offset = [], 0
    for _page in range(50):     # gornja granica (sprjecava beskonacnu petlju)
        params = {
            "where": where,
            "geometry": f"{bbox.min_x},{bbox.min_y},{bbox.max_x},{bbox.max_y}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": str(cfg.CRS_EPSG), "outSR": str(cfg.CRS_EPSG),
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "Code_18", "returnGeometry": "true", "f": "geojson",
            "resultOffset": str(offset), "resultRecordCount": "1000",
        }
        url = CORINE_QUERY + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            fc = json.load(r)
        batch = fc.get("features", []) or []
        feats.extend(batch)
        print(f"  CORINE poligoni: +{len(batch)} (ukupno {len(feats)})")
        if len(batch) < 1000:
            break
        offset += 1000

    W, H = size
    dst_transform = from_bounds(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y, W, H)
    if not feats:
        print("  ! CORINE nije vratio sumske poligone za AOI.")
        return np.zeros((H, W), dtype=bool)

    fgdf = gpd.GeoDataFrame.from_features(feats, crs=f"EPSG:{cfg.CRS_EPSG}")
    mask = rasterize(((g, 1) for g in fgdf.geometry if g is not None),
                     out_shape=(H, W), transform=dst_transform, fill=0,
                     dtype="uint8").astype(bool)
    sh.save_geotiff(mask.astype("uint8")[:, :, np.newaxis], bbox, cache)
    print(f"  CORINE suma: {int(mask.sum())} px  ({mask.mean()*100:.1f}% mreze)")
    return mask


# ==========================================================================
#  Racun + prikaz (odvojeno, da se moze testirati bez mreze)
# ==========================================================================
def compute_and_render(chm, dnbr, valid, gdf, bbox, pre, post, forest_mask=None):
    aoi = sh.aoi_pixel_mask(gdf, bbox, chm.shape)
    burned = (dnbr >= BURN_THRESHOLD) & valid & aoi
    chm_ok = np.isfinite(chm)

    # izgubljena visina = pretpozarna visina tamo gdje je izgorjelo
    lost = np.where(burned & chm_ok, chm, np.nan).astype("float32")

    px_ha = (cfg.RESOLUTION ** 2) / 10_000.0     # ha po pikselu
    px_m2 = float(cfg.RESOLUTION ** 2)

    # definicija SUME: CORINE (ako je dostupan), inace prag visine
    if forest_mask is not None:
        forest_here = forest_mask.astype(bool) & aoi
        forest_src = "CORINE 2018 (311/312/313)"
    else:
        forest_here = (chm >= FOREST_MIN_H) & aoi
        forest_src = f"visina >= {FOREST_MIN_H} m (ETH, rezerva)"

    burned_valid = burned & chm_ok
    forest_burned = burned_valid & forest_here

    n_burned = int(burned_valid.sum())
    n_forest = int(forest_burned.sum())
    mean_all = float(np.nanmean(chm[burned_valid])) if n_burned else 0.0
    mean_forest = float(np.nanmean(chm[forest_burned])) if n_forest else 0.0
    max_h = float(np.nanmax(chm[burned_valid])) if n_burned else 0.0
    # "integrirani gubitak" = suma(visina*povrsina) — proxy za volumen krosnje
    vol_m3 = float(np.nansum(chm[forest_burned]) * px_m2)

    lines = [
        f"Izgubljena visina krosnje — Deliblato ({pre} -> {post})",
        f"Izvor pretpozarne visine: ETH Global Canopy Height 2020 (10 m)",
        f"Definicija sume: {forest_src}",
        f"Prag pozara: dNBR >= {BURN_THRESHOLD}",
        "-" * 58,
        f"Opozarena povrsina (s ETH podatkom): {n_burned*px_ha:9.1f} ha",
        f"  od toga SUMA (CORINE):             {n_forest*px_ha:9.1f} ha",
        f"Prosj. visina krosnje (sve opozareno): {mean_all:5.1f} m",
        f"Prosj. visina krosnje (samo suma):     {mean_forest:5.1f} m",
        f"Najveca izgubljena visina:             {max_h:5.1f} m",
        f"Integrirani gubitak krosnje (visina x povrsina): "
        f"{vol_m3/1e6:.2f} mil. m3",
    ]
    print("\n" + "=" * 58)
    for ln in lines:
        print("  " + ln)
    print("=" * 58)

    # --- karta -------------------------------------------------------------
    extent = (bbox.min_x, bbox.max_x, bbox.min_y, bbox.max_y)
    vmax = max(10.0, float(np.nanpercentile(lost, 98))) if n_burned else 10.0
    show = np.ma.masked_invalid(lost)

    fig, ax = plt.subplots(figsize=(9, 9.6), dpi=130)
    # kontekst: CORINE sumski pokrov (svijetlo zeleno)
    fbg = np.ma.masked_where(~forest_here, np.ones(chm.shape, dtype="float32"))
    ax.imshow(fbg, extent=extent, origin="upper", cmap="Greens",
              vmin=0, vmax=1.6, alpha=0.30)
    im = ax.imshow(show, extent=extent, origin="upper", cmap="YlOrRd",
                   vmin=0, vmax=vmax)
    gdf.boundary.plot(ax=ax, edgecolor="black", linewidth=1.4)
    ax.set_xlim(bbox.min_x, bbox.max_x); ax.set_ylim(bbox.min_y, bbox.max_y)
    ax.set_axis_off()
    ax.set_title("Deliblato — izgubljena visina krosnje\n"
                 f"(ETH visina x CORINE suma, dNBR, {pre} → {post})",
                 fontsize=14, fontweight="bold", loc="left")
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.01)
    cbar.set_label("izgubljena visina krosnje [m]", fontsize=10)
    ax.text(0.99, 0.01,
            f"Opozarena suma: {n_forest*px_ha:.0f} ha\n"
            f"Prosj. visina (suma): {mean_forest:.1f} m",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=10,
            fontweight="bold",
            bbox=dict(facecolor="white", alpha=0.85, pad=3))

    png = cfg.OUT_DIR / f"izgubljena_visina_krosnje_{pre}_{post}.png"
    fig.savefig(png, dpi=130, bbox_inches="tight")
    plt.close(fig)

    # --- GeoTIFF izgubljene visine (za QGIS) -------------------------------
    sh.save_geotiff(np.nan_to_num(lost, nan=-9999.0)[:, :, np.newaxis], bbox,
                    cfg.RASTER_DIR / f"lost_canopy_height_{pre}_{post}.tif")

    # --- tekst -------------------------------------------------------------
    txt = cfg.OUT_DIR / f"izgubljena_visina_krosnje_{pre}_{post}.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n✓ Karta:    {png}")
    print(f"✓ Sazetak:  {txt}")
    print(f"✓ GeoTIFF:  lost_canopy_height_{pre}_{post}.tif (u rasters/)")


def main():
    pre = sys.argv[1] if len(sys.argv) > 1 else PRE_DATE
    post = sys.argv[2] if len(sys.argv) > 2 else POST_DATE
    print(f"Izgubljena visina krosnje:  PRE={pre} -> POST={post}\n")

    _grid_gdf, bbox, size = sh.load_aoi()          # mreza (kao ostatak pipelinea)
    gdf = sh.load_boundary(cfg.AOI_GPKG_BURN)      # granica bez Dunava

    chm = fetch_eth_chm(bbox, size)                # ETH visina (m), na nasoj mrezi
    dnbr, valid = get_dnbr(bbox, size, pre, post)  # pozar iz NBR

    try:
        forest_mask = fetch_corine_forest(bbox, size)   # CORINE definicija sume
    except Exception as ex:
        print(f"! CORINE nedostupan ({ex}) — koristim rezervni prag "
              f"visine {FOREST_MIN_H} m.")
        forest_mask = None

    compute_and_render(chm, dnbr, valid, gdf, bbox, pre, post, forest_mask)


if __name__ == "__main__":
    main()
