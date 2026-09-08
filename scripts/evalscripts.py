"""
evalscripts.py

Govori Sentinel Hub API-ju koje pojaseve uzeti i kako ih
pretvoriti u izlaznu sliku. Radim sa tri proizvoda:

  1) TRUE_COLOR    — prirodne boje (B04/B03/B02), dim , RGB
  2) FALSE_COLOR   — SWIR kompozit (B12/B8A/B04): opozarene povrsine crveno-
                     smede, zdrava vegetacija - zeleno, vartra - jarko
                     narancasto/crveno (SWIR B12 "toplina").
  3) NBR           — Normalized Burn Ratio = (B08 - B12)/(B08 + B12). Vise u 05.
                     Kvantitativni indeks: visoke vrijednosti = zdrava
                     vegetacija, niske/negativne = opozareno/golo tlo.

 dataMask - alpha band da podrucja bez podataka budu prozirna.
"""

# --- 1) TRUE COLOR — 4 bands RGB, uint8 -----------------
TRUE_COLOR = """
//VERSION=3
function setup() {
  return {
    input: ["B02", "B03", "B04", "dataMask"],
    output: { bands: 4, sampleType: "UINT8" }
  };
}
function evaluatePixel(s) {
  let g = 2.5;                       // pojacanje svjetline
  return [
    255 * Math.min(1, g * s.B04),    // R
    255 * Math.min(1, g * s.B03),    // G
    255 * Math.min(1, g * s.B02),    // B
    255 * s.dataMask                 // alpha
  ];
}
"""

# --- 2) FALSE COLOR SWIR — uint8 -------
# R = B12 (SWIR-2), G = B8A (NIR), B = B04 (Red)
FALSE_COLOR = """
//VERSION=3
function setup() {
  return {
    input: ["B04", "B8A", "B12", "dataMask"],
    output: { bands: 4, sampleType: "UINT8" }
  };
}
function evaluatePixel(s) {
  let g = 2.5;
  return [
    255 * Math.min(1, g * s.B12),    // R = SWIR-2  -> vatra/opozareno
    255 * Math.min(1, g * s.B8A),    // G = NIR     -> vegetacija
    255 * Math.min(1, g * s.B04),    // B = Red
    255 * s.dataMask
  ];
}
"""

# --- 3) NBR — 2 bands (nbr + mask), float32 ------
NBR = """
//VERSION=3
function setup() {
  return {
    input: ["B08", "B12", "dataMask"],
    output: { bands: 2, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(s) {
  let denom = s.B08 + s.B12;
  let nbr = denom === 0 ? 0 : (s.B08 - s.B12) / denom;
  return [nbr, s.dataMask];
}
"""

# --- dataMask — 1 bands, uint8 --
MASK = """
//VERSION=3
function setup() {
  return { input: ["dataMask"], output: { bands: 1, sampleType: "UINT8" } };
}
function evaluatePixel(s) {
  return [s.dataMask];
}
"""


# Sifrarnik proizvoda (evalscript, broj_pojaseva, tip)
PRODUCTS = {
    "truecolor":  {"evalscript": TRUE_COLOR,  "bands": 4, "dtype": "uint8"},
    "falsecolor": {"evalscript": FALSE_COLOR, "bands": 4, "dtype": "uint8"},
    "nbr":        {"evalscript": NBR,         "bands": 2, "dtype": "float32"},
}
