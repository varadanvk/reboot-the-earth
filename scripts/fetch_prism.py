"""Sample PRISM daily tmin/tmax at every site for the winter seasons into one Parquet.

Usage: uv run scripts/fetch_prism.py [--seasons 2023,2024,2025]

Uses the 4 km PRISM grid (800 m files are ~53 MB each, 4 km are ~2.7 MB). Each national
raster is downloaded from services.nacse.org, read in memory, sampled at the 53 sites
(nearest cell) and discarded. Output: data/prism/sites_daily.parquet with columns
site, prism_date, tmin_f, tmax_f. Already-extracted dates are skipped, so reruns resume.

prism_date is PRISM's stamp: the day ends 12Z (04:00 PST) on that date, so a stamp D
covers ~04:00 PST D-1 to 04:00 PST D, i.e. mostly calendar day D-1. benchmark_prism.py
shifts the stamp back one day. We fetch stamps Nov 1 - Mar 1 to cover calendar Oct 31 - Feb 29.
"""

import argparse
import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import rasterio
import requests
from rasterio.io import MemoryFile

ROOT = Path(__file__).resolve().parent.parent / "data"
OUT = ROOT / "prism" / "sites_daily.parquet"
URL = "https://services.nacse.org/prism/data/get/us/4km/{var}/{day}"
SLEEP = 0.5


def download(var, day):
    for attempt in range(6):
        try:
            r = requests.get(URL.format(var=var, day=day), timeout=120)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"giving up on {var} {day}")


def sample(content, sites):
    z = zipfile.ZipFile(io.BytesIO(content))
    tif = next(n for n in z.namelist() if n.endswith(".tif"))
    with MemoryFile(z.read(tif)) as mf, mf.open() as src:
        vals = [v[0] for v in src.sample(zip(sites.lon, sites.lat))]
        nodata = src.nodata
    s = pd.Series(vals, index=sites.site, dtype=float)
    s[s == nodata] = float("nan")
    return s * 9 / 5 + 32  # PRISM is degC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2023,2024,2025", help="start years of Nov-Feb seasons")
    args = ap.parse_args()

    sites = pd.read_csv(ROOT / "sites" / "sites.csv")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    have = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=["site", "prism_date", "tmin_f", "tmax_f"])
    done = set(have.prism_date.astype(str))
    parts = [have]

    days = []
    for y in map(int, args.seasons.split(",")):
        days += [d.strftime("%Y%m%d") for d in pd.date_range(f"{y}-11-01", f"{y + 1}-03-01")]
    todo = [d for d in days if d not in done]
    print(f"{len(todo)} dates to fetch ({len(done)} done)", flush=True)

    for i, day in enumerate(todo, 1):
        cols = {}
        for var in ("tmin", "tmax"):
            content = download(var, day)
            if content is None:
                break
            cols[f"{var}_f"] = sample(content, sites)
            time.sleep(SLEEP)
        if len(cols) == 2:
            df = pd.DataFrame(cols).rename_axis("site").reset_index()
            df.insert(1, "prism_date", day)
            parts.append(df)
        else:
            print(f"missing {day}", flush=True)
        if i % 10 == 0 or i == len(todo):
            pd.concat(parts, ignore_index=True).to_parquet(OUT, index=False)
            print(f"{i}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
