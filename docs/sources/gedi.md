# NASA GEDI — L2A shots, L4A footprint biomass, L4B 1 km gridded biomass

Queried 2026-10-23 through NASA CMR. Metadata needs no login; data downloads need Earthdata login, so no shot data was downloaded. Raw outputs are in `data/shapes/gedi/`.

## Endpoints and collections

CMR collection search: `https://cmr.earthdata.nasa.gov/search/collections.umm_json?short_name=<sn>`. Granule search: `https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=<id>&bounding_box=-124.5,32.5,-114,42`. The count comes back in the `CMR-Hits` header.

| Product | short_name / concept_id | Version | Temporal (CMR) | Granules total | Granules in CA bbox |
|---|---|---|---|---|---|
| L2A elevation & RH (LP DAAC) | `GEDI02_A` / `C3974616071-LPCLOUD` | **003** (current) | 2019-04-04 → 2023-03-16, then 2024-04-26 → present | 99,807 | **3,228** (2,585 actually cross the CA polygon) |
| L2A (previous) | `GEDI02_A` / `C2142771958-LPCLOUD` | 002 | same, ending 2025-07-10 | 95,770 | 3,092 |
| L4A footprint AGBD (ORNL) | `GEDI_L4A_AGB_Density_V2_1_2056` / `C2237824918-ORNL_CLOUD` | 2.1 | 2019-04-17 → 2025-07-09 | 96,318 | 3,110 |
| L4A footprint AGBD (ORNL) | `GEDI_L4A_AGB_Density_V3_2508` / `C4212593885-ORNL_CLOUD` | **3** (new) | 2019-04-04 → present | 96,886 | **3,133** |
| L4B 1 km gridded AGBD (ORNL) | `GEDI_L4B_Gridded_Biomass_V2_1_2299` / `C2792577683-ORNL_CLOUD` | 2.1 | 2019-04-18 → 2023-03-16 (single composite) | **10** (one global GeoTIFF per variable) | 10 |

L2A V003 granules in the CA bbox, by year: 2019: 445, 2020: 637, 2021: 601, 2022: 636, **2023: 119**, 2024: 382, 2025: 408, 2026: 0. The last granule is 2025-09-03. CMR shows no 2026 data yet, which may be a processing lag or a mission pause. *Unverified which.*

DOIs: L2A 10.5067/GEDI/GEDI02_A.003. L4A 10.3334/ORNLDAAC/2056 (V2.1). L4B 10.3334/ORNLDAAC/2299.

## Granule structure

- **Granule = one ISS sub-orbit** (an orbit split into about 4 segments). Example name: `GEDI02_A_2025246120816_O38100_03_T00251_02_005_02_V003`. The parts are the acquisition time (YYYYDDDHHMMSS), orbit `O38100`, sub-orbit `03`, reference ground track `T00251`, and version.
- The CMR footprint is a `GPolygon`: a thin out-and-back outline along the ground track with vertices about 6° apart. It is too coarse for clipping, but fine for "which tracks cross CA".
- Sizes: L2A V003 is about **1.4 GB median per granule** (global sub-orbit), so you cannot fetch a whole state casually. L4A V3 is about 210–280 MB per granule. L4B GeoTIFFs are 14–536 MB each. CMR labels these sizes "MB", but the values are actually bytes.
- Format is HDF5 with one group per beam: `BEAM0000`, `BEAM0001`, `BEAM0010`, `BEAM0011` are coverage beams (one laser split in two, lower energy), and `BEAM0101`, `BEAM0110`, `BEAM1000`, `BEAM1011` are full-power beams. Datasets are 1-D per shot (dimension `MT`). `rh` is `(MT, 101)`.
- Coordinates are WGS84 lon/lat (EPSG:4326). Elevations are ellipsoidal.

## Shot fields (L2A, `GEDI02_A`)

Source: the LP DAAC L2A data dictionary (`raw_gedi_l2a_data_dictionary.txt`).

