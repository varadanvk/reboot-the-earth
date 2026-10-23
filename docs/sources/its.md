# CA Interagency Tracking System (ITS) Treatments

Verified 2026-10-23 by live queries. Raw artifacts: `data/shapes/its/{layer.json,sample.geojson,stats.json}`.

The ITS backs the Wildfire & Forest Resilience Task Force "Interagency Treatment Dashboard". It is hosted by UCSD SDSC (WIFIRE / SPARCAL), with catalog entries at wifire-data.sdsc.edu ("Interagency Treatment Dashboard: Activity/Footprint Report").

## Endpoint

- Primary (used here): `https://sparcal.sdsc.edu/arcgis/rest/services/Hosted/ITSV2_1_Polygons_gdb/FeatureServer/0` (**428,309** activity polygons, all `trmt_geom=POLYGON`)
- Sibling layers in the same version (v2.1):
  - `ITSV2_1_Points_gdb/0`: 23,839 points
  - `ITSV2_1_Lines_gdb/0`: 158,618 polylines
  - `ITSV2_1_Activity_gdb/0`: 537,887 points (all activities as centroids)
  - `ITSV2_1_Footprint_Polygons_gdb/0`: 43,167 polygons, slim schema: `trmtid_user, activity_quantity, agency, in_wui, primary_ownership_group, broad_vegetation_type, region, county, year_txt`. This is the dashboard's "Footprint" view, where each acre is counted once per year.
- Older versions on the same server: `ITS_V1_1_*`, `ITS_V2_0_*`, `ITS_Dashboard_Feature_Layer_74420` (Aug 2023 snapshot, 807 points).
- Geometry: `esriGeometryPolygon`, mixed Polygon and MultiPolygon in GeoJSON.
- Native CRS: EPSG:3857 (wkid 102100); use `outSR=4326`. maxRecordCount 2000. Statistics queries are supported.
- `sample.geojson` = 20 features at evenly spaced OBJECTIDs (1, 21416, ...), simplified (`maxAllowableOffset=0.0001`). The unsorted first 20 rows were all from one BLM project near the Mexico border, so data seems ordered by latitude.

## Structure

Each row is an **activity** flattened with its parent **treatment** and **project**. The suffixes `_p` / `_t` / `_a` are project, treatment, and activity. The same treatment area can appear as many stacked activity rows (e.g. thin, then pile, then pile-burn), which makes the polygons **overlap heavily**.

## Fields that matter

| Field | Type | Example | Meaning |
|---|---|---|---|
| objectid | OID | 1 | row id (1 to 428,309) |
| source | String | `usfs_treatments` | upstream system: usfs_treatments (FACTS), CNRA (CalMAPPER / state), Industrial Timber, BLM, nps_flat_fuelstreatments, IFPRS, nfpors_haz_fuels_treatments_reduction |
| agency | String | `USDA` | USDA, CNRA, TIMBER, DOI, NPS, OTHER |
| administering_org / admin_org_name | String | `BLM` | org that owns the record |
| project_name / activity_name | String | `2_BP_Border Mountains International FB-1` | free text |
| projectid_user / trmtid_user / activid_user | String | `NFPORS6318411` | source ids (activid often null) |
| year | Double | 2020 | reporting year (derived from activity_end) |
| year_txt / federal_fy / state_fy | String | `2020` / `2020` / `2021` | year variants (state FY starts Jul 1) |
| activity_start / activity_end | **String** | `2019-10-01 00:00:00+00:00` | ISO-ish text, not epoch |
| activity_status | String | `COMPLETE` | COMPLETE / ACTIVE / PLANNED / PROPOSED / OUTYEAR / CANCELLED |
| project_status / treatment_status | String | `ACTIVE` | mostly null (only CNRA-sourced rows fill them) |
| activity_cat | String | `MECH_HFR` | MECH_HFR (mechanical hazardous-fuel reduction), TREE_PLNTING, TIMB_HARV, PRESCRB_FIRE, NOT_DEFINED, GRAZING, LAND_PROTEC |
| activity_description | String | `THIN_MECH` | 61 codes (see stats) |
| activity_quantity / activity_uom | Double / String | `162.15` / `AC` | amount treated; 99.3% in acres (also EA, TON, MI, HR) |
| treatment_area | Double | 156.3 | acres of the parent treatment polygon |
| primary_objective | String | `OTHER_FUELS_REDUCTION` | 27 codes |
| broad_vegetation_type | String | `FOREST` | FOREST, SHRB_CHAP, GRASS_HERB, SPARSE, URBAN, ... |
| primary_ownership_group | String | `FEDERAL` | FEDERAL, PRIVATE_NON-INDUSTRY, STATE, PRIVATE_INDUSTRY, LOCAL, NGO, TRIBAL |
| in_wui | String | `WUI_AUTO_POP` | WUI_/NON-WUI_ + USER_DEFINED or AUTO_POP (computed) |
| region | String | `SIERRA_NEVADA` | Task Force region: SIERRA_NEVADA, NORTH_COAST, SOUTHERN_CA, CENTRAL_COAST |
| county | String | `SD` | **3-letter county abbreviation** (not FIPS) |
| counts_to_mas | String | `YES` | counts toward the state's 1M-acres/yr "Million Acre Strategy" target |
| latitude / longitude | Double | 32.563 / -116.815 | centroid |
| valid_geom | String | `VALID` | VALID or FIXED (4,941 repaired) |
| val_* / review_* / dataload_* | String | null | QA pipeline columns, almost always null |

