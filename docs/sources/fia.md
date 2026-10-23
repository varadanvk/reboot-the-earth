# USFS FIA (Forest Inventory and Analysis) — California data shapes

Pulled 2026-10-23 from FIA DataMart (files last modified 2026-10-22). Raw stats: `data/shapes/fia/stats.json`.

## URLs and sizes

| File | URL | Size | Fetched |
|---|---|---|---|
| CA_PLOT | https://apps.fs.usda.gov/fia/datamart/CSV/CA_PLOT.csv | 11.3 MB, 50,861 rows, 63 cols | full -> `data/shapes/fia/CA_PLOT.csv` |
| CA_TREE | https://apps.fs.usda.gov/fia/datamart/CSV/CA_TREE.csv | 304 MB, 198 cols | head 1,999 rows (`CA_TREE_head2000.csv`, all INVYR 1994 periodic) + last 3 MB via HTTP Range (`CA_TREE_tail3000.csv`, all INVYR 2024) |
| CA_COND | https://apps.fs.usda.gov/fia/datamart/CSV/CA_COND.csv | 18.8 MB, 61,264 rows, 153 cols | full download for stats (scratch only); `CA_COND_head50.csv` kept |
| REF_SPECIES | https://apps.fs.usda.gov/fia/datamart/CSV/REF_SPECIES.csv | 0.6 MB, 2,697 rows | full -> `data/shapes/fia/REF_SPECIES.csv` |
| CA_PLOTGEOM | https://apps.fs.usda.gov/fia/datamart/CSV/CA_PLOTGEOM.csv | 6.6 MB | not fetched (ecoregion/geo attributes per plot) |
| All REF_* tables | https://apps.fs.usda.gov/fia/datamart/CSV/FIADB_REFERENCE.zip | 5.9 MB | not fetched (REF_FOREST_TYPE, REF_DAMAGE_AGENT, etc.) |

Note: on this machine the local DNS resolver returned SERVFAIL for `apps.fs.usda.gov`; it resolves to 165.221.120.50 via 8.8.8.8 (`curl --resolve apps.fs.usda.gov:443:165.221.120.50 ...`). The server supports Range requests (206).

## Plot design (FIA national "annual" design, DESIGNCD 501 in CA)

- Each plot = cluster of **4 subplots**, radius **24.0 ft** (~1/24 acre = 168 m² each, ~1/6 acre total). Subplot 1 at center; 2/3/4 at 120 ft, azimuths 360/120/240.
- **Microplot**: 6.8 ft radius (~1/300 acre), 12 ft east (90°) of each subplot center; saplings 1.0–4.9 in DBH.
- **Subplot**: trees >= 5.0 in DBH.
- **Macroplot**: 58.9 ft radius (~1/4 acre) — optional, used by PNW region (incl. CA). Trees >= `MACRO_BREAKPOINT_DIA` (24 in in CA).
- Verified from TREE tail: `TPA_UNADJ` takes exactly 3 values that map to plot type by DIA:
  - 74.965282 -> DIA 1.0–4.8 (microplot; = 1/(4 x 1/300 ac))
  - 6.018046 -> DIA 5.0–23.9 (subplot; = 1/(4 x 1/24 ac))
  - 0.999188 -> DIA 24.0–62.7 (macroplot; = 1/(4 x ~1/4 ac))
- 1994 periodic plots (DESIGNCD 555/999, KINDCD 0) use a different design: SUBP 1–5 and other TPA values (e.g., 23.6576). Exclude them from simulator templates.

## Public coordinate fuzzing / swapping

- Per FIA (Food Security Act 1985 privacy rules): public LAT/LON are **perturbed ("fuzzed")** — most within 0.5 mi, up to 1 mi — and for up to ~20% of **private** plots, coordinates are **swapped** with another similar private plot in the same county. Plot attributes are real; the location is not. True coords are only available via the FIA Spatial Data Services agreement. (Documented FIA policy; not verifiable from the data itself.)
- Observed: LAT/LON written with 6 decimals (89%) — **the precision is fake**, effective accuracy is ~1 mile. Every plot keeps the **same LAT/LON across all visits** (22,589/22,589 plot IDs), so revisits stack exactly.
- ELEV is in feet and 96% of values are multiples of 100 (rounded).
- Implication for a heat map: grid cells smaller than ~2–5 km will show artificial patterns; aggregate to hex/grid >= ~10 km or county.

## Counts and distributions (CA_PLOT)

