# Deliblato — satelitska analiza požara (Sentinel-2 / Copernicus)

Praćenje požara u zaštićenom području **Deliblatska peščara** (Srbija) pomoću
Sentinel-2 snimaka s Copernicus Data Space Ecosystem-a.

## Što skripte rade

| Skripta | Namjena |
|---|---|
| `01_connect_test.py` | Spajanje na Copernicus (CDSE) + popis dostupnih snimaka |
| `02_fetch_timeseries.py` | Preuzimanje snimaka (1.7.2026 – danas) kao GeoTIFF |
| `03_build_gif.py` | Animirani GIF s preklopljenom granicom područja |
| `04_compare_sept.py` | Usporedba rujan 2025. vs rujan 2026. |
| `05_burned_area.py` | Procjena ukupne opožarene površine (dNBR, ha/km²) |
| `06_canopy_loss.py` | Karta izgubljene visine krošnje u metrima (ETH 2020 × dNBR) |

Pomoćni moduli: `config.py` (postavke), `evalscripts.py` (Sentinel Hub skripte),
`sh_utils.py` (veza + preuzimanje), `viz.py` (crtanje + GIF).

Tri prikaza (proizvoda) za svaku snimku:
- **truecolor** — prirodne boje (dim, izgled terena)
- **falsecolor** — SWIR kompozit B12/B8A/B04 (aktivna vatra i opožarene površine)
- **nbr** — Normalized Burn Ratio, kvantitativni indeks opožarenosti

## Priprema (jednom)

1. Instaliraj pakete:
   ```
   pip install -r requirements.txt
   ```

2. OAuth podaci za Copernicus. Na
   <https://shapps.dataspace.copernicus.eu/dashboard/> → *User settings* →
   *OAuth clients* → **Create**. Dobiješ **Client ID** i **Secret**.

3. Kopiraj `.env.example` u `G:\Deliblato\.env` i upiši svoje podatke:
   ```
   SH_CLIENT_ID=...
   SH_CLIENT_SECRET=...
   ```
   `.env` je kao lozinka — ne dijeli je i ne stavljaj u git.

## Pokretanje (redom)

Iz mape `scripts/` u VS Code terminalu:

```
python 01_connect_test.py        # provjera veze
python 02_fetch_timeseries.py    # preuzimanje (potraje)
python 03_build_gif.py           # GIF-ovi
python 04_compare_sept.py        # usporedba rujna
python 05_burned_area.py         # procjena opožarene površine (dNBR)
python 06_canopy_loss.py         # karta izgubljene visine krošnje (m)
```

`06_canopy_loss.py` koristi **ETH Global Canopy Height 2020 (10 m)** kao
pretpožarnu visinu krošnje u metrima (Lang i sur. 2023, CC BY 4.0). Pri prvom pokretanju
preuzme potrebne ETH pločice u `data\eth_tiles\` (jednokratno, može biti
nekoliko stotina MB — ETH server ne podržava čitanje po dijelovima), a zatim
lokalno izreže prozor nad AOI. Ne treba Copernicus credentials, ali treba
internet i preuzete NBR rastere za oba datuma. Izgubljena visina = ETH visina
ondje gdje je dNBR ≥ 0,27.

**Definicija "šume" dolazi iz CORINE Land Cover 2018** (klase 311/312/313).
Skripta prvo traži lokalni CORINE gpkg u `data\` (npr.
`U2018_CLC2018_V2020_20u1.gpkg`) i iz njega čita samo šumske poligone unutar AOI
(prostorni filtar — brzo i za višegigabajtnu datoteku); ako ga nema, pada na
mrežni EEA discomap upit, a ako ni to ne radi — na rezervni prag visine
`FOREST_MIN_H` (5 m). Za prijelaznu šumu/šikaru (klasa 324) postavi
`INCLUDE_SHRUB = True`.

Karta prikazuje izgubljenu visinu **samo za CORINE šumu** (stepa/travnjak je
izuzeta). Uz to se računa **gruba procjena drvne mase** izgorjele šume
(`WOOD_M3_HA`, zadano 150 m³/ha s rasponom 100–200) — okvirno za dominantne
sastojine bagrema, crnog i običnog bora na pješčanim staništima; vrijednost
prilagodi u skripti ako imaš podatke gospodarske osnove.

`05_burned_area.py` uspoređuje NBR snimke iz istog doba godine — prošlogodišnji
i ovogodišnji rujan (zadano `2025-09-22` → `2026-09-02`; druge datume možeš
predati kao argumente: `python 05_burned_area.py 2025-09-22 2026-09-02`) — i daje
površinu po razredima težine te ukupnu opožarenu površinu u ha/km². Koristi
granicu bez Dunava (`Deliblato_granice_bez_dunava.gpkg`).

## Rezultati

Sve u `G:\Deliblato\data\output\`:
- `deliblato_truecolor.gif`, `deliblato_falsecolor.gif`, `deliblato_nbr.gif`
- `usporedba_rujan_2025_2026.png`
- `rasters/` — GeoTIFF-ovi (možeš otvoriti u **QGIS**, georeferencirani, EPSG:32634)
- `frames/` — pojedinačni kadrovi

## Podešavanje

U `config.py` možeš mijenjati: vremenski raspon (`START_DATE`/`END_DATE`),
rezoluciju (`RESOLUTION`), buffer oko granice, filtriranje oblaka (`MAX_CLOUD`).
Band-kombinacije prikaza su u `evalscripts.py`.
