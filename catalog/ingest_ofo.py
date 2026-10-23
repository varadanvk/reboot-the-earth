"""OFO drone missions + ground plots -> unified records (real data).

Usage: uv run python -m catalog.ingest_ofo

Reads data/ofo/*.gpkg (Zenodo 23402904) and writes:
  data/catalog/records/ofo.parquet     one record per mission and per plot
  data/catalog/relations.parquet       plot -covered_by-> mission, with overlap and time gap
"""

import json

import geopandas as gpd
import numpy as np
import pandas as pd

from catalog.schema import DATA, finalize, normalize_license, write_records

OFO = DATA / "ofo"
BUCKET = "https://js2.jetstream-cloud.org:8001/ofo-public/drone/missions_03"


def num(s):
    """First number in an OFO text cell ('90, 80' -> 90.0)."""
    return pd.to_numeric(s.fillna("").astype(str).str.split(",").str[0], errors="coerce")


def mission_assets(mid):
    p = f"{BUCKET}/{mid}/photogrammetry_03"
    return {
        "orthomosaic": f"{p}/full/{mid}_ortho-dsm-ptcloud.tif",
        "chm": f"{p}/full/{mid}_chm-ptcloud.tif",
        "dtm": f"{p}/full/{mid}_dtm-ptcloud.tif",
        "point_cloud": f"{p}/full/{mid}_points.copc.laz",
        "treetops": f"{p}/itd_0001/{mid}_treetops.gpkg",
        "report": f"{p}/full/{mid}_report.pdf",
        "thumbnail": f"{p}/thumbnails/{mid}_ortho-dsm-ptcloud.png",
        "chm_thumbnail": f"{p}/thumbnails/{mid}_chm-ptcloud.png",
        "photo_example": f"{BUCKET}/{mid}/images/examples/thumbnails/example_1.JPG",
    }


