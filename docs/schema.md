# Forest data coverage — unified schema (draft v0)

Goal: open a map of California and see, for any patch of land, **how much data exists, what kind, how recent, how good, and whether you may use it** — starting from OFO and extensible to any other geolocated source.

## 1. What OFO actually gives us (profiled 2026-10-23)

| File | Rows | Geometry | Key facts |
|---|---|---|---|
| `ofo_drone-missions.gpkg` | 687 | MultiPolygon footprint | 625 in CA. Median 21 ha (0.1–1,273). 2019–2026. 166 smart-oblique, 521 nadir. All RGB. 77 cols, **all text** (multi-values joined by `, `). License: `CC-BY 4.0` / `CC BY 4.0` / `CC BY SA 4.0` (inconsistent spelling). 38 have curator anomaly severity 1–3. |
| `ofo_ground-reference_plots.gpkg` | 287 | Polygon / MultiPolygon | Median 0.29 ha. Surveyed 2007–2025 (date is `YYYY`, `YYYYMM` or `YYYYMMDD` as a float). 5 license types incl. `CC BY NC SA 4.0` (51). Tally rules vary: `min_dbh` 0.4–25.4 cm, `min_ht` 1.37–20 m. 14 hyperplots (nested pairs). |
| `ofo_ground-reference_trees.gpkg` | 64,295 | Point | 75 species, 86% live. DBH 96% populated, height 51%, crown position 33%, fire-effects ~2%. |

Spatial relationships (computed): **267/287 plots are covered by ≥1 mission** (median 2, max 9); 312/687 missions touch a plot. Plots may be ~10 m off from imagery.

### Primitives we can generalize from

1. **Footprint record** — a thing with an area, a time, a license, and a provider (mission, plot). This is the unit of "coverage".
2. **Observation** — a point measurement inside a record (tree). Gives *depth* of coverage, not extent.
3. **Asset** — a file belonging to a record (ortho, CHM, DTM, point cloud, crowns). Gives *what you can actually download*.
4. **Relation** — record↔record (plot covered by mission, nadir/oblique pair, hyperplot siblings).
5. **Capability** — what a record lets you measure (species, DBH, height, canopy height, 3D structure…). This is what a researcher filters on.

## 2. Design principles

- **STAC-shaped.** A record ≈ STAC Item, collection ≈ STAC Collection, assets ≈ STAC assets. OFO already publishes STAC, and most external sources we'd add (USGS 3DEP LiDAR, Sentinel/Landsat via Planetary Computer, NEON) do too — ingestion becomes a mapper, not a rewrite.
- **Normalize what the heat map aggregates on; keep the rest raw.** Typed columns for geometry/time/kind/license/quality; source-native attributes go in `attrs` JSON so nothing is lost.
- **Coverage is a derived, gridded table**, recomputed from records. H3 hexes, stored at a fine resolution and rolled up for zoomed-out views.
- **Location uncertainty is first-class.** OFO plots ±10 m; FIA public plot coords are fuzzed ~0.5–1 mile. Coverage must spread a fuzzed record across the cells it *might* be in rather than pretending it's precise.

## 3. Tables

