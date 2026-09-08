"""
06_canopy_loss.py — KORAK 6: Karta izgubljene visine krošnje (metri).

Ideja: ETH Global Canopy Height 2020 (10 m) daje PRETPOŽARNU visinu krošnje u
metrima. Ondje gdje je naša dNBR maska pokazala požar, ta visina je (uz
pretpostavku požara koji uklanja krošnju) približno IZGUBLJENA visina.

    izgubljena_visina[m] = ETH_visina_2020[m]   tamo gdje je dNBR >= prag požara

Izvor pretpožarne visine:
    ETH Global Canopy Height 2020, 10 m (Lang et al. 2023, CC BY 4.0)
    https://langnico.github.io/globalcanopyheight/
    GeoTIFF pločice (uint8 = metri, nodata=255, EPSG:4326).
    ETH server ne podržava range-zahtjeve, pa skripta jednom preuzme potrebne
    pločice u data/eth_tiles/ (može biti nekoliko stotina MB), a zatim lokalno
    izreže prozor nad AOI. Sljedeći put se koristi keširana verzija.

Požar (dNBR) računa se iz NBR snimaka (korak 2 / 05):  PRE -> POST rujan.

Definicija "šume" dolazi iz CORINE Land Cover 2018 (klase 311/312/313) preko
EEA discomap ArcGIS REST servisa (bez logina). Ako CORINE nije dostupan,
koristi se rezervni prag visine (FOREST_MIN_H).

Izlazi (data/output/):
    rasters/eth_canopy_height_aoi.tif   — ETH visina, poravnata na našu mrežu
    rasters/lost_canopy_height_<PRE>_<POST>.tif — izgubljena visina (m)
    izgubljena_visina_krosnje_<PRE>_<POST>.png  — karta + statistika
    izgubljena_visina_krosnje_<PRE>_<POST>.txt  — sažetak

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
from shapely.geometry import box
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
BURN_THRESHOLD = 0.27    # dNBR prag "jasno opožareno" (kao u 05)
FOREST_MIN_H = 5.0       # m — rezervni prag ŠUME ako CORINE nije dostupan

# --- Gruba drvna zaliha (m3/ha) --------------------------------------------
# Dominantne sastojine Deliblatske pješčare: bagrem (Robinia pseudoacacia),
# crni bor (Pinus nigra) i obični bor (Pinus sylvestris) — vidi:
# "Flora and vegetation of Deliblato Sands (Serbia): A review of floristic and
# vegetation research through the centuries".
# Na siromašnim pjeskovitim staništima drvna zaliha je umjerena; vrijednosti su
# OKVIRNE (uredi po potrebi ili prema podacima gospodarske osnove).
WOOD_M3_HA = 150             # središnja procjena (m3/ha)
WOOD_M3_HA_RANGE = (100, 200)  # nisko - visoko (m3/ha)

# --- CORINE Land Cover 2018 (definicija šume) ------------------------------
# Šumske klase: 311 listopadna, 312 crnogorična, 313 mješovita šuma.
# INCLUDE_SHRUB dodaje 324 (prijelazna šuma/šikara).
FOREST_CODES = ["311", "312", "313"]
INCLUDE_SHRUB = False
# Lokalni CORINE gpkg (prioritetno; radi offline). Ako ne postoji, traži se
# bilo koji CLC/CORINE .gpkg u data/, a kao zadnja rezerva ide mrežni upit.
CORINE_GPKG = cfg.DATA_DIR / "U2018_CLC2018_V2020_20u1.gpkg"
CORINE_QUERY = ("https://image.discomap.eea.europa.eu/arcgis/rest/services/"
                "Corine/CLC2018_LAEA/MapServer/0/query")

# --- ETH izvor -------------------------------------------------------------
ETH_BASE = ("https://share.phys.ethz.ch/~pf/nlangdata/"
            "ETH_GlobalCanopyHeight_10m_2020_version1/3deg_cogs/")
ETH_PREFIX = "ETH_GlobalCanopyHeight_10m_2020_"
ETH_NODATA = 255
# ETH server ne podržava HTTP range-zahtjeve (vsicurl daje 500), pa pločice
# preuzimamo cijele u lokalni cache i onda lokalno režemo prozor.
ETH_CACHE = cfg.DATA_DIR / "eth_tiles"


# ==========================================================================
#  ETH dohvat (mreža; ne treba credentials, ETH je otvoren)
# ==========================================================================
def eth_tiles_for_bounds(w, s, e, n):
    """Nazivi 3° ETH pločica (po JZ kutu) koje pokrivaju WGS84 raspon."""
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
    """Puni GET s ponovnim pokušajima + provjera da je stvarno GeoTIFF."""
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
            print(f"    pokušaj {k}/{attempts} nije uspio: {ex}")
            if k < attempts:
                time.sleep(3 * k)
    return False


def _local_tile(tile):
    """Vrati lokalnu putanju pločice; preuzmi je ako je nema (ili je neispravna)."""
    fn = f"{ETH_PREFIX}{tile}_Map.tif"
    dest = ETH_CACHE / fn
    if dest.exists():
        if _valid_tif(dest):
            return dest
        print(f"  brišem neispravan keš {tile}")
        dest.unlink()
    print(f"  preuzimam ETH pločicu {tile} (jednokratno)...")
    return dest if _download(f"{ETH_BASE}{fn}", dest) else None


def fetch_eth_chm(bbox, size):
    """
    Vrati ETH visinu krošnje (float32, metri, NaN=nodata) poravnatu na našu
    rastersku mrežu (UTM 34N, ista kao dNBR). Čita samo prozor nad AOI.
    Rezultat se kešira u rasters/eth_canopy_height_aoi.tif.
    """
    cache = cfg.RASTER_DIR / "eth_canopy_height_aoi.tif"
    if cache.exists():
        print(f"ETH visina: učitavam iz {cache.name}")
        arr = sh.read_geotiff(cache)[:, :, 0].astype("float32")
        arr[arr == ETH_NODATA] = np.nan
        return arr

    W, H = size
    w, s, e, n = transform_bounds(f"EPSG:{cfg.CRS_EPSG}", "EPSG:4326",
                                  bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y)
    pad = 0.02
    w, s, e, n = w - pad, s - pad, e + pad, n + pad
    tiles = eth_tiles_for_bounds(w, s, e, n)
    print(f"ETH pločice nad AOI: {tiles}")

    srcs, missing = [], []
    for t in tiles:
        p = _local_tile(t)
        if p is not None:
            srcs.append(rasterio.open(p))
        else:
            missing.append(t)
        time.sleep(1)   # blaga pauza (izbjegava rate-limit servera)

    if missing:
        print(f"  ! nedostaju pločice: {missing}")
    if not srcs:
        man = "\n".join(f"      {ETH_BASE}{ETH_PREFIX}{t}_Map.tif" for t in tiles)
        raise RuntimeError(
            "ETH server trenutno ne servira pločice (500 / greške).\n\n"
            "  RUČNO RJEŠENJE: preuzmi ove datoteke u web-pregledniku (radi i\n"
            "  kad skripta ne uspije) i spremi ih u mapu:\n"
            f"      {ETH_CACHE}\n"
            "  a zatim ponovno pokreni skriptu. URL-ovi:\n" + man +
            "\n\n  (ili preko karte s linkovima: "
            "https://langnico.github.io/globalcanopyheight/assets/tile_index.html)")

    print("  režem prozor nad AOI...")
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
    # keširaj (nan -> 255 natrag u uint8-kompatibilan zapis kao float)
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
#  CORINE šumska maska (definicija "šume")
# ==========================================================================
def _find_corine_gpkg():
    """Nađi lokalni CORINE gpkg (zadani naziv ili bilo koji CLC/CORINE .gpkg)."""
    if CORINE_GPKG.exists():
        return CORINE_GPKG
    for pat in ("*CLC*.gpkg", "*clc*.gpkg", "*[Cc]orine*.gpkg", "U2018*.gpkg"):
        hits = sorted(cfg.DATA_DIR.glob(pat))
        if hits:
            return hits[0]
    return None


def _detect_code_field(cols):
    """Nađi ime polja s CORINE kodom (Code_18 / CODE_18 / ...)."""
    low = {c.lower(): c for c in cols}
    for key in ("code_18", "code18", "clc_code", "code"):
        if key in low:
            return low[key]
    for c in cols:
        if "code" in c.lower():
            return c
    return None


def _forest_gdf_from_gpkg(path, bbox):
    """Učitaj SAMO šumske poligone unutar AOI iz lokalnog CORINE gpkg-a."""
    # bbox kao GeoSeries u našem CRS-u -> geopandas ga sam reprojicira na CRS
    # datoteke i čita samo poligone u tom prozoru (brzo i za 8+ GB gpkg).
    aoi_box = gpd.GeoSeries(
        [box(bbox.min_x - 1000, bbox.min_y - 1000,
             bbox.max_x + 1000, bbox.max_y + 1000)],
        crs=f"EPSG:{cfg.CRS_EPSG}")
    print(f"CORINE: čitam iz {path.name} (prostorni filtar na AOI)...")
    g = gpd.read_file(path, bbox=aoi_box)
    code_col = _detect_code_field(g.columns)
    if code_col is None:
        raise RuntimeError(f"ne mogu naći polje s CORINE kodom u {path.name}")
    codes = set(FOREST_CODES) | ({"324"} if INCLUDE_SHRUB else set())
    g = g[g[code_col].astype(str).str.strip().isin(codes)]
    print(f"  šumskih poligona: {len(g)} (polje '{code_col}', klase {sorted(codes)})")
    return g.to_crs(cfg.CRS_EPSG)


def _forest_gdf_from_discomap(bbox):
    """Rezerva: povuci šumske poligone s EEA discomap ArcGIS REST-a (bez logina)."""
    codes = list(FOREST_CODES) + (["324"] if INCLUDE_SHRUB else [])
    where = "Code_18 IN (" + ",".join(f"'{c}'" for c in codes) + ")"
    feats, offset = [], 0
    for _page in range(50):     # gornja granica (sprječava beskonačnu petlju)
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
        print(f"  CORINE (discomap) poligoni: +{len(batch)} (ukupno {len(feats)})")
        if len(batch) < 1000:
            break
        offset += 1000
    if not feats:
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{cfg.CRS_EPSG}")
    return gpd.GeoDataFrame.from_features(feats, crs=f"EPSG:{cfg.CRS_EPSG}")


def fetch_corine_forest(bbox, size):
    """
    Vrati boolean masku (H,W): True gdje je CORINE 2018 šumska klasa.
    Prioritet: lokalni gpkg -> mrežni discomap. Kešira se u
    rasters/corine_forest_aoi.tif.
    """
    cache = cfg.RASTER_DIR / "corine_forest_aoi.tif"
    if cache.exists():
        print(f"CORINE šuma: učitavam iz {cache.name}")
        return sh.read_geotiff(cache)[:, :, 0].astype(bool)

    local = _find_corine_gpkg()
    fgdf = (_forest_gdf_from_gpkg(local, bbox) if local
            else _forest_gdf_from_discomap(bbox))

    W, H = size
    dst_transform = from_bounds(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y, W, H)
    if fgdf is None or len(fgdf) == 0:
        print("  ! CORINE nije vratio šumske poligone za AOI.")
        return np.zeros((H, W), dtype=bool)

    mask = rasterize(((g, 1) for g in fgdf.geometry if g is not None),
                     out_shape=(H, W), transform=dst_transform, fill=0,
                     dtype="uint8").astype(bool)
    sh.save_geotiff(mask.astype("uint8")[:, :, np.newaxis], bbox, cache)
    print(f"  CORINE šuma: {int(mask.sum())} px  ({mask.mean()*100:.1f}% mreže)")
    return mask


# ==========================================================================
#  Račun + prikaz (odvojeno, da se može testirati bez mreže)
# ==========================================================================
def compute_and_render(chm, dnbr, valid, gdf, bbox, pre, post, forest_mask=None):
    aoi = sh.aoi_pixel_mask(gdf, bbox, chm.shape)
    burned = (dnbr >= BURN_THRESHOLD) & valid & aoi
    chm_ok = np.isfinite(chm)

    px_ha = (cfg.RESOLUTION ** 2) / 10_000.0     # ha po pikselu

    # definicija ŠUME: CORINE (ako je dostupan), inače prag visine
    if forest_mask is not None:
        forest_here = forest_mask.astype(bool) & aoi
        forest_src = "CORINE 2018 (311/312/313)"
    else:
        forest_here = (chm >= FOREST_MIN_H) & aoi
        forest_src = f"visina >= {FOREST_MIN_H} m (ETH, rezerva)"

    burned_valid = burned & chm_ok
    forest_burned = burned_valid & forest_here

    # izgubljenu visinu prikazujemo SAMO za CORINE šumu (stepa izuzeta)
    lost = np.where(forest_burned, chm, np.nan).astype("float32")

    n_burned = int(burned_valid.sum())
    n_forest = int(forest_burned.sum())
    mean_all = float(np.nanmean(chm[burned_valid])) if n_burned else 0.0
    mean_forest = float(np.nanmean(chm[forest_burned])) if n_forest else 0.0
    max_h = float(np.nanmax(chm[forest_burned])) if n_forest else 0.0

    # gruba procjena drvne mase izgorjele šume (bruto)
    forest_ha = n_forest * px_ha
    wood_c = forest_ha * WOOD_M3_HA
    wood_lo = forest_ha * WOOD_M3_HA_RANGE[0]
    wood_hi = forest_ha * WOOD_M3_HA_RANGE[1]

    lines = [
        f"Izgubljena visina krošnje — Deliblato ({pre} -> {post})",
        f"Izvor pretpožarne visine: ETH Global Canopy Height 2020 (10 m)",
        f"Definicija šume: {forest_src}",
        f"Prag požara: dNBR >= {BURN_THRESHOLD}",
        "-" * 58,
        f"Opožarena površina (s ETH podatkom): {n_burned*px_ha:9.1f} ha",
        f"  od toga ŠUMA (CORINE):             {forest_ha:9.1f} ha",
        f"Prosj. visina krošnje (sve opožareno): {mean_all:5.1f} m",
        f"Prosj. visina krošnje (samo šuma):     {mean_forest:5.1f} m",
        f"Najveća visina (šuma):                 {max_h:5.1f} m",
        "-" * 58,
        f"Gruba procjena drvne mase izgorjele šume ({WOOD_M3_HA} m3/ha):",
        f"   ~{wood_c/1e3:,.0f} tis. m3   (raspon {wood_lo/1e3:.0f}-{wood_hi/1e3:.0f} "
        f"tis. m3 za {WOOD_M3_HA_RANGE[0]}-{WOOD_M3_HA_RANGE[1]} m3/ha)",
        "   sastojine: bagrem, crni i obični bor (pjeskovita staništa)",
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
    # kontekst: CORINE šumski pokrov (svijetlozeleno)
    fbg = np.ma.masked_where(~forest_here, np.ones(chm.shape, dtype="float32"))
    ax.imshow(fbg, extent=extent, origin="upper", cmap="Greens",
              vmin=0, vmax=1.6, alpha=0.30)
    im = ax.imshow(show, extent=extent, origin="upper", cmap="YlOrRd",
                   vmin=0, vmax=vmax)
    gdf.boundary.plot(ax=ax, edgecolor="black", linewidth=1.4)
    ax.set_xlim(bbox.min_x, bbox.max_x); ax.set_ylim(bbox.min_y, bbox.max_y)
    ax.set_axis_off()
    ax.set_title("Deliblato — izgubljena visina krošnje\n"
                 f"(ETH visina × CORINE šuma, dNBR, {pre} → {post})",
                 fontsize=14, fontweight="bold", loc="left")
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.01)
    cbar.set_label("izgubljena visina krošnje [m]", fontsize=10)
    ax.text(0.99, 0.01,
            f"Opožarena šuma (CORINE): {forest_ha:.0f} ha\n"
            f"Prosj. visina krošnje: {mean_forest:.1f} m\n"
            f"Drvna masa (bruto): ~{wood_c/1e3:.0f} tis. m3",
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
    print(f"✓ Sažetak:  {txt}")
    print(f"✓ GeoTIFF:  lost_canopy_height_{pre}_{post}.tif (u rasters/)")


def main():
    pre = sys.argv[1] if len(sys.argv) > 1 else PRE_DATE
    post = sys.argv[2] if len(sys.argv) > 2 else POST_DATE
    print(f"Izgubljena visina krošnje:  PRE={pre} -> POST={post}\n")

    _grid_gdf, bbox, size = sh.load_aoi()          # mreža (kao ostatak pipelinea)
    gdf = sh.load_boundary(cfg.AOI_GPKG_BURN)      # granica bez Dunava

    chm = fetch_eth_chm(bbox, size)                # ETH visina (m), na našoj mreži
    dnbr, valid = get_dnbr(bbox, size, pre, post)  # požar iz NBR

    try:
        forest_mask = fetch_corine_forest(bbox, size)   # CORINE definicija šume
    except Exception as ex:
        print(f"! CORINE nedostupan ({ex}) — koristim rezervni prag "
              f"visine {FOREST_MIN_H} m.")
        forest_mask = None

    compute_and_render(chm, dnbr, valid, gdf, bbox, pre, post, forest_mask)


if __name__ == "__main__":
    main()
