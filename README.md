# Forest data coverage — California

A prototype heat map of how much forest data exists for each patch of California, across sources,
built on the unified record schema in [`docs/schema.md`](docs/schema.md).

<img width="408" height="255" alt="image" src="https://github.com/user-attachments/assets/03ab5c0b-f440-4f7f-baca-830ad686ac10" />
<img width="408" height="255" alt="image" src="https://github.com/user-attachments/assets/866072b4-d39e-42a0-8beb-5729c93ee072" />


| Source | Kind | Status | Records |
|---|---|---|---|
| OFO drone missions + ground plots (Zenodo 23402904) | drone_imagery, field_plot | **real** | 974 |
| USFS FIA plots (`CA_PLOT.csv`, public fuzzed coords) | field_plot | **real** | 6,092 forested plots |
| USGS 3DEP lidar work units (WESM) | airborne_lidar | **real** | 203 |
| CAL FIRE FRAP fire perimeters | fire_perimeter | simulated | 2,906 |
| CA Interagency Treatment Dashboard (ITS) | fuel_treatment | simulated | 9,404 activities |
| NASA GEDI L2A passes | spaceborne_lidar | simulated | 542 passes |

Simulated sources use the real field names and distributions documented in `docs/sources/*.md`,
and are placed using real forested FIA plot locations. Every record carries `simulated: true/false`;
the UI badges them and can hide them.

## Run

```bash
# 1. data (gitignored): OFO from Zenodo into data/ofo/, source shapes into data/shapes/ (see docs/sources/)
uv run python -m catalog.ingest_ofo    # OFO -> data/catalog/records/ofo.parquet + relations.parquet
uv run python -m catalog.simulate      # FIA + 3DEP (real), FRAP/ITS/GEDI (simulated)
uv run python -m catalog.build         # records -> H3 coverage + GeoJSON into web/data/  (~40 s)
cd web && python3 -m http.server 8765  # open http://localhost:8765
```

## How it fits together

```
source adapter ──> record (GeoParquet, one schema) ──> build.py ──> coverage_r{5..8} (H3 per cell × kind)
 ingest_ofo.py                                                  ├─> records_{kind}.geojson (footprints)
 simulate.py                                                    └─> nearby.json (overlaps, covered_by, ≤2 km)
```
<img width="520" height="321" alt="image" src="https://github.com/user-attachments/assets/977b2365-454a-4085-8d36-54cc14a547fc" />


- **Coverage** is computed at H3 res 8 (~0.74 km²) and rolled up to res 5–7. Small footprints add
  `area / cell area`; fuzzed locations (FIA, ±1 mile) are spread over every cell they could be in;
  sparse samplers (GEDI) add `measured area / swath area`. Res 7–8 are tiled by res‑3 parent and
  loaded for the viewport only.
- **Coverage score** (UI default) per cell = Σ over kinds of weight × recency (8‑yr half‑life) ×
  quality × log(record count). Ground truth (plots, drone) weighs 1; wall‑to‑wall layers less.
  Other colourings: record count, kinds of data, most recent year, area covered.
- **Filters**: data kinds, "I need data that can measure …" (capabilities), year, commercial‑use
  licences, simulated on/off. Click a hexagon for a per‑kind breakdown; zoom ≥ 9.5 for footprints;
  click a footprint for licence, credit, quality, preview thumbnail and nearby/overlapping records.