| Field | Type | Example / range | Meaning |
|---|---|---|---|
| `shot_number` | uint64 | `OOOOOBBRRGNNNNNNNN` | Unique shot ID: orbit, beam, reserved, sub-orbit, index. Joins L2A, L2B, and L4A. |
| `beam` | uint16 | 0,1,2,3,5,6,8,11 | Beam ID. Also implied by the group name. |
| `delta_time` | float64 | about 1.2e8 to 2.5e8 | Seconds since 2018-01-01T00:00Z. |
| `lat_lowestmode` / `lon_lowestmode` | float64 | 38.21 / -120.33 | Ground (lowest mode) location. **Use these as the shot point.** |
| `elev_lowestmode` | float32 | m | Ground elevation (WGS84 ellipsoid). |
| `elev_highestreturn` | float32 | m | Canopy-top elevation. |
| `rh` | float32[101] | -213..213 m | Relative heights at 0–100%. There is no `rh98` dataset: **`rh98 = rh[:, 98]`**. Canopy height is usually rh98 or rh100. |
| `quality_flag` | uint8 | 0/1 | 1 means the shot is usable (signal, sensitivity, and surface checks pass). |
| `sensitivity` | float32 | 0–1 | Maximum canopy cover the shot can penetrate. Filter at ≥ 0.95 on land (0.98 in tropical evergreen broadleaf forest). |
| `degrade_flag` | uint8 | 0 = OK | Degraded pointing (tens digit) or positioning (ones digit). |
| `surface_flag` | uint8 | 0/1 | 1 if the ground is within 300 m of the DEM or mean sea surface. |
| `solar_elevation` | float32 | deg | Above 0 means daytime, which means more noise and lower pass rates. |
| `num_detectedmodes`, `selected_algorithm` | uint8 | 1–6 | Waveform processing details. |
| `land_cover_data/landsat_treecover`, `pft_class`, `leaf_off_flag`, `urban_proportion` | various | | Ancillary land cover. |

## Footprint biomass fields (L4A)

Source: ORNL user guides V2.1 and V3 (`raw_gedi_l4a_v3_variable_tables.txt`).

| Field | Type | Units | Meaning |
|---|---|---|---|
| `agbd` | float32 | Mg/ha | Predicted aboveground biomass density. Fill value -9999. |
| `agbd_se` | float32 | Mg/ha | Prediction standard error. |
| `agbd_pi_lower` / `agbd_pi_upper` | float32 | Mg/ha | Prediction interval (alpha set by an attribute). |
| **`l4_quality_flag`** (V2.1) → **`l4a_quality_flag_rel3`** (V3) | uint8 | 0/1 | Recommended-prediction flag. **The name changed between versions.** |
| `l2_quality_flag` (V2.1) → `l2a_quality_flag_rel3` (V3) | uint8 | 0/1 | Whether the L2A input is fit for biomass estimation. |
| `degrade_include_flag`, `elev_highestreturn_outlier_flag` | uint8 | | New in V3. Use both when gridding or fusing data. |
| `predict_stratum` | string | e.g. ENT_NAm | PFT × continent model. California is mostly ENT (evergreen needleleaf) and GSW (grass/shrub/woodland), and some DBT. |
| `predictor_limit_flag`, `response_limit_flag` | uint8 | 0/1/2 | Whether the input or prediction falls outside the training range. |
| `shot_number`, `beam`, `delta_time`, `lat_lowestmode`, `lon_lowestmode`, `sensitivity`, `degrade_flag`, `solar_elevation` | | | Copied from L2A. |
| `land_cover_data/leaf_off_flag` | uint8 | 1/0/255 | Leaf-off, leaf-on, or null. |
| `agbd_prediction/agbd_aN` … | | | Alternative predictions for algorithm groups N ∈ {1,2,5,10}. |

**Quality recipe.** V2.1 `l4_quality_flag = 1` requires all of these: `l2_quality_flag = 1` (algorithm_run_flag = 1, surface_flag = 1, stale_return_flag = 0, sensitivity > 0.9, rx_maxamp > 8 × sd_corrected), `sensitivity > 0.95`, `landsat_water_persistence < 10`, and `urban_proportion < 50`. In deciduous strata it also requires `leaf_off_flag = 0`. V3 adds `is_land_rel3 = 1`, `predict_stratum != None`, and `rh100 < 150 m`. It also adds the degrade codes attitude ∈ {0,1,2,3,4,6} and trajectory ∈ {0,3,8}.

## L4B gridded raster

Source: ATBD v2.0 Table 3-1 and CMR granule names. Files are named `GEDI04_B_MW019MW223_02_002_02_R01000M_<CODE>.tif`. **Each variable is a separate single-band global GeoTIFF.**

