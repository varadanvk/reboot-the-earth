# USGS 3DEP airborne lidar — WESM work-unit footprints

Queried 2026-10-23. Raw outputs: `data/shapes/3dep/`.

## Endpoints

| What | URL | Notes |
|---|---|---|
| ArcGIS REST layer (used) | `https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer/8` ("Lidar Point Cloud") | WESM attribute schema, polygon geometry, `query` supports `f=geojson`, `outSR=4326`, statistics, pagination. maxRecordCount 2000. Layer 24 is a copy with the same count. Layer 11/27 ("DEM - Source") holds 2625 rows. |
| WESM CSV (attributes only, 2.2 MB) | `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/WESM.csv` | Same 28 fields, no geometry. Includes work units whose point cloud isn't published yet. |
| WESM GeoPackage | `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/WESM.gpkg` | **3.79 GB**, not downloaded. Updated daily (Last-Modified 2026-10-23). |
| CA boundary used for the state filter | TIGERweb `State_County/MapServer/0`, `STUSAB='CA'`, generalized to 0.01° | |

Example CA query (POST, because the polygon is long):
```
.../MapServer/8/query  geometry=<esri polygon json> geometryType=esriGeometryPolygon inSR=4326
  spatialRel=esriSpatialRelIntersects where=1=1 outFields=* outSR=4326 maxAllowableOffset=0.002 f=geojson
```

## Counts

| Set | Count |
|---|---|
| REST layer 8, all US | **2,861** work units |
| WESM.csv, all rows | 3,293 (447 have no `lpc_pub_date`, meaning they are in progress) |
| REST, intersects CA bbox (-124.5,32.5,-114,42) | 258 |
| REST, intersects CA state polygon | **203** work units, in 106 distinct projects |
| CSV rows with `workunit` prefix `CA_` | 169 (3 of them unpublished, e.g. `CA_2025FireImpactZoneEaton_PRELIMINARY_C25`) |

The 203 includes units from neighbouring states that cross the border (for example `OR_OLC_KENO_2012`). Filtering by name prefix misses those, so filter spatially.

## Geometry / CRS

- `esriGeometryPolygon`. In GeoJSON: 117 `Polygon` and 86 `MultiPolygon` (the multipolygons are fire-zone or tribal-land units in pieces).
- The service's native CRS is Web Mercator (EPSG:3857). Request `outSR=4326` to get lon/lat.
- `SHAPE_Area` and `SHAPE_Length` are in **Web Mercator m²/m, so they are inflated** (about 1.6x at 37°N: 9,334 vs 5,700 km² for `CA_SierraNevada_8_2022`). Compute geodesic area yourself.
- The source data's projections (`horiz_crs`) vary per unit. CA mostly uses EPSG 6340/6339 (NAD83(2011) UTM 11N/10N), 6350 (CONUS Albers), 26911/26910, and 6418/6420/6422 (CA State Plane). This only matters if you fetch the point clouds.

## Fields that matter

Dates arrive from REST as **epoch milliseconds (UTC)**. The CSV uses `YYYY/MM/DD`.

| Field | Type | Example | Meaning |
|---|---|---|---|
| `workunit` | string | `CA_SierraNevada_8_2022` | Work unit name. One acquisition block and the unit of the footprint. |
| `workunit_id` | int | 300363 | Unique ID. Legacy units have negative IDs (e.g. -1169). |
| `project` / `project_id` | string/int | `CA_SierraNevada_B22` / 224823 | Parent project. One project has 1 to many work units. |
| `collect_start` / `collect_end` | date | 2021-11-18 / 2022-08-25 | Acquisition window. Can span many months and seasons. |
| `ql` | string | `QL 1` | Quality level. Values are `QL 0`, `QL 1`, `QL 2`, `QL 3`, `Other`. |
| `spec` | string | `USGS Lidar Base Specification 2022 Revision A` | Lidar Base Specification version. `Other` means pre-spec or legacy. |
| `p_method` | string | `linear-mode lidar` | Also `Topobathymetric LIDAR`, `Bathymetric LIDAR`, Geiger/SPL elsewhere. |
| `dem_gsd_meters` | double | 0.5 / 1 / 3 | Ground sample distance of the source DEM. |
| `lpc_category` | string | `Meets` | 3DEP point-cloud acceptance: `Meets`, `Meets with variance`, `Does not meet`, `Expected to meet`, `Not Applicable`. |
| `lpc_pub_date` | date | 2024-04-17 | When the point cloud was published. |
| `onemeter_category`, `seamless_category`, `sourcedem_category` | string | `Meets` | Whether the unit feeds the 1 m DEM, the seamless DEM, or the source DEM. |
| `lpc_link`, `sourcedem_link`, `metadata_link` | url | rockyweb / prd-tnm | Data download locations. |
| `horiz_crs` / `vert_crs` / `geoid` | string | `6340` / `5703` / `GEOID18` | EPSG codes of the delivered data. |

