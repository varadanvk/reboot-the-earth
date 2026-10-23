"""Score combined (ensemble) chill estimators against the Wildeye in-orchard stations.

Usage: uv run scripts/benchmark_ensemble.py

Reuses data loading, truth definition and the four baselines from benchmark_chill.py.
Added methods (chill totals per orchard-winter):
  avg_t      - hourly mean of idw3 and grid_corr temperatures (grid_corr fills idw3 gaps)
  avg_chill  - mean of the idw3 and grid_corr chill totals
  lapse      - idw3 with each neighbor shifted to orchard elevation (-6.5 C/km, DEM elevations)
  lapse_avg  - mean of lapse and grid_corr chill totals
  w_cv       - w*grid_corr + (1-w)*idw3, one constant w, chosen by leave-one-orchard-out CV
  spread_cv  - grid_corr weight = spread/(spread+s), spread = std of the 3 neighbors' winter
               chill that season; s chosen by leave-one-orchard-out CV
Fitted methods pick their parameter on all OTHER orchards' winters (MAE) and score the held-out one.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_chill import MIN_COVER, ROOT, WINTER_MONTHS, load_cimis, load_grid, winter_chill  # noqa: E402

LAPSE_C_PER_KM = 6.5
BASE = ["nearest", "idw3", "grid_corr", "grid"]
W_GRID = np.linspace(0, 1, 21)
S_GRID = np.array([10, 25, 50, 100, 200, 400, 800])


def load_truth():
    truth = pd.read_parquet(ROOT / "fnric" / "chill_daily_Wildeye.parquet")
    truth = truth[truth.Date.dt.month.isin(WINTER_MONTHS)]
    g = truth.groupby(["StationID", "season"])
    days = {s: len(pd.date_range(f"{s[:4]}-11-01", f"{s[5:]}-02-28")) for s in truth.season.unique()}
    expected = g.size().index.get_level_values("season").map(days).values * 24
    truth = pd.DataFrame({"truth": g.hours_32_45.sum(), "cover": g.n_hours.sum() / expected})
    return truth[truth.cover >= MIN_COVER]


def idw(frame, w):
    """IDW over whichever neighbors reported that hour."""
    vals, ok = frame.values, ~np.isnan(frame.values)
    ww = np.where(ok, w, 0)
    return pd.Series(np.nansum(vals * ww, 1) / np.where(ww.sum(1) > 0, ww.sum(1), np.nan), index=frame.index)


def orchard_estimates(n, cimis, grid, elev, wid):
    """Hourly series per base/hourly method, plus per-neighbor chill totals for the spread."""
    w = 1 / n.km.clip(lower=1).values ** 2
    w = w / w.sum()
    frame = pd.concat({f"c{i}": cimis[s] for i, s in enumerate(n.cimis)}, axis=1, sort=True)
    frame = frame[~frame.index.duplicated()]
    est = {"nearest": frame["c0"], "idw3": idw(frame, w)}

    og = grid[wid]
    est["grid"] = og
    bias = 0
    for i, s in enumerate(n.cimis):
        d = (cimis[s] - grid[f"CIMIS-{s}"]).dropna()
        bias = bias + w[i] * d.groupby([d.index.month, d.index.hour]).mean()
    key = pd.MultiIndex.from_arrays([og.index.month, og.index.hour])
    est["grid_corr"] = og + bias.reindex(key).fillna(0).values

    # hourly mean of idw3 and grid_corr over the grid's hours
    both = pd.concat([est["idw3"], est["grid_corr"]], axis=1, sort=True)
    est["avg_t"] = both.mean(axis=1).dropna()

    # lapse-rate shift of each neighbor to orchard elevation
    adj = pd.concat({f"c{i}": frame[f"c{i}"] - LAPSE_C_PER_KM * (elev[wid] - elev[f"CIMIS-{s}"]) / 1000
                     for i, s in enumerate(n.cimis)}, axis=1)
    est["lapse"] = idw(adj, w)

    nb_chill = pd.concat({i: winter_chill(frame[f"c{i}"]).chill for i in range(len(n))}, axis=1)
    return est, nb_chill


def fit_loo(r, make, grid):
    """Leave-one-orchard-out: pick the parameter minimizing MAE on other orchards, apply to held-out."""
    out, chosen = {}, {}
    for wid in r.index.get_level_values("wid").unique():
        tr = r[r.index.get_level_values("wid") != wid]
        mae = [(make(tr, p) - tr.truth).abs().mean() for p in grid]
        chosen[wid] = grid[int(np.argmin(mae))]
        te = r[r.index.get_level_values("wid") == wid]
        out[wid] = make(te, chosen[wid])
    return pd.concat(out.values()).reindex(r.index), chosen


def main():
    nb = pd.read_csv(ROOT / "sites" / "orchard_neighbors.csv")
    names = pd.read_csv(ROOT / "sites" / "sites.csv").set_index("site").name
    elev = pd.read_csv(ROOT / "openmeteo" / "sites" / "elevation.csv").set_index("site").elev_m
    grid = load_grid()
    cimis = {sid: load_cimis(sid) for sid in nb.cimis.unique()}
    truth = load_truth()

    # elevation sanity: orchard DEM vs neighbor DEM vs listed CIMIS elevation
    el = pd.read_csv(ROOT / "openmeteo" / "sites" / "elevation.csv").set_index("site")
    lst = el.loc[[f"CIMIS-{s}" for s in nb.cimis.unique()]]
    print(f"orchard DEM elev: {elev[[w for w in nb.wid.unique()]].min():.0f}-{elev[[w for w in nb.wid.unique()]].max():.0f} m")
    print(f"CIMIS listed vs DEM elev diff: median {(lst.elev_m_listed - lst.elev_m).median():.0f} m, "
          f"max abs {(lst.elev_m_listed - lst.elev_m).abs().max():.0f} m")

    rows = []
    for wid, n in nb.groupby("wid"):
        if wid not in grid:
            continue
        n = n.sort_values("rank")
        est, nb_chill = orchard_estimates(n, cimis, grid, elev, wid)
        tot = {m: winter_chill(s) for m, s in est.items()}
        tot = {m: t.chill[t.cover >= MIN_COVER] for m, t in tot.items()}
        t = pd.DataFrame(tot)
        t["spread"] = nb_chill.std(axis=1)
        t["elev_diff"] = elev[wid] - np.mean([elev[f"CIMIS-{s}"] for s in n.cimis])
        t["wid"], t["km"] = wid, n.km.iat[0]
        rows.append(t.dropna(subset=["idw3", "grid_corr", "grid", "nearest"]).rename_axis("season").reset_index())
    d = pd.concat(rows)
    d = d.set_index(["wid", "season"]).join(truth.truth.rename_axis(["wid", "season"]), how="inner")
    d["avg_chill"] = (d.idw3 + d.grid_corr) / 2
    d["lapse_avg"] = (d.lapse + d.grid_corr) / 2

    d["w_cv"], w_chosen = fit_loo(d, lambda x, w: w * x.grid_corr + (1 - w) * x.idw3, W_GRID)
    d["spread_cv"], s_chosen = fit_loo(
        d, lambda x, s: (x.spread / (x.spread + s)) * x.grid_corr + (1 - x.spread / (x.spread + s)) * x.idw3, S_GRID)
    d = d.dropna(subset=["lapse", "avg_t"])

    methods = BASE + ["avg_t", "avg_chill", "lapse", "lapse_avg", "w_cv", "spread_cv"]
    r = d.reset_index().melt(id_vars=["wid", "season", "truth"], value_vars=methods, var_name="method", value_name="est")
    r["err"] = r.est - r.truth
    best = r.groupby(["wid", "season"]).err.apply(lambda e: e.abs().min())
    suspect = best[best > 300].index
    r["suspect"] = r.set_index(["wid", "season"]).index.isin(suspect)

    def score(df):
        return df.groupby("method").err.agg(
            n="size", bias="mean", mae=lambda e: e.abs().mean(), rmse=lambda e: np.sqrt((e ** 2).mean()),
            worst=lambda e: e.abs().max()).round(0).sort_values("mae")

    print(f"\norchard-winters scored: {r[['wid','season']].drop_duplicates().shape[0]} "
          f"({r.wid.nunique()} orchards), truth mean {r.truth.mean():.0f} chill hours")
    print(f"suspect truth: {[(names.get(w, w), s) for w, s in suspect]}")
    print(f"w_cv chosen per held-out orchard: {sorted(set(np.round(list(w_chosen.values()), 2)))}")
    print(f"spread_cv s chosen: {sorted(set(s_chosen.values()))}")
    print("\nAll orchard-winters:")
    print(score(r).to_string())
    print("\nExcluding suspect:")
    print(score(r[~r.suspect]).to_string())
    print("\nBy season (MAE, excluding suspect):")
    print(r[~r.suspect].pivot_table(index="season", columns="method", values="err",
                                    aggfunc=lambda e: e.abs().mean()).round(0)[methods].to_string())
    print("\nIn-sample (NOT cross-validated) best constant w, for reference:")
    for w in (0, 0.25, 0.5, 0.75, 1):
        print(f"  w={w}: MAE {(w * d.grid_corr + (1 - w) * d.idw3 - d.truth).abs().mean():.0f}")


if __name__ == "__main__":
    main()
