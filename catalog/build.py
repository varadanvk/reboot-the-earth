"""Records -> H3 coverage grid + web exports.

Usage: uv run python -m catalog.build

Reads every data/catalog/records/*.parquet and writes to web/data/:
  coverage_r{5,6}.json       per (H3 cell, data_kind) aggregates, as flat rows (see COVERAGE_FIELDS)
  coverage_r{7,8}/{tile}.json  same, split by TILE_RES parent cell so the browser loads only the viewport
  records_{data_kind}.geojson  simplified footprints + the properties the detail panel needs
  nearby.json                record_id -> [[other_record_id, rel, distance_m, overlap_frac], ...]

Footprints are rasterized at BASE_RES (~74 ha cells). A footprint much smaller than a cell
contributes area/cell_area to its centroid cell; a fuzzed location (position_uncert_m larger
than a cell) is spread evenly over the cells it could be in. Coarser resolutions are rollups.
"""

import json
import math

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from catalog.schema import CAPABILITIES, DATA, DATA_KINDS, WEB_DATA, load_records

BASE_RES = 8
OUT_RES = [5, 6, 7, 8]
TILED_RES = {7, 8}
TILE_RES = 3
NEARBY_M = 2000
COVERAGE_FIELDS = ["h3", "kind", "n", "frac_pm", "earliest", "latest", "q_pct", "nobs", "open_pct", "caps", "sim"]


def cells_for(geom, area_ha, uncert_m, envelope_ha):
    """[(cell, frac)] at BASE_RES for one footprint.

    area_ha is the area actually measured; envelope_ha the footprint polygon's area. They differ for
    sparse samplers (GEDI shots inside a swath), where each covered cell gets area/envelope coverage.
    """
    cell_ha = h3.average_hexagon_area(BASE_RES, "km^2") * 100
    edge_m = h3.average_hexagon_edge_length(BASE_RES, "m")
    c = geom.centroid
    center = h3.latlng_to_cell(c.y, c.x, BASE_RES)
    if uncert_m and uncert_m > edge_m:
        disk = h3.grid_disk(center, math.ceil(uncert_m / (edge_m * 1.5)))
        f = min(1.0, area_ha / cell_ha) / len(disk)
        return [(h, f) for h in disk]
    if area_ha < 2 * cell_ha:
        return [(center, min(1.0, area_ha / cell_ha))]
    density = min(1.0, area_ha / envelope_ha) if envelope_ha else 1.0
    cells = h3.geo_to_cells(geom, BASE_RES)
    return [(h, density) for h in cells] or [(center, density)]


def explode(recs):
    rows = []
    envelope = recs.to_crs(3310).area / 1e4
    for r, env in zip(recs.itertuples(), envelope):
        for h, f in cells_for(r.geometry, r.area_ha, r.position_uncert_m, env):
            rows.append((h, r.Index, f))
    return pd.DataFrame(rows, columns=["cell", "rec", "frac"])


def coverage(recs, pairs, res):
    p = pairs.copy()
    if res != BASE_RES:
        p["cell"] = [h3.cell_to_parent(h, res) for h in p["cell"]]
    p = p.groupby(["cell", "rec"], as_index=False)["frac"].sum()
    meta = recs[["data_kind", "quality_score", "n_observations", "allows_commercial", "simulated", "capmask"]].copy()
    meta["y0"] = recs["time_start"].dt.year
    meta["y1"] = recs["time_end"].dt.year.fillna(meta["y0"])
    meta["kind"] = meta["data_kind"].map(DATA_KINDS.index)
    meta["open"] = meta["allows_commercial"].fillna(False).astype(float)
    meta["nobs"] = meta["n_observations"].fillna(0)
    p = p.join(meta[["kind", "quality_score", "nobs", "open", "simulated", "capmask", "y0", "y1"]], on="rec")
    mask = p["capmask"].to_numpy(dtype="int64")
    bits = {f"b{i}": (mask >> i) & 1 for i in range(len(CAPABILITIES))}
    p = p.assign(**bits)
    g = p.groupby(["cell", "kind"], sort=False).agg(
        n=("rec", "size"), frac=("frac", "sum"), y0=("y0", "min"), y1=("y1", "max"),
        q=("quality_score", "max"), nobs=("nobs", "sum"), open=("open", "mean"), sim=("simulated", "all"),
        **{k: (k, "max") for k in bits})
    caps = sum(g[f"b{i}"].to_numpy(dtype="int64") << i for i in range(len(CAPABILITIES)))
    scale = 7 ** (BASE_RES - res)
    out = pd.DataFrame({
        "h3": g.index.get_level_values(0), "kind": g.index.get_level_values(1), "n": g["n"].values,
        "frac_pm": (np.minimum(1.0, g["frac"].values / scale) * 1000).round().astype(int),
        "earliest": g["y0"].values, "latest": g["y1"].values,
        "q_pct": (g["q"].values * 100).round(), "nobs": g["nobs"].values.astype("int64"),
        "open_pct": (g["open"].values * 100).round().astype(int), "caps": caps, "sim": g["sim"].values.astype(int),
    })
    out = out.astype(object).where(out.notna(), None)
    return [[None if v is None else (int(v) if isinstance(v, (float, np.floating, np.integer)) else v) for v in row]
            for row in out.itertuples(index=False, name=None)]