```sql
-- Who provides data (OFO, NEON, USFS FIA, USGS 3DEP, CAL FIRE FRAP, …)
CREATE TABLE source (
  source_id       TEXT PRIMARY KEY,           -- 'ofo', 'fia', 'usgs_3dep'
  name            TEXT NOT NULL,
  homepage_url    TEXT,
  citation        TEXT,                       -- how to credit the *platform*
  access_notes    TEXT
);

-- A homogeneous product line within a source
CREATE TABLE collection (
  collection_id   TEXT PRIMARY KEY,           -- 'ofo.drone_mission', 'ofo.ground_plot'
  source_id       TEXT NOT NULL REFERENCES source,
  data_kind       TEXT NOT NULL,              -- enum, see §4
  title           TEXT NOT NULL,
  description     TEXT,
  default_license TEXT,
  native_crs      TEXT,
  metadata_url    TEXT                        -- e.g. the *_metadata.md
);

-- THE core primitive: one footprint-bearing data item
CREATE TABLE record (
  record_id            TEXT PRIMARY KEY,      -- '{collection_id}:{native_id}'  e.g. 'ofo.drone_mission:000123'
  collection_id        TEXT NOT NULL REFERENCES collection,
  native_id            TEXT NOT NULL,         -- mission_id / plot_id as the source spells it
  title                TEXT,

  -- where
  footprint            GEOMETRY NOT NULL,     -- EPSG:4326 (Multi)Polygon; points buffered by uncertainty
  centroid             GEOMETRY NOT NULL,     -- POINT, for clustering/labels
  area_ha              DOUBLE,
  position_uncert_m    DOUBLE,                -- 10 for OFO plots, ~1600 for FIA public coords, ~1 for RTK drone
  site_id              TEXT,                  -- groups co-located records (nadir+oblique pair, hyperplot)

  -- when
  time_start           DATE,
  time_end             DATE,
  time_precision       TEXT,                  -- 'day' | 'month' | 'year'
  time_approx          BOOLEAN,

  -- what
  data_kind            TEXT NOT NULL,         -- denormalized from collection for fast filtering
  capabilities         TEXT[],                -- see §4, e.g. {species,dbh,height,live_dead}
  spatial_res_m        DOUBLE,                -- GSD for imagery, NULL for plots
  min_tree_dbh_cm      DOUBLE,                -- tally threshold (plots) — key filter
  min_tree_ht_m        DOUBLE,
  n_observations       INTEGER,               -- trees in plot, images in mission, pulses/m² …

  -- may I use it?
  license_id           TEXT,                  -- normalized SPDX-ish: 'CC-BY-4.0','CC-BY-SA-4.0','CC-BY-NC-SA-4.0','CC0-1.0','PD'
  license_text         TEXT,                  -- original statement, incl. required citation
  allows_commercial    BOOLEAN,
  share_alike          BOOLEAN,
  attribution          TEXT,                  -- contributor names to credit
  contact              TEXT,
  withhold_from_training BOOLEAN,

  -- how good?
  quality_score        DOUBLE,                -- 0–1, collection-specific formula (see §5)
  quality_flags        TEXT[],                -- {'anomaly_sev_3','incomplete_ohvis','oblique_only',…}

  -- everything else, source-native, nothing lost
  attrs                JSON,
  preview_url          TEXT,
  ingested_at          TIMESTAMP
);
CREATE INDEX ON record USING GIST (footprint);

-- Files you can actually fetch for a record (STAC assets)
CREATE TABLE asset (
  record_id     TEXT REFERENCES record,
  role          TEXT,       -- 'orthomosaic','chm','dtm','dsm','point_cloud','mesh','treetops','crowns','raw_images','thumbnail','tree_table'
  href          TEXT NOT NULL,
  media_type    TEXT,       -- 'image/tiff; application=geotiff; profile=cloud-optimized', 'application/vnd.laszip+copc'
  size_bytes    BIGINT,
  variant       TEXT,       -- 'ptcloud' | 'mesh' | 'silva' | 'watershed'
  PRIMARY KEY (record_id, role, variant)
);

-- Record ↔ record links (precomputed, both directions queryable)
CREATE TABLE record_relation (
  from_record   TEXT REFERENCES record,
  to_record     TEXT REFERENCES record,
  rel           TEXT,       -- 'covered_by' | 'overlaps' | 'near' | 'same_site' | 'nested_in' | 'paired_with'
  overlap_frac  DOUBLE,     -- share of from_record's footprint inside to_record
  distance_m    DOUBLE,
  time_gap_days INTEGER,    -- |Δt| — "drone flown 2 yrs after plot survey" matters
  PRIMARY KEY (from_record, to_record, rel)
);

-- Point-level measurements inside a record (trees today; could be LiDAR-detected trees, GEDI shots…)
CREATE TABLE observation (
  obs_id        BIGINT PRIMARY KEY,
  record_id     TEXT REFERENCES record,
  geom          GEOMETRY,   -- POINT
  taxon_code    TEXT,       -- USDA PLANTS symbol
  status        TEXT,       -- 'live' | 'dead' | 'marginal'
  dbh_cm        DOUBLE,
  height_m      DOUBLE,
  attrs         JSON        -- crown, damage, fire-effects, …
);

-- THE heat map: one row per (H3 cell, data_kind). Derived, rebuildable.
CREATE TABLE coverage_cell (
  h3_cell          UBIGINT,   -- stored at res 9 (~0.1 km²), rolled up to res 5–8 for zoom
  h3_res           TINYINT,
  data_kind        TEXT,      -- or '*' for all kinds combined
  n_records        INTEGER,
  covered_frac     DOUBLE,    -- 0–1, union of footprints ∩ cell / cell area (weighted by position certainty)
  n_observations   INTEGER,   -- trees, images…
  n_species        INTEGER,
  earliest         DATE,
  latest           DATE,
  best_quality     DOUBLE,
  open_frac        DOUBLE,    -- share of coverage under commercial-OK licenses
  capabilities     TEXT[],    -- union of what's measurable here
  coverage_score   DOUBLE,    -- composite, §5
  record_ids       TEXT[],    -- for click-through; capped
  PRIMARY KEY (h3_cell, data_kind)
);
```

## 4. Controlled vocabularies

**`data_kind`** (one per collection): `field_plot`, `drone_imagery`, `airborne_lidar`, `satellite_imagery`, `spaceborne_lidar` (GEDI), `fire_perimeter`, `fuel_treatment`, `vegetation_map`, `weather_station`, `other`.

**`capabilities`** (many per record — the researcher-facing filter):

