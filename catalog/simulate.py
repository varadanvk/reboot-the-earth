"""Source adapters that don't need a full download.

Real: FIA (CA_PLOT.csv, fuzzed coords) and 3DEP lidar work units (WESM, 203 CA units).
Simulated: FRAP fire perimeters, ITS treatments, GEDI passes.

Usage: uv run python -m catalog.simulate [--seed 7]

Simulated sources reproduce the real schemas and distributions documented in docs/sources/*.md
(field names, year curves, size buckets, category mixes) so swapping in the real pull is a
mapper change, not a schema change. Locations are drawn from real forested FIA plot locations
(a statistically sampled map of where California's forest is), so simulated fires, treatments,
lidar and GEDI land where they plausibly would.

Writes data/catalog/records/{fia,3dep,frap_sim,its_sim,gedi_sim}.parquet.
"""

import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from catalog.schema import DATA, finalize, write_records

FIA = DATA / "shapes" / "fia" / "CA_PLOT.csv"
WESM = DATA / "shapes" / "3dep" / "wesm_lpc_ca_state_all.geojson"
ALBERS = 3310


# ---------- FIA (real plot table, fuzzed coordinates) ----------

def fia_plots():
    p = pd.read_csv(FIA, dtype={"CN": str, "PREV_PLT_CN": str}, low_memory=False)
    p = p[p["LAT"].notna() & (p["KINDCD"] != 0)]           # drop 1994 periodic design + blank coords
    p["pid"] = p[["STATECD", "UNITCD", "COUNTYCD", "PLOT"]].astype(int).astype(str).agg("-".join, axis=1)
    p["date"] = pd.to_datetime(dict(year=p.MEASYEAR, month=p.MEASMON.fillna(7), day=p.MEASDAY.fillna(1)), errors="coerce")
    g = p.sort_values("date").groupby("pid")
    plots = g.last()
    plots["first_date"] = g["date"].first()
    plots["n_visits"] = g.size()
    plots["ever_forest"] = g["PLOT_STATUS_CD"].apply(lambda s: (s == 1).any())
    return plots.reset_index()


def fia_records(plots):
    f = plots[plots["ever_forest"]]
    caps = ["species", "dbh", "tree_height", "live_dead", "damage", "biomass", "disturbance_history", "treatment_history"]
    r = gpd.GeoDataFrame({
        "record_id": "fia.plot:" + f["pid"],
        "collection_id": "fia.plot", "source_id": "fia", "native_id": f["pid"],
        "title": "FIA plot " + f["pid"],
        "geometry": gpd.points_from_xy(f["LON"], f["LAT"]),
        "area_ha": 0.67,                       # 4 macroplots of 58.9 ft radius
        "position_uncert_m": 1609.0,           # public coords fuzzed up to ~1 mile
        "site_id": "fia.plot:" + f["pid"],
        "time_start": f["first_date"], "time_end": f["date"], "time_precision": "day", "time_approx": False,
        "data_kind": "field_plot", "capabilities": [caps] * len(f),
        "min_tree_dbh_cm": 2.54, "n_observations": None,
        "license_id": "PD", "attribution": "USDA Forest Service, Forest Inventory and Analysis",
        "withhold_from_training": False,
        "quality_score": np.where(f["PLOT_STATUS_CD"] == 1, 0.8, 0.5),
        "quality_flags": [["fuzzed_location"] + (["latest_visit_nonforest"] if s != 1 else []) for s in f["PLOT_STATUS_CD"]],
        "simulated": False,
        "attrs": [json.dumps({"CN": cn, "INVYR": int(iy), "n_visits": int(nv), "PLOT_STATUS_CD": int(st),
                              "ELEV_ft": None if pd.isna(el) else int(el), "DESIGNCD": int(dc)})
                  for cn, iy, nv, st, el, dc in zip(f["CN"], f["INVYR"], f["n_visits"], f["PLOT_STATUS_CD"],
                                                    f["ELEV"], f["DESIGNCD"])],
    }, crs=4269).to_crs(4326)
    return finalize(r)


# ---------- shared helpers for simulation ----------

