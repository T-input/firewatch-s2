# Analiza požara sa S2 - primjer Deliblato, Srbija, ljeto 2026.

Skripte pisane u Pythonu. QGIS za vizalni pregled. Prije bilo čega treba `.env` s Copernicus
podacima.

Popis:

- `01_connect.py` - testiraj spajanje na Copernicus, ispiši dostupne snimke
- `02_fetch_timeseries.py` - skini snimke (u mom primjeru 1.7.2026 do danas), .TIF
- `03_build_gif.py` - GIF s granicom preko snimaka
- `04_compare_sept.py` - rujan 2025 vs rujan 2026
- `05_burned_area.py` - opožarena površina (dNBR), u ha/km2
- `06_canopy_loss.py` - karta izgubljene visine krošnje (m)

Aux. skripte: `config.py`, `evalscripts.py`,
`sh_utils.py`, `viz.py`.

Glavni EO inputi su tri Copernicus proizvoda: RedGreenBlue, SWIR falsecolor
(čak se vidi se živa vatra) i NBR indeks.

## Priprema

```
pip install -r requirements.txt
```

Copernicus OAuth: na https://shapps.dataspace.copernicus.eu/dashboard/ pod
User settings -> OAuth clients -> Create. Kopiraj `.env.example` u
root, u njega upiši Client ID i Secret, izbriši `.example` iz imena i imaš `.env`. `.env` ne ide u git.

## Struktura radnog direktorija
- root (meni je to G:\Deliblato)
   - data
      - eth_tiles (ručno download)
      - output
         - frames
         - rasters
      - AOI.gpkg
      - CORINE.gpkg
   - scripts
   - .env

## Pokretanje

Iz mape `scripts`:

```
python 01_connect_test.py
python 02_fetch_timeseries.py
python 03_build_gif.py
python 04_compare_sept.py
python 05_burned_area.py
python 06_canopy_loss.py
```

## Izvori

Key, C. H., & Benson, N. C. (2006). Landscape assessment (LA): Sampling and analysis methods. In D. C. Lutes, R. E. Keane, J. F. Caratti, C. H. Key, N. C. Benson, S.
Sutherland, & L. J. Gangi (Eds.), FIREMON: Fire effects monitoring and inventory system (General Technical Report RMRS-GTR-164-CD, pp. LA-1–LA-55). U.S. Department 
of Agriculture, Forest Service, Rocky Mountain Research Station.

Lang, N., Jetz, W., Schindler, K., & Wegner, J. D. (2023). A high-resolution canopy height model of the Earth. Nature Ecology & Evolution, 7(11), 1778–1789. 
https://doi.org/10.1038/s41559-023-02206-6

Ćuk, M., Perić, R., Čarni, A., Ilić, M., Vlku, A., Igić, D., Vukov, D. (2025). Flora and vegetation of Deliblato Sands (Serbia): A review of floristic and vegetation
research through the centuries.
Matica Srpska Journal for Natural Sciences, (149), 27–[zadnja stranica]. 
https://doiserbia.nb.rs/ft.aspx?id=0352-49062549027C

CORINE Land Cover 2018 (vector/raster 100 m), Europe, 6-yearly
European Union's Copernicus Land Monitoring Service information,
Link: https://land.copernicus.eu/en/products/corine-land-cover/clc2018 (Accessed on 08.09.2026.)
DOI: https://doi.org/10.2909/71c95a07-e296-44fc-b22b-415f42acfdf0

Contains modified Copernicus Sentinel data for years 2025 and 2026.

## Rezultati (u `data\output\`)

- GIF-ovi: `deliblato_truecolor.gif`, `_falsecolor.gif`, `_nbr.gif`
- `usporedba_rujan_2025_2026.png`
- `opozarena_povrsina_*.png/.txt`, `izgubljena_visina_krosnje_*.png/.txt`
- `rasters\` - GeoTIFF za QGIS (EPSG:32634)
- `frames\` - pojedini kadrovi

## Postavke

Glavno je u `config.py`: datumi (`START_DATE`/`END_DATE`), rezolucija, buffer
oko granice, oblaci (`MAX_CLOUD`), prag pokrivenosti (`MIN_COVERAGE`).
Band-kombinacije za prikaze su u `evalscripts.py`.