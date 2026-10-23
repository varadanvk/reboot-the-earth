"""Score ways of estimating orchard chill against the Wildeye in-orchard stations.

Usage: uv run scripts/benchmark_chill.py

Truth: FNRIC's daily chill hours (32-45F) for each Wildeye orchard, summed Nov 1 - Feb 28.
Methods, each producing an hourly temperature series at the orchard:
  nearest   - nearest active CIMIS station
  idw3      - inverse-distance-squared blend of the 3 nearest CIMIS stations
  grid      - Open-Meteo gridded temperature at the orchard
  grid_corr - grid, shifted by the grid's month x hour-of-day bias at the 3 nearest
              CIMIS stations (IDW-weighted)
Only orchard-winters with >=90% of hours present in the truth are scored.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "data"
WINTER_MONTHS = [11, 12, 1, 2]
MIN_COVER = 0.9


def season_of(t):
    y = t.dt.year + (t.dt.month >= 9)
    return (y - 1).astype(str) + "-" + y.astype(str)


def load_cimis(sid):
    h = pd.read_parquet(ROOT / "cimis" / f"hourly_{sid}.parquet")
    bad = h.HlyAirTmpQc.isin(["M", "R", "S"]) | ~h.HlyAirTmp.between(5, 125)
    h.loc[bad, "HlyAirTmp"] = np.nan
    # CIMIS hours are Pacific Standard Time, hour-ending "0100".."2400"
    t = pd.to_datetime(h.Date) + pd.to_timedelta(h.Hour.astype(int) // 100, unit="h")
    return pd.Series(h.HlyAirTmp.values, index=t).sort_index()


def load_grid():
    g = pd.read_parquet(ROOT / "openmeteo" / "sites" / "history_hourly.parquet")
    # Open-Meteo local time (with DST) -> PST to line up with CIMIS
    t = g.time.dt.tz_localize("America/Los_Angeles", ambiguous="NaT", nonexistent="NaT")
    g["time"] = t.dt.tz_convert("Etc/GMT+8").dt.tz_localize(None)
    return {s: d.dropna(subset=["time"]).set_index("time").temperature_2m.sort_index()
            for s, d in g.groupby("site")}


def winter_chill(temps):
    """Chill hours per season over Nov-Feb, scaled up for missing hours, plus coverage."""
    x = temps[temps.index.month.isin(WINTER_MONTHS)]
    df = pd.DataFrame({"t": x.values}, index=x.index)
    df["season"] = season_of(df.index.to_series()).values
    g = df.groupby("season").t
    expected = g.size()
    present = g.count()
    chill = g.apply(lambda s: s.between(32, 45).sum())
    return pd.DataFrame({"chill": chill * expected / present.clip(lower=1), "cover": present / expected})


def main():
    nb = pd.read_csv(ROOT / "sites" / "orchard_neighbors.csv")
    names = pd.read_csv(ROOT / "sites" / "sites.csv").set_index("site").name
    grid = load_grid()
    cimis = {sid: load_cimis(sid) for sid in nb.cimis.unique()}

    truth = pd.read_parquet(ROOT / "fnric" / "chill_daily_Wildeye.parquet")
    truth = truth[truth.Date.dt.month.isin(WINTER_MONTHS)]
    g = truth.groupby(["StationID", "season"])
    # coverage against the full Nov-Feb calendar, not just the days that came back
    winter_days = {s: len(pd.date_range(f"{s[:4]}-11-01", f"{s[5:]}-02-28")) for s in truth.season.unique()}
    expected = g.size().index.get_level_values("season").map(winter_days).values * 24
    truth = pd.DataFrame({"truth": g.hours_32_45.sum(), "cover": g.n_hours.sum() / expected})
    truth = truth[truth.cover >= MIN_COVER]

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
        # IDW over whichever neighbors reported that hour
        vals, ok = frame.values, ~np.isnan(frame.values)
        ww = np.where(ok, w, 0)
        est["idw3"] = pd.Series(np.nansum(vals * ww, 1) / np.where(ww.sum(1) > 0, ww.sum(1), np.nan), index=frame.index)

        og = grid[wid]
        est["grid"] = og
        # grid bias at each neighbor, by month x hour, IDW-blended
        bias = 0
        for i, s in enumerate(n.cimis):
            d = (cimis[s] - grid[f"CIMIS-{s}"]).dropna()
            b = d.groupby([d.index.month, d.index.hour]).mean()
            bias = bias + w[i] * b
        key = pd.MultiIndex.from_arrays([og.index.month, og.index.hour])
        est["grid_corr"] = og + bias.reindex(key).fillna(0).values

        for m, series in est.items():
            wc = winter_chill(series)
            for season, r in wc[wc.cover >= MIN_COVER].iterrows():
                if (wid, season) in truth.index:
                    rows.append(dict(orchard=names.get(wid, wid), wid=wid, season=season, method=m,
                                     est=r.chill, truth=truth.loc[(wid, season), "truth"], km=n.km.iat[0]))

    r = pd.DataFrame(rows)
    r["err"] = r.est - r.truth
    # flag truth that disagrees wildly with every method (likely sensor fault), report both ways
    worst = r.groupby(["wid", "season"]).err.apply(lambda e: e.abs().min())
    suspect = worst[worst > 300].index
    r["suspect"] = r.set_index(["wid", "season"]).index.isin(suspect)
    # score only orchard-winters every method could estimate
    n_methods = r.method.nunique()
    full = r.groupby(["wid", "season"]).method.transform("nunique") == n_methods
    r = r[full]

    def score(df):
        return df.groupby("method").err.agg(
            n="size", bias="mean", mae=lambda e: e.abs().mean(), rmse=lambda e: np.sqrt((e ** 2).mean()),
            worst=lambda e: e.abs().max()).round(0).sort_values("mae")

    print(f"orchard-winters scored: {r[['wid','season']].drop_duplicates().shape[0]} "
          f"({r.wid.nunique()} orchards), truth mean {r.truth.mean():.0f} chill hours")
    print(f"suspect truth (all methods off by >300h): {[(names.get(w, w), s) for w, s in suspect]}")
    print("\nAll orchard-winters:")
    print(score(r).to_string())
    print("\nExcluding suspect:")
    print(score(r[~r.suspect]).to_string())
    print("\nBy season (MAE, excluding suspect):")
    print(r[~r.suspect].pivot_table(index="season", columns="method", values="err",
                                    aggfunc=lambda e: e.abs().mean()).round(0).to_string())
    r.to_csv(ROOT / "sites" / "benchmark_chill.csv", index=False)


if __name__ == "__main__":
    main()