| Capability | OFO plot | OFO nadir mission | OFO oblique mission | Typical external |
|---|---|---|---|---|
| `tree_location` | ✓ | ✓ (detected treetops) | | |
| `species` | ✓ | | (potential, multi-view) | veg maps |
| `dbh` | ✓ (96%) | | | FIA |
| `tree_height` | if `height_measured` | ✓ (CHM) | | LiDAR |
| `live_dead` | ✓ | | | |
| `canopy_height` | | ✓ | | 3DEP, GEDI |
| `crown_delineation` | | ✓ (Silva, Watershed) | | |
| `terrain` | | ✓ (DTM) | | 3DEP |
| `rgb_ortho` | | ✓ | | NAIP |
| `point_cloud_3d` | | ✓ | ✓ | 3DEP |
| `fire_effects` | where scorch/crown-green populated | | | FRAP, MTBS |
| `damage` | if `includes_damage` | | | |

## 5. Coverage & quality scoring (first pass)

Per record, `quality_score ∈ [0,1]`:
- **Drone mission:** start 1.0; −0.15/−0.4/−0.7 for anomaly severity 1/2/3; −0.2 if `agl_fidelity` < 50; scale by image density (log-normalized). Oblique missions flagged, not penalized.
- **Ground plot:** start 1.0; −0.2 if `num_ohvis_trees_excluded` set; −0.1 if `survey_date` precision is year-only; +0.1 if `height_measured`; lower `min_dbh` ⇒ more complete ⇒ small bonus.

Per cell, `coverage_score` combines (weights tunable in the UI, not baked in):
`presence` (any record) · `breadth` (# distinct capabilities) · `depth` (log observations) · `recency` (decay from `latest`, e.g. half-life 5 yr — post-fire landscapes change fast) · `quality` · `openness`.

The UI should let the user pick *which* of these drives the heat-map color; the composite is just the default.

## 6. OFO → schema mapping

| Schema field | Drone mission | Ground plot |
|---|---|---|
| `native_id` | `mission_id` | `plot_id` |
| `footprint` | `geom` | `geom` |
| `area_ha` | `area_derived` | `plot_area_ha` |
| `position_uncert_m` | ~2 if `percent_images_rtk_derived` > 90 else ~5 | 10 |
| `site_id` | cluster of overlapping missions same project + date (nadir/oblique pairs) | `hyperplot_id` else `plot_id` |
| `time_start/end` | `earliest_date_derived` / `latest_datetime_local_derived` (fallback `date`) | parse `survey_date` → precision from digit count |
| `time_approx` | false | `survey_date_approx` |
| `spatial_res_m` | from `altitude_agl_nominal` + sensor (GSD calc) | — |
| `min_tree_dbh_cm`, `min_tree_ht_m` | — | `min_dbh` (or `min_dbh_live`), `min_ht` |
| `n_observations` | `image_count_derived` | count of trees |
| `license_id` | normalize `license` | normalize `license_short` |
| `attribution` | `contributor_names` | `investigator_names` |
| `quality_flags` | `anomaly_severity`, `smart_oblique_derived` | `num_ohvis_trees_excluded`, `notes` |
| `withhold_from_training` | same | same |
| `attrs` | all remaining 60-odd columns | `top_species`, protocol fields, … |
| `asset.href` | `…/ofo-public/drone/missions_03/{id}/photogrammetry_03/full/{id}_{ortho-dsm-ptcloud,chm-ptcloud,dtm-ptcloud,points-copc}…` | — (tree table is `observation`) |

### Cleaning required during ingest
- Mission columns are all text; numeric ones may hold `"90, 80"`. Policy: keep raw in `attrs`, put min/max into typed fields.
- License spelling: `CC-BY 4.0` vs `CC BY 4.0` → same `license_id`.
- `base_lon` sometimes positive (17 rows) → negate.
- `*_local_derived` timestamps are partly UTC; only trust the date for `time_start`, and it may be off by one day.
- `survey_date` is a float (`2008.0`, `201910.0`, `20220715.0`).
- Trees: drop DBH ≥ 500 cm / height ≥ 100 m as errors (OFO's own rule); `live_dead='0'` (3 rows) → null.

## 7. Candidate external sources (to validate the schema stretches)

| Source | data_kind | Footprint | Gotcha the schema already handles |
|---|---|---|---|
| USFS FIA plots | `field_plot` | point, fuzzed | `position_uncert_m` ≈ 1600 |
| USGS 3DEP LiDAR | `airborne_lidar` | project polygons | STAC available; `capabilities` = canopy_height, terrain, point_cloud_3d |
| NEON AOP (SOAP, TEAK, SJER) | `airborne_lidar` + `field_plot` | tiles / plots | NEON plots already in OFO (NEON2023) → dedupe via `record_relation` `same_site` |
| GEDI L2A/L4A | `spaceborne_lidar` | ~25 m shots | huge count → aggregate straight into `coverage_cell`, skip `record` |
| CAL FIRE FRAP perimeters, MTBS | `fire_perimeter` | polygons | not "data about trees" but context: "was this plot surveyed before or after the fire?" via `time_gap_days` |
| CalMAPPER / Interagency Tracking System | `fuel_treatment` | polygons | directly answers the challenge's "did thinning reduce density" question |
| NAIP / Sentinel-2 | `satellite_imagery` | wall-to-wall | ubiquitous → treat as basemap/background, not coverage, or it saturates the heat map |