## Distributions (from `stats.json`)

- **Years:** 1950 to 2025 (plus 607 in 2026, 10 in 2027, 1 in 2030, and **470 with year=0**). Volume ramps from ~100/yr in the early 1950s to a peak of ~15k/yr in 1989–91, sits at ~6–8k/yr from 2000–2020, then climbs to 10.6k (2021), 13.0k (2022), 16.2k (2023), **19.0k (2024)**, 18.0k (2025).
- **Source:** usfs_treatments 378,638 (88%); CNRA 43,130; Industrial Timber 3,158; BLM 1,220; NPS 831; IFPRS 689; NFPORS 643.
- **Status:** COMPLETE 414,426; ACTIVE 13,763; PLANNED 48; CANCELLED 29; PROPOSED 28; OUTYEAR 12.
- **Category:** MECH_HFR 201k; TREE_PLNTING 102k; TIMB_HARV 64k; PRESCRB_FIRE 50k; NOT_DEFINED 10k; GRAZING 592.
- **Top activities:** TREE_PLNTING 63.6k, TREE_RELEASE_WEED 50.1k, THIN_MECH 49.7k, SITE_PREP 37.9k, INV_PLANT_REMOVAL 33.4k, PILE_BURN 31.0k, CLEARCUT 26.9k, PILING 24.6k, BROADCAST_BURN 17.9k, COMM_THIN 17.4k.
- **Vegetation:** FOREST 344k; SHRB_CHAP 60k; GRASS_HERB 17k.
- **Region:** Sierra Nevada 223k; North Coast 177k; Southern CA 17k; Central Coast 10k.
- **Size (activity_quantity):** mean 42 ac, max 722,470. Buckets: <1 ac 42.9k; 1–10 156.5k; 10–100 207.3k; 100–1000 20.2k; ≥1000 1.1k. treatment_area mean 70 ac.
- **counts_to_mas:** YES 374k / NO 54k. **WUI:** 28% of rows.

## Gotchas

- **Dates are strings, with inconsistent formats.** You'll see `2022-05-27` alongside `2025-12-31 00:00:00+00:00`, and **470 rows have the literal `"NaT"`** (a pandas leak; these are the `year=0` rows). `activity_start` is null in 379,935 rows (89%). Only USFS rows give the end date. Use `year` (or `state_fy`) for time.
- **Planned vs completed:** filter `activity_status='COMPLETE'` for actual coverage. ACTIVE/PLANNED/PROPOSED/OUTYEAR rows (about 14k) are future or in-progress, and some have future years (2026–2030).
- **Activity vs footprint:** the polygon layer is activity-level, so stacked activities on the same ground double-count acres. For "area treated" use the Footprint layer or union the geometry. `activity_quantity` (reported) can differ a lot from the polygon area and from `treatment_area` (e.g. 99 ac activity on a 2,167 ac treatment).
- Includes non-fuels work (clearcuts, planting, site prep). Fuels-only views usually filter `activity_cat IN ('MECH_HFR','PRESCRB_FIRE','GRAZING')` or `counts_to_mas='YES'`.
- Multipart polygons are common for CNRA/BLM. Points and lines live in separate layers (lines = fuel breaks/roads, measured in MI).
- `activity_uom` is not always AC. Check it before summing quantity.
- Very wide schema (~100 cols, String(65536)). Request explicit `outFields` to keep payloads small.
- **CalMAPPER** (CAL FIRE's own project tracker) feeds ITS via the CNRA source. Its public dashboard view is `https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/CMDash_v3_view/FeatureServer` ("CAL FIRE Fuel Reduction Projects v2"). I didn't inspect it.