def export_records(recs):
    keep = ["record_id", "title", "data_kind", "source_id", "collection_id", "license_id", "allows_commercial",
            "attribution", "quality_score", "quality_flags", "capabilities", "n_observations", "area_ha",
            "position_uncert_m", "withhold_from_training", "min_tree_dbh_cm", "min_tree_ht_m", "spatial_res_m",
            "simulated", "preview_url", "time_precision"]
    for kind, g in recs.groupby("data_kind"):
        g = g.copy()
        tol = 0.0001 if g["area_ha"].median() < 1000 else 0.002
        g["geometry"] = g.geometry.simplify(tol, preserve_topology=True)
        g["date"] = g["time_start"].dt.strftime("%Y-%m-%d")
        g["date_end"] = g["time_end"].dt.strftime("%Y-%m-%d")
        g["quality_flags"] = g["quality_flags"].map(lambda v: list(v) if v is not None else [])
        g["capabilities"] = g["capabilities"].map(lambda v: list(v) if v is not None else [])
        g["area_ha"] = g["area_ha"].round(2)
        out = g[keep + ["date", "date_end", "geometry"]]
        path = WEB_DATA / f"records_{kind}.geojson"
        path.write_text(out.to_json(drop_id=True, na="drop"))
        print(f"  {path.name}: {len(g)} features, {path.stat().st_size / 1e6:.1f} MB")


def nearby(recs):
    """Precomputed 'what else is here' for the detail panel: explicit relations + anything within NEARBY_M."""
    g = recs[["record_id", "geometry"]].to_crs(3310)
    j = gpd.sjoin(g, g.assign(geometry=g.buffer(NEARBY_M)), predicate="intersects")
    j = j[j["record_id_left"] != j["record_id_right"]]
    geom = g.set_index("record_id").geometry
    out = {}
    for a, b in zip(j["record_id_right"], j["record_id_left"]):
        ga, gb = geom[a], geom[b]
        d = ga.distance(gb)
        ov = ga.intersection(gb).area / ga.area if d == 0 and ga.area > 0 else 0
        out.setdefault(a, []).append([b, "overlaps" if ov > 0 else "near", round(d), round(ov, 3)])
    rel = DATA / "catalog" / "relations.parquet"
    if rel.exists():
        for r in pd.read_parquet(rel).itertuples():
            for a, b, name in [(r.from_record, r.to_record, "covered_by"), (r.to_record, r.from_record, "covers")]:
                lst = out.setdefault(a, [])
                lst[:] = [x for x in lst if x[0] != b]
                lst.append([b, name, 0, r.overlap_frac, int(r.time_gap_days) if pd.notna(r.time_gap_days) else None])
    for a in out:
        out[a] = sorted(out[a], key=lambda x: (x[2], -x[3]))[:40]
    return out


def main():
    recs = load_records().reset_index(drop=True)
    recs["capmask"] = recs["capabilities"].map(
        lambda cs: sum(1 << CAPABILITIES.index(c) for c in (cs if cs is not None else []) if c in CAPABILITIES))
    print(recs.groupby(["source_id", "data_kind"]).size().to_string())
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    pairs = explode(recs)
    print(f"{len(pairs)} (cell, record) pairs at res {BASE_RES}")
    for res in OUT_RES:
        rows = coverage(recs, pairs, res)
        head = {"res": res, "fields": COVERAGE_FIELDS, "kinds": DATA_KINDS, "caps": CAPABILITIES}
        if res not in TILED_RES:
            path = WEB_DATA / f"coverage_r{res}.json"
            path.write_text(json.dumps({**head, "rows": rows}, separators=(",", ":")))
            print(f"  {path.name}: {len(rows)} rows, {path.stat().st_size / 1e6:.1f} MB")
            continue
        tiles = {}
        for row in rows:
            tiles.setdefault(h3.cell_to_parent(row[0], TILE_RES), []).append(row)
        d = WEB_DATA / f"coverage_r{res}"
        d.mkdir(exist_ok=True)
        for old in d.glob("*.json"):
            old.unlink()
        for t, trows in tiles.items():
            (d / f"{t}.json").write_text(json.dumps({**head, "tile": t, "rows": trows}, separators=(",", ":")))
        size = sum(f.stat().st_size for f in d.glob("*.json")) / 1e6
        print(f"  {d.name}/: {len(rows)} rows in {len(tiles)} tiles, {size:.1f} MB total, "
              f"max tile {max(len(v) for v in tiles.values())} rows")

    export_records(recs)
    nb = nearby(recs)
    (WEB_DATA / "nearby.json").write_text(json.dumps(nb, separators=(",", ":")))
    print(f"  nearby.json: {len(nb)} records with neighbours")
    meta = {
        "sources": recs.groupby("source_id").agg(n=("record_id", "size"), simulated=("simulated", "all"))
                       .reset_index().to_dict("records"),
        "years": [int(recs["time_start"].dt.year.min()), int(recs["time_start"].dt.year.max())],
        "built": pd.Timestamp.now().isoformat(timespec="seconds"),
        "tiled_res": sorted(TILED_RES), "tile_res": TILE_RES,
    }
    (WEB_DATA / "meta.json").write_text(json.dumps(meta, default=lambda o: o.item() if isinstance(o, np.generic) else str(o)))


if __name__ == "__main__":
    main()