There are 33 fields in total. See `layer8_metadata.json` (REST) and `wesm_csv_fields_and_unpublished.json` (CSV, 28 fields).

## Distributions — 203 CA work units (`wesm_ca_stats.json`)

- **collect_start year:** 2002–2016 has a thin tail of 1–11 units per year, 59 units in total. Most units started 2017–2025: 2017: 16, 2018: 24, 2019: 14, 2020: 12, 2021: 27, 2022: 24, 2023: 14, 2024: 9, 2025: 4.
- **QL:** QL 1 has 99 units, QL 2 has 55, Other has 47 (44 from 2002–2012 legacy, plus 1 from 2021 and the 2 PRELIMINARY 2025 fire units), and QL 0 has 2. No QL 3 in CA.
- **lpc_category:** Meets 132, Does not meet 51, Meets with variance 18, Expected to meet 1, Not Applicable 1.
- **Footprint area** (geodesic, whole polygon including any part outside CA): min 0.6 km², p10 157, **median 2,393**, p90 9,080, max about 14,100 km². The sum is 704k km², against CA's 424k km² of land.
- **Collection duration:** median 31 days, p90 280 days, max 913 days.
- **Coverage on a 0.05° grid inside CA (17,231 cells):** **97.1% of CA has at least one work unit.** Overlap depth: 0 units 2.9%, 1 unit 67.7%, 2 units 25.3%, 3 units 3.1%, 4 or more about 1%. The newest `collect_end` per covered cell is 2022 for 28.8% of cells, 2024 for 18.8%, 2021 for 14.8%, 2018 for 11.4%, 2023 for 10%, 2019 for 8.3%, 2020 for 4.5%, and 2017 or earlier for about 3%.

The 20-row sample in `wesm_ca_sample20.geojson` is spread evenly across collect_start dates. It is WGS84 GeoJSON with the added property `_area_km2`. `wesm_lpc_ca_state_all.geojson` holds all 203 units, simplified to 0.002°, 1.3 MB.

## Gotchas for the simulator

- **Overlaps are normal.** About 30% of CA is covered two or more times: legacy flights, newer statewide flights, and post-fire re-flights (the 2025 Eaton and Palisades `PRELIMINARY` units). For freshness, use the max `collect_end` per cell. Summing coverage double-counts.
- **"Other" QL is mostly legacy** (2002–2012 county, academic, and FEMA data), plus a few non-spec rapid-response collections. These units mostly fail spec (`lpc_category = Does not meet`). Weight or exclude them.
- **QL meaning** (Lidar Base Spec): QL0 is ≥8 pts/m² with ≤5 cm RMSEz. QL1 is ≥8 pts/m² with ≤10 cm RMSEz. QL2 is ≥2 pts/m² with ≤10 cm RMSEz. QL3 is ≥0.5 pts/m² with ≤20 cm RMSEz. These numbers come from the spec, not from this data. *Not re-verified this session.*
- **Leaf-off is not a field.** The spec prefers leaf-off, snow-free collection, but nothing in WESM records it. Collection windows like Nov to Aug span seasons. For CA conifer forest this matters little.
- **Work units are not tiles.** Footprints are irregular buffered survey outlines with holes, slivers, and multipart pieces, and some are smaller than 1 km².
- The REST layer lags the CSV and gpkg: it holds only units with a published point cloud. Use the CSV `lpc_pub_date` being empty to simulate "in progress" units.
- The REST service caps responses at 2,000 records per page. CA (203) fits in one page.