| Code | Type | Nodata | Meaning |
|---|---|---|---|
| `MU` | float32 | -9999 | Mean AGBD in Mg/ha (forest and non-forest). |
| `SE` | float32 | -9999 | Standard error of the mean, Mg/ha. |
| `PE` | uint8 | 255 | SE as a percent of the mean. |
| `V1` / `V2` | float32 | -9999 | Variance components: V1 is model error, V2 is sampling error (MI=1) or second-model error (MI=2). |
| `NC` | uint16 | 0 | Number of clusters: distinct ground tracks with at least one good shot. |
| `NS` | uint32 | 0 | Number of high-quality shots in the cell. **This is the shot-density layer for the heat map.** |
| `QF` | uint8 | 0 | 0 = outside domain, 1 = land, 2 = land and meets precision (PE < 20% or SE < 20 Mg/ha). |
| `PS` | uint16 | 0 | L4A prediction stratum ID. |
| `MI` | uint8 | | Mode of inference: 0 = none, 1 = hybrid (needs at least 2 tracks), 2 = GHMB. |

- **Resolution 1 km (1000 m), EASE-Grid 2.0 global.** The CRS is EPSG:6933 per the ORNL user guide. *The CRS code and the grid dimensions (about 34,704 × 14,616) are not verified from file headers this session.*
- It is a single time-composite, not a time series.
- Cells crossed by fewer than 2 tracks get `MI = 0` and `MU = 0` or nodata. They are not interpolated.

## Shot density over California (estimate)

Full output: `gedi_ca_track_density_estimate.json`.

- **Geometry by design:** 8 beams with footprints about 25 m across, **60 m apart along-track**. Beams are **600 m apart across-track**, so one pass covers a swath about 4.2 km wide. Within a single swath that is about 32 shots/km², but the shots lie on 8 lines, not spread evenly.
- **Track length:** summing CMR track lengths of the 2,585 L2A V003 granules that cross CA gives about **1.06 million track-km inside CA** (2019-04 to 2025-09). By year: 2019: 144k, 2020: 223k, 2021: 192k, 2022: 205k, 2023: 39k, 2024: 125k, 2025: 132k km.
- **Raw shots:** 1.06M km × 8 beams × 16.7 shots/km ≈ **141 million shots, about 333 shots/km² over the mission.** This is an upper bound: it ignores laser-off gaps and empty or cloudy returns.
- **After quality filtering:** assuming 30–50% of shots pass `quality_flag` / `l4_quality_flag` in CA, density is about **100–170 good shots/km² for the full mission**, or about 75–125 for the L4B period (2019-04 to 2023-03). This works out to roughly 100 good shots per 1-km cell over the mission. *The pass fraction is unverified.* It is an assumption based on general GEDI experience, not a measured CA value. Check it against the L4B `NS` layer if anyone downloads it.
- The coverage beams have lower energy and fail the 0.95 sensitivity test more often under dense conifer canopy, as in the Sierra and North Coast. Expect lower good-shot density in tall, dense forest.

## Gotchas for the simulator

- **Track pattern:** coverage comes as stripes. Each pass is 8 parallel lines 600 m apart, and passes cross in ascending and descending diagonal directions. Many 1-km cells are hit by 0–2 tracks, and gaps of several km between tracks are normal. Do not simulate uniform random points.
- **Mission gap:** the instrument was stored on the ISS from **mid-March 2023 to April 2024**, so 2023 has only about 2.5 months of data. 2019 starts in April. 2026 has no granules in CMR yet.
- **Orbit resonance (2020–2021):** an ISS altitude change made some ground tracks repeat at the expense of others, leaving uneven coverage holes (per the ATBD).
- **Latitude limit:** GEDI covers 51.6°S to 51.6°N, so all of California is in range. Track density rises toward the turning latitude, so CA at 32–42°N gets more coverage than the tropics.
- **Quality filtering is essential.** Raw files include shots over cloud tops and noise. Always apply `quality_flag == 1` (L2A) or `l4_quality_flag == 1` (L4A V2.1) / `l4a_quality_flag_rel3 == 1` (V3), plus `degrade_flag == 0` and `sensitivity >= 0.95`. Daytime shots (`solar_elevation > 0`) pass less often.
- **Leaf-off:** leaf-off shots in deciduous strata are excluded from L4A quality. This matters little for CA conifer forest, but does affect oak woodland (DBT).
- **Versions:** L2A V003 and L4A V3 are current. L4A V2.1 ends 2025-07. **L4B exists only as V2.1 (to 2023-03).** The V1 to V2 change altered the `shot_number` format, so old shot IDs don't join to new ones.
- **Geolocation:** the footprint is about 25 m across, with about 10 m horizontal geolocation error (*from literature, not re-verified*). Plot it as a point, not a polygon.
- **No real shot rows were downloaded** because Earthdata login is required. The field names, types, and ranges come from the official dictionaries. Example values in the tables above are illustrative.
