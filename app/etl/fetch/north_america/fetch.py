"""Download the file-based North America sources into <CACHE>/scenes/north-america/raw/ (skips what is there).

  ahcb/             Newberry AHCB US Historical States & Territories, Gen .001 deg shapefile zip
  royce/            USFS 'Tribal Land Cessions' (Royce 1899) ArcGIS MapServer layer 1 (polygons) + 2 (table),
                    paged 200 records at a time, merged into polys.geojson + table.json
  hb/               aourednik/historical-basemaps world_<year>.geojson, pinned to a commit
  canada_treaties/  CIRNAC/ISC Historic Treaties SHP, Ontario LIO Morris 1943 treaty areas SHP, and the
                    CIRNAC Treaty Texts pages the curated treaty dates were transcribed from
OHM (Overpass) is in ohm_fetch.py.
"""
from __future__ import annotations

import json
import zipfile

from etl import profile
from .helpers import RAW, download, get_json, log, unzip

# ---- Newberry Library, Atlas of Historical County Boundaries
AHCB_ZIP = "https://publications.newberry.org/ahcb/downloads/gis/US_AtlasHCB_StateTerr_Gen001.zip"


def ahcb():
    d = RAW / "ahcb"
    z = download(AHCB_ZIP, d / "US_AtlasHCB_StateTerr_Gen001.zip")
    unzip(z, d, "US_AtlasHCB_StateTerr_Gen001/US_HistStateTerr_Gen001_Shapefile/US_HistStateTerr_Gen001.shp")


# ---- USDA Forest Service, Royce cessions
ROYCE = "https://apps.fs.usda.gov/ArcX/rest/services/EDW/EDW_TribalCessionLands_01/MapServer"
PAGE = 200


def _pages(kind: str, url_fmt: str):
    """Page an ArcGIS query by resultOffset until a short page; each page cached as its own file."""
    out, off = [], 0
    while True:
        ext = "geojson" if kind == "pg" else "json"
        d = get_json(url_fmt.format(off=off), RAW / "royce" / kind / f"{kind[0]}{off}.{ext}")
        if "error" in d:
            raise SystemExit(f"ArcGIS error: {d['error']}")
        out += d["features"]
        if len(d["features"]) < PAGE and not d.get("exceededTransferLimit"):
            return out
        off += PAGE


def royce():
    polys, table = RAW / "royce/polys.geojson", RAW / "royce/table.json"
    if polys.exists() and table.exists():
        return
    q = "where=1%3D1&outFields=*&resultOffset={off}&resultRecordCount=" + str(PAGE) + "&orderByFields=objectid"
    feats = _pages("pg", f"{ROYCE}/1/query?{q}&outSR=4326&geometryPrecision=5&f=geojson")
    rows = [r["attributes"] for r in _pages("tb", f"{ROYCE}/2/query?{q}&f=json")]
    assert len({f["properties"]["objectid"] for f in feats}) == len(feats), "duplicate polygons across pages"
    assert len({r["objectid"] for r in rows}) == len(rows), "duplicate table rows across pages"
    polys.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    table.write_text(json.dumps(rows))
    log("  royce:", len(feats), "polygons,", len(rows), "table rows")


# ---- aourednik/historical-basemaps (GPL-3.0); pinned to the master commit current when first fetched
HB_COMMIT = "da7a4b735ecef70aebdc9c73e409d8a2500d50f3"  # 2026-09-15, 'Merge pull request #80'
HB_YEARS = [1492, 1500, 1530, 1600, 1650, 1700, 1715, 1783, 1800, 1815, 1878, 1880, 1900]
HB_RAW = f"https://raw.githubusercontent.com/aourednik/historical-basemaps/{HB_COMMIT}"


def basemaps():
    if profile.blocked("hb"):       # a profile that may not ship GPL data draws Cliopatria instead (etl/history/na_sides.py)
        log(f"  historical-basemaps: left out (profile {profile.NAME})")
        return
    for y in HB_YEARS:
        download(f"{HB_RAW}/geojson/world_{y}.geojson", RAW / f"hb/world_{y}.geojson", pause=0.5)
    download(f"{HB_RAW}/LICENSE", RAW / "hb/LICENSE", pause=0)


# ---- Canada: historic treaty areas
CIRNAC_SHP = ("https://data.sac-isc.gc.ca/geomatics/rest/directories/arcgisoutput/DonneesOuvertes_OpenData/"
              "Traite_historique_Historic_Treaty/Traite_historique_Historic_Treaty_SHP.zip")
MORRIS_ZIP = "https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/TreatiesMorrisMap1943.zip"
# CIRNAC Treaty Texts pages (https://www.rcaanc-cirnac.gc.ca/eng/1370373165583/1581292088522), saved as <name>.html;
# the dates in sources/north-america/canada_treaties.json were transcribed from these
CIRNAC_PAGES = {
    "t1_2": "1100100028664/1581294165927", "t3": "1100100028675/1581294028469",
    "t4": "1100100028689/1581293019940", "t5": "1100100028699/1581292696320", "t6": "1100100028710/1581292569426",
    "t7": "1100100028793/1581292336658", "t8": "1100100028813/1581293624572", "t9": "1100100028863/1581293189896",
    "t10": "1100100028874/1581292941464", "t11": "1100100028916/1581294101357",
    "douglas": "1100100029052/1581515763202", "ucls": "1370372152585/1581293792285",
    "pf1752": "1100100029040/1581293867988", "pf1760": "1100100029046/1581293947580",
    "robinson_sup": "1100100028978/1581293296351", "robinson_hur": "1100100028984/1581293724401",
    "williams_chip": "1100100029004/1581292197513", "williams_miss": "1100100029019/1581516441090",
}
CIRNAC_BASE = "https://www.rcaanc-cirnac.gc.ca/eng/"


def canada_treaties():
    d = RAW / "canada_treaties"
    unzip(download(CIRNAC_SHP, d / "Traite_historique_Historic_Treaty_SHP.zip"), d / "shp",
          "Traite_historique_Historic_Treaty_SHP.shp")
    z = download(MORRIS_ZIP, d / "TreatiesMorrisMap1943.zip")
    if not list((d / "morris").glob("*.shp")):
        shp = [n for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp")]
        assert len(shp) == 1, f"expected one .shp in {z.name}, got {shp}"
        unzip(z, d / "morris", shp[0])
    for name, path in CIRNAC_PAGES.items():
        download(CIRNAC_BASE + path, d / "cirnac_pages" / f"{name}.html")


ALL = [ahcb, royce, basemaps, canada_treaties]
