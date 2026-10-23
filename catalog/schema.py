"""Unified record schema shared by every source adapter (see docs/schema.md).

Every adapter returns a GeoDataFrame with exactly RECORD_COLUMNS (EPSG:4326). List-valued
columns hold Python lists; `attrs` holds a JSON string of source-native fields.
"""

import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RECORDS = DATA / "catalog" / "records"   # one GeoParquet per source
WEB_DATA = ROOT / "web" / "data"

DATA_KINDS = [
    "field_plot", "drone_imagery", "airborne_lidar", "spaceborne_lidar",
    "fuel_treatment", "fire_perimeter",
]

CAPABILITIES = [
    "tree_location", "species", "dbh", "tree_height", "live_dead", "canopy_height",
    "crown_delineation", "terrain", "rgb_ortho", "point_cloud_3d", "biomass",
    "fire_effects", "damage", "treatment_history", "disturbance_history",
]

RECORD_COLUMNS = [
    "record_id", "collection_id", "source_id", "native_id", "title",
    "geometry", "area_ha", "position_uncert_m", "site_id",
    "time_start", "time_end", "time_precision", "time_approx",
    "data_kind", "capabilities", "spatial_res_m", "min_tree_dbh_cm", "min_tree_ht_m",
    "n_observations",
    "license_id", "allows_commercial", "share_alike", "attribution", "withhold_from_training",
    "quality_score", "quality_flags",
    "simulated", "preview_url", "attrs",
]

# license_id -> (allows_commercial, share_alike)
LICENSES = {
    "CC0-1.0": (True, False),
    "PD": (True, False),
    "CC-BY-4.0": (True, False),
    "CC-BY-SA-4.0": (True, True),
    "CC-BY-NC-4.0": (False, False),
    "CC-BY-NC-SA-4.0": (False, True),
}


def normalize_license(raw):
    """Map free-form license strings ('CC-BY 4.0', 'CC BY NC SA 4.0', 'Public domain') to LICENSES keys."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = str(raw).upper().replace("-", " ").replace("_", " ")
    if "PUBLIC DOMAIN" in s:
        return "PD"
    if "CC0" in s:
        return "CC0-1.0"
    parts = [p for p in ("NC", "SA") if f" {p} " in f" {s} "]
    return "-".join(["CC", "BY", *parts, "4.0"])


def area_ha(gdf):
    return gdf.to_crs(3310).area / 1e4   # California Albers


def clean_geometry(g):
    """Repair invalid polygons (self-intersections from simplification) and keep only the polygonal parts."""
    if g is None or g.is_empty or g.geom_type == "Point" or g.is_valid:
        return g
    g = shapely.make_valid(g)
    if g.geom_type == "GeometryCollection":
        polys = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
        g = MultiPolygon([q for p in polys for q in getattr(p, "geoms", [p])])
    return g


def finalize(gdf):
    """Repair geometry, fill derived license flags, coerce types, and return columns in schema order."""
    gdf["geometry"] = gdf.geometry.map(clean_geometry)
    lic = gdf["license_id"].map(lambda l: LICENSES.get(l, (None, None)))
    gdf["allows_commercial"] = lic.str[0]
    gdf["share_alike"] = lic.str[1]
    if "area_ha" not in gdf or gdf["area_ha"].isna().all():
        gdf["area_ha"] = area_ha(gdf)
    for c in RECORD_COLUMNS:
        if c not in gdf:
            gdf[c] = None
    gdf["time_start"] = pd.to_datetime(gdf["time_start"])
    gdf["time_end"] = pd.to_datetime(gdf["time_end"])
    gdf["attrs"] = gdf["attrs"].map(lambda a: a if isinstance(a, str) else json.dumps(a, default=str))
    return gpd.GeoDataFrame(gdf[RECORD_COLUMNS], geometry="geometry", crs=4326)


def write_records(gdf, source_id):
    RECORDS.mkdir(parents=True, exist_ok=True)
    out = RECORDS / f"{source_id}.parquet"
    gdf.to_parquet(out)
    return out


def load_records():
    parts = [gpd.read_parquet(p) for p in sorted(RECORDS.glob("*.parquet"))]
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