- 50,861 plot-visit rows; **22,589 distinct plot IDs** (STATECD/UNITCD/COUNTYCD/PLOT); 22,361 distinct lat/lon pairs.
- Visits per plot: 1 visit 4,914 (all 1994 periodic) / 2 visits 7,078 / 3 visits 10,597. **17,675 plots are remeasured** (all annual-era plots).
- INVYR: 1994 = 4,914 (periodic); 2001–2020 ~1,760–1,780/yr (one panel/yr of a 10-panel cycle); **2021 = 3,550, 2022 = 4, 2023 = 3,521, 2024 = 3,522**. Cycle 7 (2021+) measures two panels per year (REMPER 5 and 10 in 2021) — interpretation unverified. INVYR 2021 rows have MEASYEAR 2021–2024 (INVYR != MEASYEAR, ~17% differ).
- MEASYEAR range 1991–2025 (54 rows in 2025, partial year).
- PLOT_STATUS_CD (all rows): 1 forest = 16,882 (33%), 2 nonforest = 31,624 (62%), 3 nonsampled = 2,355 (5%). Latest visit of annual-era plots: 5,413 forest / 11,302 nonforest / 960 nonsampled.
- **Density**: 17,675 annual plots over CA's 423,970 km² = **41.7 plots per 1,000 km²** (~1 plot / 24 km², matches the 1 per ~6,000 acre hex grid); forested-only = 12.8 per 1,000 km².
- LAT 32.55–42.01, LON -124.44 to -114.16. 228 rows (all DESIGNCD 999) have **blank LAT/LON** — drop them.

## Key fields

### PLOT (63 cols)
| Field | Type | Units | Example | Meaning |
|---|---|---|---|---|
| CN | string (bigint) | – | "1308375394290487" | Unique plot-visit key (up to 16 digits). Read as text. |
| PREV_PLT_CN | string | – | | CN of previous visit (remeasurement chain) |
| STATECD/UNITCD/COUNTYCD/PLOT | int | – | 6 / 1 / 15 / 1 | Composite permanent plot ID (stable across visits) |
| INVYR | int | year | 2024 | Inventory (panel) year — not always the measurement year |
| MEASYEAR/MEASMON/MEASDAY | int | date | 2023 / 7 / 14 | Actual field visit date |
| PLOT_STATUS_CD | int | code | 1 | 1 forest, 2 nonforest, 3 nonsampled |
| KINDCD | int | code | 2 | 0 periodic, 1 initial annual, 2 remeasurement |
| DESIGNCD | int | code | 501 | Plot design (501 = annual 4-subplot + macroplot, PNW) |
| LAT/LON | float | deg (NAD83) | 39.123456 | **Fuzzed/swapped** location |
| ELEV | int | ft | 4900 | Elevation, rounded to 100 ft |
| REMPER | float | years | 10.0 | Remeasurement period |
| CYCLE/SUBCYCLE | int | – | 7 / 3 | Inventory cycle / panel |
| MACRO_BREAKPOINT_DIA | int | in | 24 | DBH threshold for macroplot trees |

### TREE (198 cols; one row per tree per visit)
| Field | Type | Units | Example | Meaning |
|---|---|---|---|---|
| CN / PLT_CN / PREV_TRE_CN | string (bigint) | – | "1917397927290487" | Tree-visit key / FK to PLOT.CN / previous visit |
| SUBP | int | – | 1–4 | Subplot number (1–5 in 1994 periodic) |
| TREE | int | – | 118 | Tree number within subplot (stable across visits) |
| STATUSCD | int | code | 1 | 0 no status (not in sample/removed), 1 live, 2 dead, 3 removed (cut) |
| SPCD | int | code | 122 | FIA species code -> REF_SPECIES. **Written as "122.0"** in CSV |
| DIA | float | **inches** DBH (4.5 ft) | 13.0 | Diameter; 1.0 min |
| HT | float | **feet** | 39 | Total height (estimated if broken) |
| ACTUALHT | float | feet | 34 | Actual height (differs if top broken). Populated for all annual trees, only dead trees in 1994 |
| CR | int | % | 60 | Compacted crown ratio (live trees only) |
| CCLCD | int | code | 3 | Crown class: 1 open, 2 dominant, 3 codominant, 4 intermediate, 5 overtopped |
| AGENTCD | int | code | 30 | Cause of death (dead trees only in annual): 10 insect, 20 disease, 30 **fire**, 40 animal, 50 weather, 60 vegetation, 70 unknown, 80 silvicultural/harvest |
| DAMAGE_AGENT_CD1-3 | int | 5-digit code | 22500, 90001 | Damage agents (newer national codes, REF_DAMAGE_AGENT). Blank for 1994 rows; 0 = none. e.g. 1xxxx insects, 2xxxx disease, 3xxxx fire, 9xxxx physical/other |
| TPA_UNADJ | float | trees/acre | 6.018046 | Expansion factor; 3 values by plot type (see design) |
| STANDING_DEAD_CD | int | code | 1 | Dead tree still standing |
| DRYBIO_AG / CARBON_AG | float | lb | | Aboveground biomass / carbon per tree |

