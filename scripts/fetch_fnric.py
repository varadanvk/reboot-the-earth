"""Pull FNRIC's daily chill-model values for Wildeye in-orchard stations (and optionally CIMIS).

Usage: uv run scripts/fetch_fnric.py [--types Wildeye,CIMIS] [--seasons 2022-2023,...]

Source is the public API behind https://fruitsandnuts.ucdavis.edu/chill-calculator. It
returns per-day chill values (hours 32-45F, hours <45F, Dynamic portions, Utah units,
n_hours of data), not raw temperatures. Seasons run Sep 1 - Aug 31.
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://f5dby14cj5.execute-api.us-west-2.amazonaws.com/prod"
OUT = Path(__file__).resolve().parent.parent / "data" / "fnric"
SEASONS = "2022-2023,2023-2024,2024-2025,2025-2026,2026-2027"


def get(path, **params):
    for attempt in range(5):
        r = requests.get(f"{API}/{path}", params=params, timeout=120)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def parse_coord(s):
    # "36º48'52N / 36.814444" or " / 36.81" -> 36.814444
    return float(s.split("/")[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="Wildeye")
    ap.add_argument("--seasons", default=SEASONS)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    stations = pd.DataFrame(get("stations")["stations"])
    stations["type"] = stations.StationID.str.split("-").str[0]
    stations["lat"] = stations.HmsLatitude.map(parse_coord)
    stations["lon"] = stations.HmsLongitude.map(parse_coord)
    stations.to_csv(OUT / "stations.csv", index=False)

    wanted = stations[stations.type.isin(args.types.split(","))]
    frames = []
    for sid in wanted.StationID:
        for season in args.seasons.split(","):
            vals = get("chill-models", **{"station-id": sid, "chill-year": season})["model_values"]
            if vals:
                frames.append(pd.DataFrame(vals).assign(StationID=sid, season=season))
        print(sid, sum(len(f) for f in frames if f.StationID.iat[0] == sid), "days", flush=True)

    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df.Date)
    df.sort_values(["StationID", "Date"]).to_parquet(OUT / f"chill_daily_{'_'.join(args.types.split(','))}.parquet")


if __name__ == "__main__":
    main()
