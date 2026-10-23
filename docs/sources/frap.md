# CAL FIRE FRAP Fire Perimeters (firep)

Verified 2026-10-23 by live queries. Raw artifacts: `data/shapes/frap/{layer.json,sample.geojson,stats.json}`.

## Endpoint

- Service: `https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/California_Historic_Fire_Perimeters/FeatureServer`
  - Layer **0** "California Fire Perimeters (all)": **23,334** features (used here)
  - Layer 2 "California Fire Perimeters (1950+)": 18,064
  - Layer 1 "Recent Large Fire Perimeters (GT 5000 acres)": 83
- Note: `.../California_Fire_Perimeters/FeatureServer` (the older name) now returns 499 Token Required.
- Geometry: `esriGeometryPolygon` (GeoJSON comes back as a mix of `Polygon` and `MultiPolygon`)
- Native CRS: EPSG:3857 (wkid 102100); request `outSR=4326` for lon/lat.
- maxRecordCount 2000 → paginate with `resultOffset`. Last edit: 2026-07-28 (data through Dec 2025 fires).
- `sample.geojson` = 20 features spread evenly across OBJECTID (1878 to 2025), simplified (`maxAllowableOffset=0.0002`, 6 dp). Raw geometries are heavy: the top 20 (2025) fires were 4.7 MB, up to **23k vertices** and **42 parts** per fire.

## Fields that matter

| Field | Type | Example | Meaning |
|---|---|---|---|
| OBJECTID | OID | 1 | row id |
| YEAR_ | SmallInteger | 2025 | fire year (77 null) |
| FIRE_NAME | String(34) | `GIFFORD` | name; often null in old records |
| AGENCY | String(3), domain | `USF` | lead agency: USF, CDF, CCO (contract county), NPS, BLM, LRA, DOD, FWS, BIA, OTH |
| UNIT_ID | String(3), domain | `LPF` | unit (e.g. LPF = Los Padres NF, LNU) |
| INC_NUM | String(8) | `00002181` | local incident number |
| IRWINID | String(40) | `{08A6358F-83...}` | national incident GUID; only ~16% populated (recent) |
| ALARM_DATE | Date (epoch ms, UTC) | 1754006400000 (2025-08-01) | ignition/report date |
| CONT_DATE | Date (epoch ms, UTC) | 1760400000000 (2025-10-14) | containment date |
| CAUSE | SmallInt, domain | 14 | 1 Lightning, 2 Equipment, 7 Arson, 9 Misc, 10 Vehicle, 11 Power line, 14 Unknown, 18 Escaped Rx burn, ... (1–19) |
| C_METHOD | SmallInt, domain | 3 | mapping method: 1 GPS ground, 2 GPS air, 3 Infrared, 4 Other imagery, 5 Photo interp, 6 Hand drawn, 7 Mixed, 8 Unknown |
| OBJECTIVE | SmallInt, domain | 1 | 1 Suppression (wildfire), 2 Resource benefit (WFU) |
| GIS_ACRES | Single | 131614 | computed burned acres |
| COMMENTS | String(100) | `Edited in InFORM Inspector` | free text |
| COMPLEX_NAME / COMPLEX_ID | String | | fire complex grouping |
| DECADES | String(9) | `2020-2025` | decade bucket; **null for pre-1950** |
| STATE | String(2) | `CA` | 23,317 CA; a few NV/OR/AZ |
| Shape__Area / Shape__Length | Double | | in Web Mercator m² (distorted; use GIS_ACRES) |

## Distributions (from `stats.json`)

- **Years:** 1878 to 2025. Pre-1950: 5,270 rows. By decade: 1950s 1,819; 1960s 1,276; 1970s 1,879; 1980s 2,206; 1990s 1,992; 2000s 2,905; 2010s 3,429; 2020–25 2,558.
- **Recent years (count / acres):** 2017 611 / 1.43M; 2018 416 / 1.58M; 2020 504 / **4.18M**; 2021 388 / 2.51M; 2022 307 / 0.32M; 2023 285 / 0.34M; 2024 553 / 1.01M; 2025 521 / 0.51M. That's roughly 300–600 perimeters a year with very heavy-tailed acreage.
- **Size (GIS_ACRES):** min 0.0009, mean 1,914, max 1,032,700 (August Complex 2020). Buckets: <10 ac 3,001; 10–100 7,452; 100–1k 8,677; 1k–10k 3,426; 10k–100k 731; ≥100k 47.
- **Agency:** USF 9,761; CDF 7,474; CCO 3,643; NPS 1,052; BLM 789; LRA 282; DOD 173; other <200.
- **Cause:** Unknown (14) 10,514; Lightning 3,648; Misc 3,533; Equipment 1,455; Arson 1,018; Debris 806; Vehicle 639; Power line 506.
- **C_METHOD:** 8 Unknown 15,081 (most of the history); GPS ground 4,405; hand drawn 1,227; mixed 1,148.
- **Objective:** Suppression 22,781; WFU 282; null 271.

## Gotchas

- **Dates are epoch milliseconds** set to midnight UTC (date-only values). Pre-1970 dates are **negative**. Min ALARM_DATE is 1898-04-01; max is 2025-12-24.
- Many date nulls: ALARM_DATE null in 5,384 rows, CONT_DATE null in 12,618. Use `YEAR_` as the reliable temporal key.
- **Multipart**: large modern fires are MultiPolygons with dozens of parts and holes (unburned islands). Perimeters **overlap** across years (reburns). Coverage maps should union per year, or count overlaps deliberately.
- Default query order is not by OBJECTID. An unsorted `resultRecordCount=20` returned the 2025 largest fires.
- Includes small fires (<10 ac) and some prescribed/WFU events (`OBJECTIVE=2`). The prescribed-burn layer (rxburn) is separate and not in this service.
- `COMMENTS` sometimes holds the literal string `"<Null>"`.
- `DECADES` is null for everything before 1950, so don't use it as the year filter.
- Shape__Area is Web Mercator area. Use GIS_ACRES.

## MTBS (brief, verified)

- Esri-hosted mirror of USFS EDW: `https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/EDW_MTBS_v1/FeatureServer/0` ("Burned Area Boundaries (All Years)"), with 30,930 CONUS polygons. **California: 1,956** (`FIRE_ID LIKE 'CA%'`), 1984–2025. The USFS original (`apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MTBS_01/MapServer/63`) did not resolve from here.
- Key fields: `FIRE_ID` (e.g. `CA4196012323320120805` = state + lat/lon + ignition date), `FIRE_NAME`, `YEAR`, `STARTMONTH`, `STARTDAY`, `FIRE_TYPE` (Wildfire / Prescribed Fire / ...), `ACRES`, `IRWINID`, `IG_DATE` (**integer YYYYMMDD**, not epoch), `ASMNT_TYPE` (Initial/Extended), `PRE_ID`/`POST_ID` (Landsat scene ids), dNBR thresholds (`LOW_THRESHOLD`, `MODERATE_THRESHOLD`, `HIGH_THRESHOLD`, ...), `LATITUDE`/`LONGITUDE`.
- Only large fires are included (≥1,000 ac West). The per-pixel severity rasters are separate from these perimeters.
