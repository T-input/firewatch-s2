"""
config.py — Konfig. za Deliblato.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# PUTANJE
# --------------------------------------------------------------------------
# Root projekta, roditelj direktorij od scripts/ (kod mene je to G:\Deliblato)
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = DATA_DIR / "output"
FRAMES_DIR = OUT_DIR / "frames"
RASTER_DIR = OUT_DIR / "rasters"

for _d in (OUT_DIR, FRAMES_DIR, RASTER_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Granica podrucja (.gpkg koji je preuzet lokalno sa OSM)
AOI_GPKG = DATA_DIR / "Deliblato_granice.gpkg"

# Granica za procjenu opozarene povrsine (05) — bez Dunava, da ne radi sum.
AOI_GPKG_BURN = DATA_DIR / "Deliblato_granice_bez_dunava.gpkg"

# --------------------------------------------------------------------------
# VREMENSKI RASPON
# --------------------------------------------------------------------------
START_DATE = date(2026, 7, 1)        # 1. srpnja 2026.
END_DATE = date.today()              # danas

# Usporedba: rujan 2025. vs rujan 2026.
COMPARE_YEARS = (2025, 2026)
COMPARE_MONTH = 9

# --------------------------------------------------------------------------
# SATELIT / OBRADA
# --------------------------------------------------------------------------
RESOLUTION = 20      # metri po pikselu (server daje SWIR pojaseve B11/B12 u 20 m)
BUFFER_M = 1000      # buffer oko granice (m) da granica nije tik uz rub slike
MAX_CLOUD = 100      # % oblaka; 100 = uzmi ssve snimke (bez filtriranja)
CRS_EPSG = 32634     # UTM zona 34N — isti CRS kao gpkg granica, ne znam koji terestricki sustav Srbija koristi, ovo mi je sigurnija opcija

# Min. pokrivenost podrucja ne-nodata pikselima da kadar ude
# u GIF. S2 nekad pokrije samo dio AOI-ja (spoj orbita). To ne zelim i takvi
# poluprazni kadrovi se preskacu.
MIN_COVERAGE = 0.95

# --------------------------------------------------------------------------
# COPERNICUS CREDENTIALS
# --------------------------------------------------------------------------
# Ucitava se iz datoteke .env (u root projekta), inace iz varijabli okoline.
# NE DIJELITI .env SA DRUGIM LJUDIMA!!
def _load_dotenv() -> None:
    env = PROJECT_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

SH_CLIENT_ID = os.environ.get("SH_CLIENT_ID", "")
SH_CLIENT_SECRET = os.environ.get("SH_CLIENT_SECRET", "")

# CDSE Sentinel Hub API endpoint
SH_BASE_URL = "https://sh.dataspace.copernicus.eu"
SH_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