def site_ids(gdf, key):
    """Union-find over footprints that overlap >50% (of the smaller) within the same `key` group."""
    g = gdf.to_crs(3310)
    parent = list(range(len(g)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pairs = gpd.sjoin(g[[key, "geometry"]], g[[key, "geometry"]], predicate="intersects")
    pairs = pairs[(pairs.index < pairs.index_right) & (pairs[f"{key}_left"] == pairs[f"{key}_right"])]
    area = g.area
    for i, j in zip(pairs.index, pairs.index_right):
        inter = g.geometry.iloc[i].intersection(g.geometry.iloc[j]).area
        if inter > 0.5 * min(area.iloc[i], area.iloc[j]):
            parent[find(i)] = find(j)
    return [find(i) for i in range(len(g))]


def missions():
    m = gpd.read_file(OFO / "ofo_drone-missions.gpkg").reset_index(drop=True)
    pitch = num(m["camera_pitch_derived"])
    oblique = (m["smart_oblique_derived"] == True) | (pitch > 15)  # noqa: E712
    sev = m["anomaly_severity"].fillna("").astype(str).str.split(";").map(
        lambda v: max((float(x) for x in v if x.strip() not in ("", "nan", "None")), default=0))
    fidelity = num(m["agl_fidelity"])
    density = num(m["image_density_derived"])
    q = 1.0 - sev.map({0: 0, 1: 0.15, 2: 0.4, 2.5: 0.55, 3: 0.7}).fillna(0.4)
    q -= np.where(fidelity < 50, 0.2, 0)
    q *= np.clip(np.log10(density.fillna(10)) / np.log10(200), 0.5, 1.0)

    nadir_caps = ["tree_location", "canopy_height", "crown_delineation", "terrain", "rgb_ortho", "point_cloud_3d"]
    start = pd.to_datetime(m["earliest_date_derived"], errors="coerce").fillna(
        pd.to_datetime(m["date"].astype(str).str[:10], errors="coerce"))
    end = pd.to_datetime(m["latest_datetime_local_derived"].astype(str).str[:10], errors="coerce").fillna(start)
    agl = num(m["agl_mean"]).fillna(num(m["altitude_agl_nominal"]))
    sites = site_ids(m, "project_name")

    keep_typed = {"geometry", "mission_id", "license", "contributor_names", "withhold_from_training"}
    r = gpd.GeoDataFrame({
        "record_id": "ofo.drone_mission:" + m["mission_id"],
        "collection_id": "ofo.drone_mission",
        "source_id": "ofo",
        "native_id": m["mission_id"],
        "title": "Drone mission " + m["mission_id"] + " (" + m["project_name"] + ")",
        "geometry": m.geometry,
        "area_ha": num(m["area_derived"]),
        "position_uncert_m": np.where(num(m["percent_images_rtk_derived"]) > 90, 2.0, 5.0),
        "site_id": [f"ofo.mission_site:{s}" for s in sites],
        "time_start": start,
        "time_end": end,
        "time_precision": "day",
        "time_approx": False,
        "data_kind": "drone_imagery",
        "capabilities": [["point_cloud_3d"] if o else nadir_caps for o in oblique],
        "spatial_res_m": (agl / 3650).round(3),     # ~GSD of a 20 MP 1" sensor
        "n_observations": pd.to_numeric(m["image_count_derived"], errors="coerce"),
        "license_id": m["license"].map(normalize_license),
        "attribution": m["contributor_names"],
        "withhold_from_training": m["withhold_from_training"].astype(bool),
        "quality_score": q.clip(0, 1).round(3),
        "quality_flags": [
            [f for f, on in [("oblique", o), (f"anomaly_sev_{s:g}", s > 0), ("low_terrain_fidelity", fl < 50)] if on]
            for o, s, fl in zip(oblique, sev, fidelity.fillna(100))
        ],
        "simulated": False,
        "preview_url": [mission_assets(i)["thumbnail"] for i in m["mission_id"]],
        "attrs": [
            json.dumps({**{k: v for k, v in row.items() if k not in keep_typed and pd.notna(v)},
                        "assets": mission_assets(row["mission_id"])}, default=str)
            for row in m.drop(columns="geometry").to_dict("records")
        ],
    }, crs=m.crs)
    return finalize(r)


def parse_survey_date(v):
    """OFO stores YYYY / YYYYMM / YYYYMMDD as a float -> (start, end, precision)."""
    if pd.isna(v):
        return pd.NaT, pd.NaT, None
    s = str(int(v))
    if len(s) == 8:
        d = pd.Timestamp(s)
        return d, d, "day"
    if len(s) == 6:
        d = pd.Timestamp(s + "01")
        return d, d + pd.offsets.MonthEnd(0), "month"
    d = pd.Timestamp(s + "0101")
    return d, pd.Timestamp(s + "1231"), "year"


def plots():
    p = gpd.read_file(OFO / "ofo_ground-reference_plots.gpkg").reset_index(drop=True)
    t = gpd.read_file(OFO / "ofo_ground-reference_trees.gpkg", columns=[
        "plot_id", "species_code", "dbh", "height", "scorch_height", "percent_prefire_crown_green"],
        read_geometry=False)
    ts = t.groupby("plot_id").agg(
        n_trees=("plot_id", "size"),
        n_species=("species_code", "nunique"),
        dbh_frac=("dbh", lambda s: s.notna().mean()),
        fire_frac=("scorch_height", lambda s: s.notna().mean()),
    )
    p = p.join(ts, on="plot_id")

    dates = p["survey_date"].map(parse_survey_date)
    caps = []
    for _, row in p.iterrows():
        c = ["tree_location", "species", "live_dead"]
        if row["dbh_frac"] > 0.5:
            c.append("dbh")
        if row["height_measured"] == 1:
            c.append("tree_height")
        if row["includes_damage"]:
            c.append("damage")
        if row["fire_frac"] > 0.1:
            c.append("fire_effects")
        caps.append(c)

    precision = dates.str[2]
    q = (1.0 - np.where(p["num_ohvis_trees_excluded"].notna(), 0.2, 0)
         - np.where(precision == "year", 0.1, 0)
         + np.where(p["height_measured"] == 1, 0.1, 0)
         - np.where(p["notes"].notna(), 0.05, 0))

    keep_typed = {"geometry", "plot_id", "license_short", "investigator_names", "withhold_from_training"}
    r = gpd.GeoDataFrame({
        "record_id": "ofo.ground_plot:" + p["plot_id"],
        "collection_id": "ofo.ground_plot",
        "source_id": "ofo",
        "native_id": p["plot_id"],
        "title": "Ground plot " + p["plot_id"] + " (" + p["project_name"] + ")",
        "geometry": p.geometry,
        "area_ha": p["plot_area_ha"],
        "position_uncert_m": 10.0,
        "site_id": "ofo.plot_site:" + p["hyperplot_id"].fillna(p["plot_id"]),
        "time_start": dates.str[0],
        "time_end": dates.str[1],
        "time_precision": precision,
        "time_approx": p["survey_date_approx"].astype(bool),
        "data_kind": "field_plot",
        "capabilities": caps,
        "min_tree_dbh_cm": p["min_dbh_live"].fillna(p["min_dbh"]),
        "min_tree_ht_m": p["min_ht"],
        "n_observations": p["n_trees"].fillna(0).astype(int),
        "license_id": p["license_short"].map(normalize_license),
        "attribution": p["investigator_names"],
        "withhold_from_training": p["withhold_from_training"].astype(bool),
        "quality_score": np.clip(q, 0, 1).round(3),
        "quality_flags": [
            [f for f, on in [("incomplete_ohvis", pd.notna(x)), ("year_only_date", pr == "year"), ("has_notes", pd.notna(n))] if on]
            for x, pr, n in zip(p["num_ohvis_trees_excluded"], precision, p["notes"])
        ],
        "simulated": False,
        "attrs": [
            json.dumps({k: v for k, v in row.items() if k not in keep_typed and pd.notna(v)}, default=str)
            for row in p.drop(columns="geometry").to_dict("records")
        ],
    }, crs=p.crs)
    return finalize(r)


def relations(recs):
    """plot covered_by mission: overlap = share of plot inside mission; gap = |mission - survey| in days."""
    g = recs.to_crs(3310)
    pl, mi = g[g.data_kind == "field_plot"], g[g.data_kind == "drone_imagery"]
    j = gpd.sjoin(pl[["record_id", "time_start", "geometry"]], mi[["record_id", "time_start", "geometry"]],
                  predicate="intersects", lsuffix="plot", rsuffix="mission")
    mgeom = mi.set_index("record_id").geometry
    j["overlap_frac"] = [
        (geom.intersection(mgeom[m]).area / geom.area) for geom, m in zip(j.geometry, j["record_id_mission"])
    ]
    return pd.DataFrame({
        "from_record": j["record_id_plot"].values,
        "to_record": j["record_id_mission"].values,
        "rel": "covered_by",
        "overlap_frac": j["overlap_frac"].round(3).values,
        "distance_m": 0.0,
        "time_gap_days": (j["time_start_mission"] - j["time_start_plot"]).dt.days.values,
    })


def main():
    recs = pd.concat([missions(), plots()], ignore_index=True)
    recs = gpd.GeoDataFrame(recs, crs=4326)
    print(f"wrote {write_records(recs, 'ofo')}: {len(recs)} records")
    print(recs.groupby("data_kind").agg(n=("record_id", "size"), area_ha=("area_ha", "median"),
                                        q=("quality_score", "mean"), start=("time_start", "min"),
                                        end=("time_start", "max")))
    rel = relations(recs)
    rel.to_parquet(DATA / "catalog" / "relations.parquet")
    print(f"relations: {len(rel)} covered_by; median |gap| {rel.time_gap_days.abs().median():.0f} d;"
          f" plots with mission flown AFTER survey: {(rel.time_gap_days > 0).groupby(rel.from_record).any().sum()}")


if __name__ == "__main__":
    main()