Sample stats (2024 tail, 3,000 rows / 116 plots): STATUSCD 1 = 56%, 2 = 32%, 0 = 11% (high dead share — fire/drought mortality); DIA median 13.0 in (max 62.7); HT median 39 ft (max 192); CR median 60%. **Trees per plot median 21 (range 1–95)**; 1994 head: median 28 (3–77). Top SPCD in tail: 15 white fir, 133 singleleaf pinyon, 81 incense-cedar, 116 Jeffrey pine, 108 lodgepole, 805 canyon live oak, 20 red fir, 122 ponderosa pine.

### COND (153 cols; one row per condition (stand/land class) per plot visit)
| Field | Type | Units | Example | Meaning |
|---|---|---|---|---|
| PLT_CN / CONDID | string / int | – | | FK to PLOT.CN / condition number within plot |
| COND_STATUS_CD | int | code | 1 | 1 forest, 2 nonforest, 3 noncensus water, 4 census water, 5 nonsampled |
| CONDPROP_UNADJ | float | fraction | 0.75 | Share of plot area in this condition (sum to 1 per plot) |
| FORTYPCD | int | code | 371 | Forest type (REF_FOREST_TYPE); blank if nonforest. Top CA: 371 California mixed conifer (4,305) |
| OWNGRPCD | int | code | 10 | 10 USFS, 20 other federal, 30 state/local, 40 private |
| RESERVCD | int | 0/1 | 0 | Reserved (wilderness etc.) |
| STDSZCD | int | code | 1 | Stand size: 1 large, 2 medium, 3 small, 5 nonstocked |
| DSTRBCD1-3 / DSTRBYR1-3 | int / year | code / yr | 31 / 2020 | Disturbance: 10 insect, 20 disease, 30 fire (31 ground, 32 crown), 40 animal, 46 domestic grazing, 50 weather, 60 vegetation, 70 unknown, 80 human, 90s geologic. Year 9999 = continuous/unknown |
| TRTCD1-3 / TRTYR1-3 | int / year | code / yr | 10 / 2015 | **Treatment: 0 none, 10 cutting (harvest/thinning), 20 site prep, 30 artificial regen (planting), 40 natural regen, 50 other silvicultural** |
| BALIVE | float | ft²/acre | | Live basal area |
| LIVE_CANOPY_CVR_PCT | float | % | | Live canopy cover |

Distributions (61,264 rows): conds per plot 1 = 42,588, 2 = 6,526, 3+ = 1,747. CONDPROP_UNADJ < 1 on 18,676 rows. DSTRBCD1 nonzero ~4,400 (fire 31/32 = 1,864, grazing 46 = 1,163, disease 22 = 970). TRTCD1: 10 cutting = 1,243, 50 = 91, 30 = 41, 20 = 32. DSTRBYR1 peaks in 2008 / 2018 / **2020 (374)** / 2021 — the big fire years.

## REF_SPECIES (SPCD -> USDA PLANTS symbol)

`REF_SPECIES.csv` (also in FIADB_REFERENCE.zip). Columns include `SPCD, COMMON_NAME, GENUS, SPECIES, SCIENTIFIC_NAME, SPECIES_SYMBOL, SFTWD_HRDWD, WOODLAND, ...`. `SPECIES_SYMBOL` is the USDA PLANTS symbol, which OFO uses. Examples: 15 white fir ABCO; 81 incense-cedar CADE27; 108 lodgepole pine PICO; 122 ponderosa pine PIPO; 202 Douglas-fir PSME; 818 California black oak QUKE. Join on `int(float(SPCD))` because TREE writes SPCD as "122.0".

## Gotchas

1. **CN keys are 16-digit integers stored as text — read them as strings** (`dtype=str`). Float parsing loses precision (> 2^53) and breaks PLT_CN joins.
2. **Imperial units**: DIA inches, HT/ACTUALHT/ELEV feet, TPA per acre, biomass in lb, BALIVE ft²/acre.
3. **Codes written as floats** in some columns (SPCD "122.0"). Cast with `int(float(x))`.
4. **Fuzzed + swapped coordinates** (~1 mi); 6 decimals of fake precision; coords identical on every revisit.
5. **Panels**: one plot measured per INVYR panel; a single INVYR is ~1/10 (cycle <=6) or ~1/5 (cycle 7) of the state. INVYR != MEASYEAR for some plots. "Current" state = latest visit per plot (or EVALID-based selection via POP_* tables, not fetched).
6. **Most plots are nonforest** (62% of rows); they still have PLOT rows (and COND rows) but no TREE rows. Mixed plots split into conditions via CONDPROP_UNADJ.
7. **1994 periodic data** (4,914 plots, KINDCD 0) uses a different design (5 subplots, other TPA values, no damage codes); the TREE file starts with it, so `head` samples are misleading.
8. Many region-specific columns (`*_PNWRS`, `*_SRS`, `*_NERS`, ...) are blank for CA except PNWRS.
9. STATUSCD 0 trees have blank DIA/HT/TPA — filter them out before computing stats.
