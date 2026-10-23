"""Add PRISM (4 km daily tmin/tmax) as an orchard chill estimator and score it with the baselines.

Usage: uv run scripts/benchmark_prism.py      (needs data/prism/sites_daily.parquet from fetch_prism.py)

Steps:
  1. Day alignment: PRISM stamp D covers ~04:00 PST D-1 to 04:00 PST D, so stamp D is used
     as calendar day D-1 (checked against CIMIS daily below).
  2. Hourly reconstruction from daily min/max (Linvill / chillR make_hourly_temps style):
     sine from sunrise to sunset, log decay from sunset to next sunrise.
  3. Reconstruction floor: at CIMIS stations, rebuild hourly from CIMIS's own daily
     max/min and compare winter chill with chill from the real CIMIS hourly series.
  4. Score on the same orchard-winters as benchmark_chill.py:
       prism      - PRISM tmin/tmax at the orchard -> hourly
       prism_corr - PRISM tmin/tmax shifted by the monthly (CIMIS - PRISM) daily bias at the
                    3 nearest CIMIS stations (IDW-weighted), then -> hourly
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_chill as bc  # noqa: E402

ROOT = bc.ROOT
SEASON_START = {"2023-2024": "2023-10-31", "2024-2025": "2024-10-31", "2025-2026": "2025-10-31"}
SEASON_END = {"2023-2024": "2024-03-01", "2024-2025": "2025-03-01", "2025-2026": "2026-03-01"}


def load_prism():
    """Return {site: DataFrame(tmin_f, tmax_f) indexed by PST calendar day}."""
    p = pd.read_parquet(ROOT / "prism" / "sites_daily.parquet")
    p["day"] = pd.to_datetime(p.prism_date) - pd.Timedelta(days=1)
    return {s: d.set_index("day")[["tmin_f", "tmax_f"]].sort_index() for s, d in p.groupby("site")}


def load_cimis_daily(sid):
    d = pd.read_parquet(ROOT / "cimis" / f"daily_{sid}.parquet")
    out = pd.DataFrame(index=pd.to_datetime(d.Date))
    for col, new in (("DayAirTmpMin", "tmin_f"), ("DayAirTmpMax", "tmax_f")):
        bad = d[col + "Qc"].isin(["M", "R", "S"]) | ~d[col].between(-20, 130)
        out[new] = d[col].where(~bad).values
    return out[~out.index.duplicated()].sort_index()


def daylight(lat, lon, days):
    """Sunrise, sunset (PST decimal hours) and day length for each date (Spencer declination)."""
    g = 2 * np.pi / 365 * (days.day_of_year.values - 1)
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    cosw = np.clip(-np.tan(np.radians(lat)) * np.tan(decl), -1, 1)
    dl = 2 * np.degrees(np.arccos(cosw)) / 15
    noon = 12 - (lon + 120) / 15  # solar noon in PST (equation of time ignored)
    return noon - dl / 2, noon + dl / 2, dl


def hourly_from_daily(daily, lat, lon):
    """Hourly temps (hour-ending PST labels, evaluated at mid-hour) from daily tmin/tmax."""
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()))
    tn, tx = daily.tmin_f.values, daily.tmax_f.values
    rise, sset, dl = daylight(lat, lon, daily.index)
    ts = tn + (tx - tn) * np.sin(np.pi * dl / (dl + 4))  # temperature at sunset
    n = len(daily)
    h = np.arange(24) + 0.5  # mid-hour, hours since local midnight
    out = np.full((n, 24), np.nan)
    for i in range(n):
        day = np.sin(np.pi * (h - rise[i]) / (dl[i] + 4))
        t = tn[i] + (tx[i] - tn[i]) * day
        # before sunrise: decay from previous sunset
        pre = h < rise[i]
        if i > 0 and pre.any():
            x, big = h[pre] + 24 - sset[i - 1], rise[i] + 24 - sset[i - 1]
            t[pre] = ts[i - 1] - (ts[i - 1] - tn[i]) * np.log1p(x) / np.log1p(big)
        elif pre.any():
            t[pre] = np.nan
        # after sunset: decay toward tomorrow's min
        post = h > sset[i]
        if i < n - 1 and post.any():
            x, big = h[post] - sset[i], rise[i + 1] + 24 - sset[i]
            t[post] = ts[i] - (ts[i] - tn[i + 1]) * np.log1p(x) / np.log1p(big)
        elif post.any():
            t[post] = np.nan
        out[i] = t
    idx = (daily.index.values[:, None] + (np.arange(24) + 1) * np.timedelta64(1, "h")).ravel()
    return pd.Series(out.ravel(), index=pd.DatetimeIndex(idx)).dropna()


def reconstruction_floor(sites):
    """Chill error from daily min/max reconstruction at CIMIS stations (vs real hourly)."""
    rows = []
    for _, s in sites[sites.kind != "orchard"].iterrows():
        sid = s.site.split("-")[1]
        try:
            real, daily = bc.load_cimis(sid), load_cimis_daily(sid)
        except FileNotFoundError:
            continue
        rec = hourly_from_daily(daily, s.lat, s.lon)
        a, b = bc.winter_chill(real), bc.winter_chill(rec)
        j = a.join(b, lsuffix="_real", rsuffix="_rec", how="inner")
        j = j[(j.cover_real >= 0.9) & (j.cover_rec >= 0.9) & j.index.isin(list(SEASON_START))]
        for season, r in j.iterrows():
            rows.append(dict(site=s.site, season=season, real=r.chill_real, rec=r.chill_rec))
    d = pd.DataFrame(rows)
    d["err"] = d.rec - d.real
    return d


def check_alignment(prism, sites):
    """Mean |PRISM - CIMIS| daily tmin/tmax with PRISM shifted by 0 and 1 further days."""
    res = {}
    for lag in (-1, 0, 1):
        errs = []
        for s in sites[sites.kind != "orchard"].site:
            sid = s.split("-")[1]
            try:
                c = load_cimis_daily(sid)
            except FileNotFoundError:
                continue
            p = prism[s].copy()
            p.index = p.index + pd.Timedelta(days=lag)
            j = p.join(c, rsuffix="_c", how="inner")
            errs.append(((j.tmin_f - j.tmin_f_c).abs().mean(), (j.tmax_f - j.tmax_f_c).abs().mean()))
        res[lag] = np.nanmean(errs, axis=0).round(2)
    return res


def load_truth():
    truth = pd.read_parquet(ROOT / "fnric" / "chill_daily_Wildeye.parquet")
    truth = truth[truth.Date.dt.month.isin(bc.WINTER_MONTHS)]
    g = truth.groupby(["StationID", "season"])
    winter_days = {s: len(pd.date_range(f"{s[:4]}-11-01", f"{s[5:]}-02-28")) for s in truth.season.unique()}
    expected = g.size().index.get_level_values("season").map(winter_days).values * 24
    truth = pd.DataFrame({"truth": g.hours_32_45.sum(), "cover": g.n_hours.sum() / expected})
    return truth[truth.cover >= bc.MIN_COVER]


def baseline_estimates(n, w, grid, cimis):
    """The four baselines from benchmark_chill.py for one orchard (copied logic)."""
    wid = n.wid.iat[0]
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
    return est


def prism_corr_daily(wid, n, w, prism, cdaily):
    """PRISM daily tmin/tmax at the orchard plus IDW-blended monthly (CIMIS - PRISM) bias."""
    p = prism[wid].copy()
    for col in ("tmin_f", "tmax_f"):
        shift = 0
        for i, s in enumerate(n.cimis):
            c = cdaily[s]
            d = (c[col] - prism[f"CIMIS-{s}"][col]).dropna()
            shift = shift + w[i] * d.groupby(d.index.month).mean()
        p[col] = p[col] + p.index.month.map(shift).fillna(0).values
    return p


def main():
    sites = pd.read_csv(ROOT / "sites" / "sites.csv").set_index("site", drop=False)
    prism = load_prism()
    print(f"PRISM alignment (mean |PRISM-CIMIS| tmin, tmax F) by extra day shift: {check_alignment(prism, sites)}")

    fl = reconstruction_floor(sites)
    print(f"\nReconstruction floor, CIMIS daily->hourly vs real hourly: {len(fl)} station-seasons, "
          f"real mean {fl.real.mean():.0f} h")
    print(f"  bias {fl.err.mean():+.0f}  MAE {fl.err.abs().mean():.0f}  RMSE {np.sqrt((fl.err ** 2).mean()):.0f}  "
          f"worst {fl.err.abs().max():.0f}")

    nb = pd.read_csv(ROOT / "sites" / "orchard_neighbors.csv")
    names = sites.name
    grid = bc.load_grid()
    cimis = {sid: bc.load_cimis(sid) for sid in nb.cimis.unique()}
    cdaily = {sid: load_cimis_daily(sid) for sid in nb.cimis.unique()}
    truth = load_truth()

    rows = []
    for wid, n in nb.groupby("wid"):
        if wid not in grid or wid not in prism:
            continue
        n = n.sort_values("rank")
        w = 1 / n.km.clip(lower=1).values ** 2
        w = w / w.sum()
        est = baseline_estimates(n, w, grid, cimis)
        lat, lon = sites.loc[wid, ["lat", "lon"]]
        est["prism"] = hourly_from_daily(prism[wid], lat, lon)
        est["prism_corr"] = hourly_from_daily(prism_corr_daily(wid, n, w, prism, cdaily), lat, lon)
        for m, series in est.items():
            wc = bc.winter_chill(series)
            for season, r in wc[wc.cover >= bc.MIN_COVER].iterrows():
                if (wid, season) in truth.index:
                    rows.append(dict(orchard=names.get(wid, wid), wid=wid, season=season, method=m,
                                     est=r.chill, truth=truth.loc[(wid, season), "truth"]))

    r = pd.DataFrame(rows)
    r["err"] = r.est - r.truth
    worst = r.groupby(["wid", "season"]).err.apply(lambda e: e.abs().min())
    suspect = worst[worst > 300].index
    r["suspect"] = r.set_index(["wid", "season"]).index.isin(suspect)
    r = r[r.groupby(["wid", "season"]).method.transform("nunique") == r.method.nunique()]

    def score(df):
        return df.groupby("method").err.agg(
            n="size", bias="mean", mae=lambda e: e.abs().mean(), rmse=lambda e: np.sqrt((e ** 2).mean()),
            worst=lambda e: e.abs().max()).round(0).sort_values("mae")

    print(f"\norchard-winters scored: {r[['wid', 'season']].drop_duplicates().shape[0]} "
          f"({r.wid.nunique()} orchards), truth mean {r.truth.mean():.0f} chill hours")
    print(f"suspect truth: {[(names.get(w, w), s) for w, s in suspect]}")
    print("\nAll orchard-winters:")
    print(score(r).to_string())
    print("\nExcluding suspect:")
    print(score(r[~r.suspect]).to_string())
    print("\nBy season (MAE, excluding suspect):")
    print(r[~r.suspect].pivot_table(index="season", columns="method", values="err",
                                    aggfunc=lambda e: e.abs().mean()).round(0).to_string())
    r.to_csv(ROOT / "prism" / "benchmark_prism.csv", index=False)


if __name__ == "__main__":
    main()
