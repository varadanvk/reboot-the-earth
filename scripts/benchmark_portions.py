"""Score orchard-chill estimation methods on Dynamic chill portions and Utah units.

Usage: uv run scripts/benchmark_portions.py

Same truth, orchard-winter filter (>=90% of Nov 1 - Feb 28 hours), and four methods as
benchmark_chill.py (nearest, idw3, grid, grid_corr). Each method's hourly temperature is
built first, then run through chill_models: the Dynamic model runs continuously from
Sep 1 (or from the first day FNRIC reports for that orchard) and increments are summed
over Nov 1 - Feb 28. Missing hours are skipped and the winter total is scaled by
expected/present hours, as in the chill-hours benchmark.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chill_models as cm
from benchmark_chill import MIN_COVER, ROOT, WINTER_MONTHS, load_cimis, load_grid

MODELS = {"portions_dynamic": cm.dynamic_portions, "units_utah": cm.utah_units}


def winter_totals(temps, start_by_season):
    """Per season: {model: Nov-Feb total scaled for missing hours} plus hour coverage."""
    out = {}
    temps = cm.hour_beginning(temps[~temps.index.duplicated()].sort_index())
    for season, start in start_by_season.items():
        y = int(season[:4])
        idx = pd.date_range(max(start, pd.Timestamp(f"{y}-09-01")), f"{y + 1}-02-28 23:00", freq="h")
        t = temps.reindex(idx)
        win = idx[idx.month.isin(WINTER_MONTHS) & (idx >= f"{y}-11-01")]
        present = t[win].notna().sum()
        if present == 0:
            continue
        r = {"cover": present / len(win)}
        for m, fn in MODELS.items():
            r[m] = fn(t)[win].sum() * len(win) / present
        out[season] = r
    return out


def main():
    nb = pd.read_csv(ROOT / "sites" / "orchard_neighbors.csv")
    names = pd.read_csv(ROOT / "sites" / "sites.csv").set_index("site").name
    grid = load_grid()
    cimis = {sid: load_cimis(sid) for sid in nb.cimis.unique()}

    truth = pd.read_parquet(ROOT / "fnric" / "chill_daily_Wildeye.parquet")
    first = truth.groupby(["StationID", "season"]).Date.min()
    truth = truth[truth.Date.dt.month.isin(WINTER_MONTHS)]
    g = truth.groupby(["StationID", "season"])
    winter_days = {s: len(pd.date_range(f"{s[:4]}-11-01", f"{s[5:]}-02-28")) for s in truth.season.unique()}
    expected = g.size().index.get_level_values("season").map(winter_days).values * 24
    tr = g[["portions_dynamic", "units_utah"]].sum()
    tr["cover"] = g.n_hours.sum() / expected
    tr = tr[tr.cover >= MIN_COVER]

    rows = []
    for wid, n in nb.groupby("wid"):
        if wid not in grid:
            continue
        n = n.sort_values("rank")
        w = 1 / n.km.clip(lower=1).values ** 2
        w = w / w.sum()
        frame = pd.concat({f"c{i}": cimis[s] for i, s in enumerate(n.cimis)}, axis=1, sort=True)
        frame = frame[~frame.index.duplicated()]
        est = {"nearest": frame["c0"]}
        vals, ok = frame.values, ~np.isnan(frame.values)
        ww = np.where(ok, w, 0)
        est["idw3"] = pd.Series(np.nansum(vals * ww, 1) / np.where(ww.sum(1) > 0, ww.sum(1), np.nan), index=frame.index)
        og = grid[wid]
        est["grid"] = og
        bias = 0
        for i, s in enumerate(n.cimis):
            d = (cimis[s] - grid[f"CIMIS-{s}"]).dropna()
            bias = bias + w[i] * d.groupby([d.index.month, d.index.hour]).mean()
        key = pd.MultiIndex.from_arrays([og.index.month, og.index.hour])
        est["grid_corr"] = og + bias.reindex(key).fillna(0).values

        seasons = {s: first[(wid, s)] for s in tr.loc[wid].index} if wid in tr.index.get_level_values(0) else {}
        for m, series in est.items():
            for season, r in winter_totals(series, seasons).items():
                if r["cover"] >= MIN_COVER:
                    for model in MODELS:
                        rows.append(dict(orchard=names.get(wid, wid), wid=wid, season=season, method=m, model=model,
                                         est=r[model], truth=tr.loc[(wid, season), model]))

    r = pd.DataFrame(rows)
    r["err"] = r.est - r.truth
    full = r.groupby(["wid", "season", "model"]).method.transform("nunique") == r.method.nunique()
    r = r[full]

    for model in MODELS:
        d = r[r.model == model]
        mean_truth = d.drop_duplicates(["wid", "season"]).truth.mean()
        s = d.groupby("method").err.agg(n="size", bias="mean", mae=lambda e: e.abs().mean(),
                                        rmse=lambda e: np.sqrt((e ** 2).mean()), worst=lambda e: e.abs().max())
        s["mae_pct"] = 100 * s.mae / mean_truth
        print(f"\n== {model}: {d[['wid','season']].drop_duplicates().shape[0]} orchard-winters, "
              f"{d.wid.nunique()} orchards, truth mean {mean_truth:.1f} ==")
        print(s.round(1).sort_values("mae").to_string())
        print("MAE by season:")
        print(d.pivot_table(index="season", columns="method", values="err", aggfunc=lambda e: e.abs().mean()).round(1).to_string())
    r.to_csv(ROOT / "sites" / "benchmark_portions.csv", index=False)


if __name__ == "__main__":
    main()