class Sampler:
    """Draw plausible locations from real FIA plot positions (forest-weighted), in CA Albers metres."""

    def __init__(self, plots, rng):
        pts = gpd.GeoSeries(gpd.points_from_xy(plots["LON"], plots["LAT"]), crs=4269).to_crs(ALBERS)
        self.xy = np.c_[pts.x, pts.y]
        self.forest = (plots["PLOT_STATUS_CD"] == 1).to_numpy()
        self.lat = plots["LAT"].to_numpy()
        self.rng = rng
        self.land = unary_union(pts.buffer(6000).values).simplify(2000)

    def draw(self, n, forest_weight=0.85, jitter=3000, lat_range=None):
        w = np.where(self.forest, forest_weight, 1 - forest_weight)
        if lat_range:
            w = w * ((self.lat >= lat_range[0]) & (self.lat < lat_range[1]))
        idx = self.rng.choice(len(self.xy), size=n, p=w / w.sum())
        return self.xy[idx] + self.rng.normal(0, jitter, size=(n, 2))


def blob(rng, x, y, area_m2, elong=(1.0, 2.5), n=28, rough=0.35):
    """Irregular fire-like polygon of a given area."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = np.ones(n)
    for k in range(2, 6):
        r += rough / k * np.sin(k * t + rng.uniform(0, 2 * np.pi))
    poly = Polygon(np.c_[np.cos(t) * r, np.sin(t) * r])
    poly = affinity.scale(poly, rng.uniform(*elong), 1.0)
    poly = affinity.rotate(poly, rng.uniform(0, 180))
    poly = affinity.scale(poly, *(np.sqrt(area_m2 / poly.area),) * 2)
    return affinity.translate(poly, x, y)


def unit_block(rng, x, y, area_m2):
    """Blocky harvest/treatment-unit polygon: a rotated rectangle with a notch."""
    a = rng.uniform(1, 3)
    w = np.sqrt(area_m2 / a)
    poly = box(-w * a / 2, -w / 2, w * a / 2, w / 2)
    if rng.random() < 0.5:
        poly = poly.difference(box(w * a / 2 * rng.uniform(0, .6), 0, w * a, w))
    poly = affinity.scale(poly, *(np.sqrt(area_m2 / poly.area),) * 2)
    return affinity.translate(affinity.rotate(poly, rng.uniform(0, 180)), x, y)


def epoch_ms(ts):
    return None if pd.isna(ts) else int(pd.Timestamp(ts).value // 1_000_000)


def sample_bucketed(rng, n, buckets, weights):
    """Log-uniform within buckets chosen by weight (matches the real bucket histograms)."""
    w = np.array(weights, float)
    b = rng.choice(len(buckets), size=n, p=w / w.sum())
    lo = np.log([buckets[i][0] for i in b])
    hi = np.log([buckets[i][1] for i in b])
    return np.exp(rng.uniform(lo, hi))


# ---------- FRAP fire perimeters (simulated, schema of California_Historic_Fire_Perimeters/0) ----------

FRAP_DECADES = {1950: 1819, 1960: 1276, 1970: 1879, 1980: 2206, 1990: 1992, 2000: 2905, 2010: 3429, 2020: 2558}
FRAP_AGENCY = {"USF": 9761, "CDF": 7474, "CCO": 3643, "NPS": 1052, "BLM": 789, "LRA": 282, "DOD": 173}
FRAP_CAUSE = {14: 10514, 1: 3648, 9: 3533, 2: 1455, 7: 1018, 5: 806, 10: 639, 11: 506}
FRAP_BIG_YEARS = {2020: 4.18e6, 2021: 2.51e6, 2018: 1.58e6, 2017: 1.43e6, 2024: 1.01e6, 2008: 1.4e6, 2007: 1.0e6}
NAMES = ["PINE", "CEDAR", "RIDGE", "CREEK", "OAK", "BEAR", "EAGLE", "CANYON", "SUMMIT", "MILL", "FORK", "LAKE",
         "COYOTE", "MEADOW", "ROCK", "SPRING", "FLAT", "BUTTE", "HOLLOW", "PEAK", "VALLEY", "BALD", "SADDLE"]


def pick(rng, d, n):
    k = list(d)
    w = np.array(list(d.values()), float)
    return rng.choice(k, size=n, p=w / w.sum())


def frap(sampler, rng, scale=0.25):
    """~25% of real fires ≥100 ac would be ~3.2k; we keep fires ≥100 ac, decade counts scaled."""
    rows = []
    for dec, n in FRAP_DECADES.items():
        n_big = int(n * scale * 0.65)                                  # ~65% of fires are ≥100 ac
        years = rng.integers(dec, min(dec + 10, 2026), size=n_big)
        acres = sample_bucketed(rng, n_big, [(100, 1e3), (1e3, 1e4), (1e4, 1e5), (1e5, 1e6)], [8677, 3426, 731, 47])
        for y, ac in zip(years, acres):
            if y in FRAP_BIG_YEARS and rng.random() < 0.15:
                ac *= rng.uniform(3, 15)                              # megafire years
            rows.append((int(y), float(min(ac, 1.03e6))))
    df = pd.DataFrame(rows, columns=["YEAR_", "GIS_ACRES"])
    n = len(df)
    xy = sampler.draw(n, forest_weight=0.7, jitter=8000)
    geoms = [blob(rng, x, y, ac * 4046.86).intersection(sampler.land) for (x, y), ac in zip(xy, df["GIS_ACRES"])]
    alarm = pd.to_datetime(df["YEAR_"].astype(str) + "-01-01") + pd.to_timedelta(rng.normal(215, 35, n).clip(90, 340), "D")
    cont = alarm + pd.to_timedelta(np.ceil(np.log10(df["GIS_ACRES"]) ** 2 * rng.uniform(1, 3, n)), "D")
    df["ALARM_DATE"] = [epoch_ms(a) if rng.random() > 0.2 else None for a in alarm]
    df["CONT_DATE"] = [epoch_ms(c) if rng.random() > 0.45 else None for c in cont]
    df["AGENCY"] = pick(rng, FRAP_AGENCY, n)
    df["CAUSE"] = pick(rng, FRAP_CAUSE, n)
    df["C_METHOD"] = np.where(df["YEAR_"] < 2000, 8, pick(rng, {1: 4405, 3: 1500, 7: 1148, 6: 1227, 8: 2000}, n))
    df["OBJECTIVE"] = np.where(rng.random(n) < 0.012, 2, 1)
    df["FIRE_NAME"] = [f"{rng.choice(NAMES)}" + (f" {rng.choice(NAMES)}" if rng.random() < .3 else "") for _ in range(n)]
    df["INC_NUM"] = [f"{rng.integers(0, 10**8):08d}" for _ in range(n)]
    df["STATE"] = "CA"
    df["OBJECTID"] = np.arange(1, n + 1)

    alarm_dt = pd.to_datetime(df["ALARM_DATE"], unit="ms")
    cont_dt = pd.to_datetime(df["CONT_DATE"], unit="ms")
    r = gpd.GeoDataFrame({
        "record_id": "frap.perimeter:sim" + df["OBJECTID"].astype(str),
        "collection_id": "frap.perimeter", "source_id": "frap_sim", "native_id": df["OBJECTID"].astype(str),
        "title": df["FIRE_NAME"].str.title() + " Fire (" + df["YEAR_"].astype(str) + ")",
        "geometry": geoms, "area_ha": None, "position_uncert_m": np.where(df["C_METHOD"].isin([1, 2]), 15, 150),
        "time_start": alarm_dt.fillna(pd.to_datetime(df["YEAR_"].astype(str) + "-01-01")),
        "time_end": cont_dt.fillna(alarm_dt).fillna(pd.to_datetime(df["YEAR_"].astype(str) + "-12-31")),
        "time_precision": np.where(df["ALARM_DATE"].isna(), "year", "day"), "time_approx": df["ALARM_DATE"].isna(),
        "data_kind": "fire_perimeter", "capabilities": [["disturbance_history"]] * n,
        "license_id": "PD", "attribution": "CAL FIRE FRAP, " + df["AGENCY"],
        "withhold_from_training": False,
        "quality_score": df["C_METHOD"].map({1: 0.95, 2: 0.9, 3: 0.85, 7: 0.75, 6: 0.55, 8: 0.5}).fillna(0.5),
        "quality_flags": [["mapping_method_unknown"] if m == 8 else [] for m in df["C_METHOD"]],
        "simulated": True,
        "attrs": df.drop(columns=[]).to_dict("records"),
    }, crs=ALBERS)
    r = r[~r.geometry.is_empty]
    return finalize(r.to_crs(4326))


# ---------- ITS treatments (simulated, schema of ITSV2_1_Polygons_gdb/0) ----------

ITS_SEQUENCES = {   # activity stacks that land on the same ground, with real-ish category weights
    ("THIN_MECH", "PILING", "PILE_BURN"): 30,
    ("COMM_THIN", "PILE_BURN"): 12,
    ("CLEARCUT", "SITE_PREP", "TREE_PLNTING", "TREE_RELEASE_WEED"): 18,
    ("BROADCAST_BURN",): 14,
    ("MASTICATION",): 10,
    ("TREE_PLNTING", "TREE_RELEASE_WEED"): 10,
    ("INV_PLANT_REMOVAL",): 6,
}
ITS_CAT = {"THIN_MECH": "MECH_HFR", "PILING": "MECH_HFR", "PILE_BURN": "PRESCRB_FIRE", "COMM_THIN": "TIMB_HARV",
           "CLEARCUT": "TIMB_HARV", "SITE_PREP": "NOT_DEFINED", "TREE_PLNTING": "TREE_PLNTING",
           "TREE_RELEASE_WEED": "TREE_PLNTING", "BROADCAST_BURN": "PRESCRB_FIRE", "MASTICATION": "MECH_HFR",
           "INV_PLANT_REMOVAL": "NOT_DEFINED"}
ITS_SOURCE = {"usfs_treatments": 378638, "CNRA": 43130, "Industrial Timber": 3158, "BLM": 1220, "nps_flat_fuelstreatments": 831}
ITS_AGENCY = {"usfs_treatments": "USDA", "CNRA": "CNRA", "Industrial Timber": "TIMBER", "BLM": "DOI",
              "nps_flat_fuelstreatments": "NPS"}


def its_year_weights():
    y = np.arange(1980, 2027)
    w = np.interp(y, [1980, 1990, 2000, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
                  [8, 15, 7, 7, 10.6, 13, 16.2, 19, 18, 0.6])
    return y, w / w.sum()


def its(sampler, rng, n_treatments=4000):
    years, yw = its_year_weights()
    seqs = list(ITS_SEQUENCES)
    sw = np.array(list(ITS_SEQUENCES.values()), float)
    xy = sampler.draw(n_treatments, forest_weight=0.9, jitter=1500, lat_range=(34.5, 42.1))
    area_ac = sample_bucketed(rng, n_treatments, [(1, 10), (10, 100), (100, 1000), (1000, 5000)], [156, 207, 20, 1])
    rows, geoms = [], []
    oid = 0
    for i in range(n_treatments):
        seq = seqs[rng.choice(len(seqs), p=sw / sw.sum())]
        src = pick(rng, ITS_SOURCE, 1)[0]
        y0 = int(rng.choice(years, p=yw))
        geom = unit_block(rng, *xy[i], area_ac[i] * 4046.86)
        lat = gpd.GeoSeries([geom.centroid], crs=ALBERS).to_crs(4326).iloc[0].y
        region = "NORTH_COAST" if lat > 39.6 and xy[i][0] < -150000 else "SIERRA_NEVADA" if lat > 35.3 else "SOUTHERN_CA"
        y = y0
        for act in seq:
            oid += 1
            status = "COMPLETE" if y <= 2025 else rng.choice(["ACTIVE", "PLANNED"])
            q = float(area_ac[i] * rng.uniform(0.6, 1.0))
            rows.append({
                "objectid": oid, "source": src, "agency": ITS_AGENCY[src], "year": y, "year_txt": str(y),
                "activity_start": None if rng.random() < 0.89 else f"{y}-{rng.integers(5, 10):02d}-01",
                "activity_end": f"{y}-{rng.integers(6, 12):02d}-{rng.integers(1, 28):02d} 00:00:00+00:00",
                "activity_status": status, "activity_cat": ITS_CAT[act], "activity_description": act,
                "activity_quantity": round(q, 2), "activity_uom": "AC", "treatment_area": round(float(area_ac[i]), 2),
                "broad_vegetation_type": "FOREST" if rng.random() < 0.8 else "SHRB_CHAP",
                "primary_ownership_group": "FEDERAL" if src != "Industrial Timber" and rng.random() < 0.8 else "PRIVATE_INDUSTRY",
                "region": region, "in_wui": "WUI_AUTO_POP" if rng.random() < 0.28 else "NON-WUI_AUTO_POP",
                "counts_to_mas": "YES" if ITS_CAT[act] in ("MECH_HFR", "PRESCRB_FIRE", "TIMB_HARV") else "NO",
                "trmtid_user": f"SIM-T{i:05d}", "project_name": f"{rng.choice(NAMES).title()} {rng.choice(['Fuels', 'Forest Health', 'Restoration', 'Timber Sale', 'Rx'])} Project",
            })
            geoms.append(geom)
            y += int(rng.integers(0, 3))
    df = pd.DataFrame(rows)
    end = pd.to_datetime(df["activity_end"].str[:10])
    r = gpd.GeoDataFrame({
        "record_id": "its.activity:sim" + df["objectid"].astype(str),
        "collection_id": "its.activity", "source_id": "its_sim", "native_id": df["objectid"].astype(str),
        "title": df["activity_description"].str.replace("_", " ").str.title() + " – " + df["project_name"],
        "geometry": geoms, "position_uncert_m": 30.0, "site_id": "its.treatment:" + df["trmtid_user"],
        "time_start": pd.to_datetime(df["activity_start"]).fillna(end), "time_end": end,
        "time_precision": "day", "time_approx": df["activity_start"].isna(),
        "data_kind": "fuel_treatment", "capabilities": [["treatment_history"]] * len(df),
        "n_observations": None, "license_id": "PD",
        "attribution": "CA Wildfire & Forest Resilience Task Force ITS (" + df["source"] + ")",
        "withhold_from_training": False,
        "quality_score": np.where(df["activity_status"] == "COMPLETE", 0.8, 0.3),
        "quality_flags": [[] if s == "COMPLETE" else ["not_completed"] for s in df["activity_status"]],
        "simulated": True, "attrs": df.to_dict("records"),
    }, crs=ALBERS)
    return finalize(r.to_crs(4326))


# ---------- 3DEP lidar work units (real WESM footprints, simplified to 0.002°) ----------

QL_SCORE = {"QL 0": 1.0, "QL 1": 0.9, "QL 2": 0.75, "QL 3": 0.6, "Other": 0.5}


def threedep():
    w = gpd.read_file(WESM)
    start = pd.to_datetime(w["collect_start"], unit="ms")
    end = pd.to_datetime(w["collect_end"], unit="ms")
    ql = w["ql"].fillna("Other").str.replace("PRELIMINARY", "Other")
    q = ql.map(QL_SCORE).fillna(0.5) - np.where(w["lpc_category"] == "Does not meet", 0.2, 0)
    keep = ["workunit", "workunit_id", "project", "ql", "spec", "p_method", "dem_gsd_meters", "lpc_category",
            "lpc_pub_date", "horiz_crs", "vert_crs", "lpc_link", "metadata_link"]
    r = gpd.GeoDataFrame({
        "record_id": "3dep.workunit:" + w["workunit_id"].astype(str),
        "collection_id": "3dep.workunit", "source_id": "3dep", "native_id": w["workunit_id"].astype(str),
        "title": w["workunit"].str.replace("_", " ") + " lidar",
        "geometry": w.geometry, "position_uncert_m": 1.0, "site_id": "3dep.project:" + w["project"],
        "time_start": start, "time_end": end, "time_precision": "day", "time_approx": False,
        "data_kind": "airborne_lidar",
        "capabilities": [["canopy_height", "terrain", "point_cloud_3d", "tree_height"]] * len(w),
        "spatial_res_m": w["dem_gsd_meters"],
        "license_id": "PD", "attribution": "U.S. Geological Survey 3D Elevation Program",
        "withhold_from_training": False, "quality_score": q.clip(0, 1),
        "quality_flags": [[f for f, on in [(f"ql_{v.replace(' ', '').lower()}", True),
                                            ("does_not_meet_spec", c == "Does not meet")] if on]
                          for v, c in zip(ql, w["lpc_category"])],
        "simulated": False, "preview_url": None,
        "attrs": w[keep].to_dict("records"),
    }, crs=w.crs)
    return finalize(r.to_crs(4326))


# ---------- GEDI passes (simulated; real track geometry and per-year totals) ----------

GEDI_TRACK_KM = {2019: 143595, 2020: 223068, 2021: 191878, 2022: 204697, 2023: 38953, 2024: 125117, 2025: 131979}
SHOT_HA = np.pi * 12.5 ** 2 / 1e4          # 25 m footprint


def gedi(sampler, rng, scale=0.25):
    """One record per pass segment over CA: a 4.2 km swath (8 beams, 600 m apart) on a 51.6°-inclination
    ground track (heading ≈ ±51° from north at CA latitudes). `scale` thins passes to keep the prototype light."""
    land = sampler.land
    minx, miny, maxx, maxy = land.bounds
    rows, geoms = [], []
    i = 0
    for year, km in GEDI_TRACK_KM.items():
        done = 0.0
        while done < km * scale:
            heading = np.deg2rad(rng.choice([51, 129]) + rng.normal(0, 2))  # ascending NE / descending SE
            cx, cy = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
            d = np.array([np.sin(heading), np.cos(heading)]) * 1.2e6
            line = LineString([(cx - d[0], cy - d[1]), (cx + d[0], cy + d[1])]).intersection(land)
            if line.is_empty or line.length < 20000:
                continue
            length_km = line.length / 1000
            done += length_km
            i += 1
            when = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(rng.integers(0, 365 if year != 2023 else 75)))
            pass_rate = rng.uniform(0.25, 0.55)                          # cloud, sensitivity < 0.95, degrade
            shots = int(length_km * 8 * 16.7)
            good = int(shots * pass_rate)
            geoms.append(line.buffer(2100, cap_style="flat"))
            orbit = 2000 + i * 7
            rows.append({
                "granule": f"GEDI02_A_{when:%Y%j}{rng.integers(0, 235959):06d}_O{orbit:05d}_0{rng.integers(1, 5)}_T{rng.integers(0, 4471):05d}_02_005_02_V003",
                "orbit": orbit, "date": when, "length_km": round(length_km, 1), "n_shots": shots, "n_good": good,
                "quality_pass_rate": round(pass_rate, 3), "direction": "ascending" if np.rad2deg(heading) < 90 else "descending",
            })
    df = pd.DataFrame(rows)
    r = gpd.GeoDataFrame({
        "record_id": "gedi.pass:sim" + df["orbit"].astype(str),
        "collection_id": "gedi.l2a_pass", "source_id": "gedi_sim", "native_id": df["granule"],
        "title": "GEDI pass O" + df["orbit"].astype(str) + " (" + df["direction"] + ")",
        "geometry": geoms, "area_ha": df["n_good"] * SHOT_HA, "position_uncert_m": 10.0,
        "time_start": df["date"], "time_end": df["date"], "time_precision": "day", "time_approx": False,
        "data_kind": "spaceborne_lidar", "capabilities": [["canopy_height", "biomass"]] * len(df),
        "spatial_res_m": 25.0, "n_observations": df["n_good"],
        "license_id": "PD", "attribution": "NASA GEDI (Dubayah et al.), LP DAAC / ORNL DAAC",
        "withhold_from_training": False, "quality_score": (df["quality_pass_rate"] / 0.55).clip(0, 1),
        "quality_flags": [["sparse_sampling"]] * len(df), "simulated": True,
        "attrs": df.assign(date=df["date"].astype(str)).to_dict("records"),
    }, crs=ALBERS)
    return finalize(r.to_crs(4326))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    plots = fia_plots()
    sampler = Sampler(plots, rng)
    for name, fn in [("fia", lambda: fia_records(plots)), ("3dep", threedep),
                     ("frap_sim", lambda: frap(sampler, rng)), ("its_sim", lambda: its(sampler, rng)),
                     ("gedi_sim", lambda: gedi(sampler, rng))]:
        recs = fn()
        print(f"{name}: {len(recs)} records -> {write_records(recs, name)}")
        print(f"   years {recs.time_start.dt.year.min()}–{recs.time_start.dt.year.max()},"
              f" median area {recs.area_ha.median():.1f} ha, total area {recs.area_ha.sum() / 1e6:.2f} Mha")


if __name__ == "__main__":
    main()
