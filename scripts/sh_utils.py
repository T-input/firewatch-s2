"""
sh_utils.py — Pomocne funkcije za CDSE.

  - get_config()        : postavi SHConfig s CDSE endpointima i credentialsima
  - get_data_collection : Sentinel-2 L2A na CDSE servisu
  - load_aoi()          : ucitaj granicu, izracunaj bbox i velicinu
  - search_days()       : preko STAC kataloga nadi dane sa snimkama
  - fetch_array()       : preuzmi jednu clipanu sliku preko Process API
  - save_geotiff()      : spremi georeferencirani GeoTIFF (za Q)
"""
from __future__ import annotations

import datetime as dt
from typing import List, Tuple

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from sentinelhub import (
    SHConfig, BBox, CRS, DataCollection, SentinelHubCatalog,
    SentinelHubRequest, MimeType, MosaickingOrder, bbox_to_dimensions,
)

import evalscripts as ev

import config as cfg


# --------------------------------------------------------------------------
def get_config() -> SHConfig:
    """Vrati SHConfig postavljen za CDSE. Baci gresku ako nema credentialsa."""
    if not cfg.SH_CLIENT_ID or not cfg.SH_CLIENT_SECRET:
        raise RuntimeError(
            "Nedostaju Copernicus credentials!\n"
            "Kreiraj datoteku .env u root-u projekta (G:\\Deliblato\\.env) "
            "prema .env.example i upisi SH_CLIENT_ID i SH_CLIENT_SECRET."
        )
    c = SHConfig()
    c.sh_client_id = cfg.SH_CLIENT_ID
    c.sh_client_secret = cfg.SH_CLIENT_SECRET
    c.sh_base_url = cfg.SH_BASE_URL
    c.sh_token_url = cfg.SH_TOKEN_URL
    return c


def get_data_collection() -> DataCollection:
    """Sentinel-2 L2A (atmosferski korigirano) na CDSE servisu."""
    return DataCollection.SENTINEL2_L2A.define_from(
        "s2l2a_cdse", service_url=cfg.SH_BASE_URL
    )


# --------------------------------------------------------------------------
def load_boundary(gpkg=None) -> gpd.GeoDataFrame:
    """Ucitaj granicu iz gpkg-a i reprojwciraj u radni CRS (UTM 34N)."""
    return gpd.read_file(gpkg or cfg.AOI_GPKG).to_crs(cfg.CRS_EPSG)


def load_aoi() -> Tuple[gpd.GeoDataFrame, BBox, Tuple[int, int]]:
    """
    Ucitaj glavnu granicu -> (gdf u UTM34N, BBox s bufferom, (sirina, visina) px).
    BBox definira mrezu na kojoj se preuzimaju sve snimke — isti za
    cijeli pipeline (dijeljenje cachea medu skriptama).
    """
    gdf = load_boundary(cfg.AOI_GPKG)
    minx, miny, maxx, maxy = gdf.total_bounds
    b = cfg.BUFFER_M
    bbox = BBox((minx - b, miny - b, maxx + b, maxy + b),
                crs=CRS(str(cfg.CRS_EPSG)))
    size = bbox_to_dimensions(bbox, resolution=cfg.RESOLUTION)
    return gdf, bbox, size


# --------------------------------------------------------------------------
def search_days(config: SHConfig, bbox: BBox, start: dt.date, end: dt.date,
                max_cloud: int = 100) -> List[Tuple[str, List[float]]]:
    """
    Preko STAC kataloga nadi sve dane sa Sentinel-2 snimkama nad AOI.
    Vraca listu (datum 'YYYY-MM-DD', lista oblacnosti po plocici).
    """
    catalog = SentinelHubCatalog(config=config)
    dc = get_data_collection()

    kwargs = dict(
        collection=dc,
        bbox=bbox,
        time=(start.isoformat(), end.isoformat()),
        fields={"include": ["id", "properties.datetime",
                            "properties.eo:cloud_cover"], "exclude": []},
    )
    if max_cloud < 100:
        kwargs["filter"] = f"eo:cloud_cover < {max_cloud}"

    per_day: dict[str, List[float]] = {}
    for scene in catalog.search(**kwargs):
        day = scene["properties"]["datetime"][:10]
        cc = scene["properties"].get("eo:cloud_cover")
        per_day.setdefault(day, []).append(cc)

    return [(d, per_day[d]) for d in sorted(per_day)]


# --------------------------------------------------------------------------
def fetch_array(config: SHConfig, bbox: BBox, size: Tuple[int, int],
                day: str, evalscript: str,
                mime: MimeType = MimeType.TIFF) -> np.ndarray:
    """
    Preuzmi jednu clipanu sliku za zadani dan (mozaik svih plocica tog dana).
    Vraca numpy polje (HxW ili HxWxN).
    """
    dc = get_data_collection()
    request = SentinelHubRequest(
        evalscript=evalscript,
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=dc,
                time_interval=(f"{day}T00:00:00Z", f"{day}T23:59:59Z"),
                mosaicking_order=MosaickingOrder.LEAST_CC,  # najmanje oblaka gore
            )
        ],
        responses=[SentinelHubRequest.output_response("default", mime)],
        bbox=bbox,
        size=size,
        config=config,
    )
    return request.get_data()[0]


# --------------------------------------------------------------------------
def save_geotiff(array: np.ndarray, bbox: BBox, path) -> None:
    """Spremi numpy polje kao georef. GeoTIFF (za ucitavanje u Q)."""
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    height, width, bands = array.shape
    transform = from_bounds(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y,
                            width, height)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=height, width=width, count=bands,
        dtype=array.dtype, crs=f"EPSG:{cfg.CRS_EPSG}", transform=transform,
        compress="deflate",
    ) as dst:
        for b in range(bands):
            dst.write(array[:, :, b], b + 1)


def read_geotiff(path) -> np.ndarray:
    """Ucitaj GeoTIFF natrag u numpy polje (HxWxN)."""
    with rasterio.open(path) as src:
        arr = src.read()                      # (bands, H, W)
    return np.transpose(arr, (1, 2, 0))       # -> (H, W, bands)


# --------------------------------------------------------------------------
def aoi_pixel_mask(gdf, bbox, shape) -> np.ndarray:
    """Boolean maska (H, W): True za piksele unutar granice podrucja."""
    height, width = shape[0], shape[1]
    transform = from_bounds(bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y,
                            width, height)
    mask = rasterize(
        ((geom, 1) for geom in gdf.geometry),
        out_shape=(height, width), transform=transform, fill=0, dtype="uint8",
    )
    return mask.astype(bool)


def data_coverage(valid_mask: np.ndarray, aoi_mask: np.ndarray) -> float:
    """Udio valjanih (ne-nodata) piksela UNUTAR granice AOI-ja (0..1)."""
    total = int(aoi_mask.sum())
    if total == 0:
        return 0.0
    return float(np.logical_and(valid_mask, aoi_mask).sum()) / total


def fetch_coverage(config: SHConfig, bbox: BBox, gdf, day: str,
                   resolution: int = 60) -> float:
    """
    Provjera: koliki udio AOI-ja snimka tog dana stvarno pokriva (0..1).
    Preuzima samo dataMask na gruboj rezoluciji — za odabir dana.
    """
    size = bbox_to_dimensions(bbox, resolution=resolution)
    arr = fetch_array(config, bbox, size, day, ev.MASK, mime=MimeType.TIFF)
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    aoi = aoi_pixel_mask(gdf, bbox, (size[1], size[0]))
    return data_coverage(arr > 0, aoi)
