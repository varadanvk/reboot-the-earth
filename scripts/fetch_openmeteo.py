"""Pull Open-Meteo gridded temperature (history + 16-day forecast) and elevation for every site.

Usage: uv run scripts/fetch_openmeteo.py [--start 2022-09-01]

Reads data/sites/sites.csv (site, kind, name, lat, lon). Writes to data/openmeteo/sites/:
  history_hourly.parquet, history_daily.parquet, forecast_hourly.parquet,
  forecast_daily.parquet, elevation.csv
Times are local (America/Los_Angeles). No key needed; the free tier rate-limits, so
requests are paced and retried.
"""

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent / "data"
OUT = ROOT / "openmeteo" / "sites"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ELEVATION = "https://api.open-meteo.com/v1/elevation"
COMMON = dict(hourly="temperature_2m", daily="temperature_2m_max,temperature_2m_min",
              temperature_unit="fahrenheit", timezone="America/Los_Angeles")


def get(url, **params):
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, timeout=300)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def frames(j, site):
    h = pd.DataFrame(j["hourly"]).assign(site=site)
    d = pd.DataFrame(j["daily"]).assign(site=site)
    return h, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-09-01")
    args = ap.parse_args()
    end = (date.today() - timedelta(days=2)).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    sites = pd.read_csv(ROOT / "sites" / "sites.csv")

    elev = get(ELEVATION, latitude=",".join(map(str, sites.lat)), longitude=",".join(map(str, sites.lon)))
    sites.assign(elev_m=elev["elevation"]).to_csv(OUT / "elevation.csv", index=False)

    # cache raw responses per site so an interrupted run resumes where it stopped
    cache = OUT / "raw"
    cache.mkdir(exist_ok=True)
    hist_h, hist_d, fc_h, fc_d = [], [], [], []
    for s in sites.itertuples():
        for kind, url, extra in [("hist", ARCHIVE, dict(start_date=args.start, end_date=end)),
                                 ("fc", FORECAST, dict(forecast_days=16))]:
            path = cache / f"{kind}_{s.site}.json"
            if not path.exists():
                j = get(url, latitude=s.lat, longitude=s.lon, **extra, **COMMON)
                path.write_text(json.dumps(j))
                time.sleep(1)
            h, d = frames(json.loads(path.read_text()), s.site)
            (hist_h if kind == "hist" else fc_h).append(h)
            (hist_d if kind == "hist" else fc_d).append(d)
        print(s.site, len(hist_h[-1]), "hist hours", flush=True)

    for name, parts in [("history_hourly", hist_h), ("history_daily", hist_d), ("forecast_hourly", fc_h), ("forecast_daily", fc_d)]:
        df = pd.concat(parts, ignore_index=True)
        df["time"] = pd.to_datetime(df.time)
        df.to_parquet(OUT / f"{name}.parquet")


if __name__ == "__main__":
    main()
