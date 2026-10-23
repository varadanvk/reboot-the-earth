"""Pull CIMIS hourly air temp + daily max/min for a set of stations into Parquet.

Usage: uv run scripts/fetch_cimis.py [--stations 6,70,71,39,5] [--start 1985-01-01] [--end today]

The CIMIS API caps each request at 5020 records (one record = one station-hour or
station-day), so requests are chunked by date range. Key is read from CIMIS_API_KEY.
"""

import argparse
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

BASE = "https://et.water.ca.gov/StationWeb"
OUT = Path(__file__).resolve().parent.parent / "data" / "cimis"
HOURLY_CHUNK_DAYS = 200  # 200 * 24 = 4800 records
DAILY_CHUNK_DAYS = 4800

load_dotenv()
session = requests.Session()
session.headers.update({
    "Ocp-Apim-Subscription-Key": os.environ["CIMIS_API_KEY"],
    "Accept": "application/json",
})


def get(path, **params):
    for attempt in range(5):
        try:
            r = session.get(f"{BASE}/{path}", params=params, timeout=120)
        except requests.ConnectionError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (503, 504, 429):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def chunks(start, end, days):
    while start <= end:
        stop = min(start + timedelta(days=days - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def records_to_frame(records, items):
    """Flatten {"HlyAirTmp": {"Value", "Qc", "Unit"}} into value + qc columns."""
    rows = []
    for rec in records:
        row = {k: rec.get(k) for k in ("Station", "Date", "Hour")}
        for item in items:
            cell = rec.get(item) or {}
            row[item] = cell.get("Value")
            row[f"{item}Qc"] = (cell.get("Qc") or "").strip()
        rows.append(row)
    df = pd.DataFrame(rows)
    for item in items:
        df[item] = pd.to_numeric(df[item], errors="coerce")
    return df


def fetch(station, start, end, hourly):
    items = ["HlyAirTmp"] if hourly else ["DayAirTmpMax", "DayAirTmpMin"]
    data_items = "hly-air-tmp" if hourly else "day-air-tmp-max,day-air-tmp-min"
    frames = []
    for a, b in chunks(start, end, HOURLY_CHUNK_DAYS if hourly else DAILY_CHUNK_DAYS):
        j = get("GetDataByStationNumber", stationNbrs=station, startDate=a.isoformat(),
                endDate=b.isoformat(), isHourly=str(hourly).lower(), unitOfMeasure="E",
                dataItems=data_items)
        recs = [r for p in j["Data"]["Providers"] for r in p["Records"]]
        if recs:
            frames.append(records_to_frame(recs, items))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default="6,70,71,39,5")
    ap.add_argument("--start", default="1985-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--overwrite", action="store_true", help="re-fetch stations already on disk")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    OUT.mkdir(parents=True, exist_ok=True)

    stations = pd.DataFrame(get("GetAllStations")["Stations"])
    stations.to_json(OUT / "stations.json", orient="records", indent=1)

    for sid in args.stations.split(","):
        for hourly in (False, True):
            name = f"{'hourly' if hourly else 'daily'}_{sid}.parquet"
            if (OUT / name).exists() and not args.overwrite:
                continue
            t = time.time()
            df = fetch(sid, start, end, hourly)
            df.to_parquet(OUT / name)
            print(f"station {sid} {name}: {len(df)} rows in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
