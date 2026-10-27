"""Rebuild the North America source data: download every source, then convert it.

    cd app
    uv run --project .. python -m etl.fetch.north_america            # everything
    uv run --project .. python -m etl.fetch.north_america fetch      # downloads only
    uv run --project .. python -m etl.fetch.north_america convert    # conversions only
    uv run --project .. python -m etl.fetch.north_america ohm_tags royce_convert ...   # named steps

Writes <CACHE>/scenes/north-america/raw/ (downloads), geo/*.geojson and sources.json, where CACHE is
etl/common.CACHE (env ATLAS_CACHE). Downloads are skipped when their file is already in the cache, so a rerun
only converts. Hand-curated inputs are read from app/sources/north-america/.
Network: Newberry, USDA Forest Service ArcGIS (paged), GitHub raw, OpenHistoricalMap Overpass (~75 queries,
4 s apart, pinned to a date), open.canada.ca / data.sac-isc.gc.ca, Ontario LIO, rcaanc-cirnac.gc.ca.
The OHM raw download is ~1.4 GB.
"""
from __future__ import annotations

import sys
import time


from etl.fetch.north_america import canada_treaties, convert, fetch, make_sources, ohm_convert, ohm_fetch

FETCH = {
    "ahcb": fetch.ahcb,
    "royce": fetch.royce,
    "basemaps": fetch.basemaps,
    "canada_treaties": fetch.canada_treaties,
    "ohm_tags": ohm_fetch.tags,
    "ohm_geometry": ohm_fetch.geometry,
}
CONVERT = {
    "newberry_convert": convert.newberry,
    "royce_convert": convert.royce,
    "basemaps_convert": convert.basemaps,
    "ohm_convert": ohm_convert.main,
    "canada_treaties_convert": canada_treaties.main,
    "sources_json": make_sources.main,
}
STEPS = {**FETCH, **CONVERT}


def main(args):
    if not args:
        names = list(STEPS)
    elif args == ["fetch"]:
        names = list(FETCH)
    elif args == ["convert"]:
        names = list(CONVERT)
    else:
        bad = [a for a in args if a not in STEPS]
        if bad:
            raise SystemExit(f"unknown step(s) {bad}; steps: fetch, convert, {', '.join(STEPS)}")
        names = args
    from .helpers import BASE
    print("north-america sources ->", BASE, flush=True)
    for n in names:
        t = time.time()
        print(f"[{n}]", flush=True)
        r = STEPS[n]()
        print(f"[{n}] done in {time.time() - t:.0f} s" + (f": {r}" if r is not None else ""), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
