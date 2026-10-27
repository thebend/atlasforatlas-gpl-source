"""Elevation texture for the scene window from Terrarium tiles.

Source: AWS Open Data "Terrain Tiles" (Terrarium encoding; SRTM/GMTED/ETOPO1
etc., public domain/open; attribution: Mapzen + listed sources). Reuses the
repo's cached z7 tiles in data/dem and fetches only the missing ones.

The world base (ATLAS_SCENE=world) reaches the poles. Web Mercator tiles stop at 85.05
degrees, and their Antarctica is wrong (near sea level where the ice plateau stands 3 km
high), so ETOPO1 Ice Surface (NOAA NGDC, public domain; Antarctic RAMP topography, IBCAO
Arctic bathymetry) replaces them south of 60 S (blended over 60-62) and north of 83.5 N
(blended over 83.5-85), fetched through NOAA's ERDDAP.

Output: public/data/elev.png — RGBA8, equirectangular over the scene window,
v = elevation_m + 12000 split as R=v>>8, G=v&255. B = 255 where elevation>0
(coarse land guess; the NE land mask refines it in landmask.py). A = 255.
"""
from __future__ import annotations

import urllib.request

import numpy as np
from PIL import Image

from etl.common import CACHE, CFG, LAT0, LAT1, LON0, LON1, OUT, ROOT, SCACHE, UA, grid, tile_xy, write_json

Z = CFG['dem_z']
STEP = CFG['terrain_step']
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ETOPO_URL = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv"
             "?altitude%5B({a}):{s}:({b})%5D%5B(-180):{s}:(180)%5D")
# ETOPO bands: (from lat, to lat, blend start, blend width): full weight poleward of start + width
CAPS = ((83.5, 90.0, 83.5, 1.5), (-90.0, -60.0, 60.0, 2.0))


def etopo_cap(lat_a: float, lat_b: float, stride: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ETOPO1 (1 arc-minute) between two latitudes at `stride` minutes: lats, lons, heights."""
    dst = CACHE / "etopo" / f"cap_{lat_a:+.1f}_{lat_b:+.1f}_s{stride}.csv"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(ETOPO_URL.format(a=lat_a, b=lat_b, s=stride), headers={"User-Agent": UA})
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(urllib.request.urlopen(req, timeout=600).read())
        tmp.replace(dst)
    d = np.loadtxt(dst, delimiter=",", skiprows=2)
    lats, lons = np.unique(d[:, 0]), np.unique(d[:, 1])
    z = d[:, 2].reshape(len(lats), len(lons))   # ERDDAP rows: latitude outer, longitude inner
    return lats, lons, z


def sample(lats: np.ndarray, lons: np.ndarray, z: np.ndarray, qlat: np.ndarray, qlon: np.ndarray) -> np.ndarray:
    """Bilinear sample of a regular lat/lon grid."""
    fy = np.clip((qlat - lats[0]) / (lats[1] - lats[0]), 0, len(lats) - 1.001)
    fx = np.clip((qlon - lons[0]) / (lons[1] - lons[0]), 0, len(lons) - 1.001)
    y0, x0 = np.floor(fy).astype(int), np.floor(fx).astype(int)
    dy, dx = fy - y0, fx - x0
    a = z[y0, x0] * (1 - dx) + z[y0, x0 + 1] * dx
    b = z[y0 + 1, x0] * (1 - dx) + z[y0 + 1, x0 + 1] * dx
    return a * (1 - dy) + b * dy


def load_tile(x: int, y: int) -> np.ndarray:
    local = ROOT / "data" / "dem" / f"z{Z}" / f"t_{x}_{y}.png"
    cached = CACHE / "dem" / f"z{Z}" / f"t_{x}_{y}.png"
    if local.exists():
        p = local
    else:
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(TILE_URL.format(z=Z, x=x, y=y), headers={"User-Agent": UA})
            cached.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        p = cached
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float64)
    return a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768


def main() -> None:
    lons, lats = grid(STEP)
    fx, fy = tile_xy(LON0, LAT1, Z)
    gx, gy = tile_xy(LON1, LAT0, Z)
    tiles = {}
    last = 2 ** Z - 1                          # lon 180 / lat -85 fall one tile past the grid's edge
    for tx in range(int(fx), min(int(gx), last) + 1):
        for ty in range(int(fy), min(int(gy), last) + 1):
            tiles[(tx, ty)] = load_tile(tx, ty)
    print("tiles", len(tiles))
    n = 2 ** Z
    px = (lons + 180) / 360 * n
    r = np.radians(lats)
    py = (1 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2 * n
    H = np.zeros(lons.shape)
    tx = np.minimum(np.floor(px).astype(int), 2 ** Z - 1)
    ty = np.minimum(np.floor(py).astype(int), 2 ** Z - 1)
    for (kx, ky), arr in tiles.items():
        m = (tx == kx) & (ty == ky)
        if not m.any():
            continue
        u = np.clip((px[m] - kx) * 256 - 0.5, 0, 254.999)
        v = np.clip((py[m] - ky) * 256 - 0.5, 0, 254.999)
        u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
        du, dv = u - u0, v - v0
        a = arr[v0, u0] * (1 - du) + arr[v0, u0 + 1] * du
        b = arr[v0 + 1, u0] * (1 - du) + arr[v0 + 1, u0 + 1] * du
        H[m] = a * (1 - dv) + b * dv
    if LAT0 < -60 or LAT1 > 83.5:
        stride = max(1, round(STEP * 60))          # arc-minutes, matching the texture's step
        for a, b, start, width in CAPS:
            m = (lats >= a) & (lats <= b)
            if not m.any():
                continue
            clat, clon, cz = etopo_cap(a, b, stride)
            w = np.clip((np.abs(lats[m]) - start) / width, 0, 1)
            H[m] = H[m] * (1 - w) + sample(clat, clon, cz, lats[m], lons[m]) * w
            print(f"polar cap {a:+.1f}..{b:+.1f}: ETOPO1 {cz.shape}")
    v = np.clip(np.round(H + 12000), 0, 65535).astype(np.uint32)
    img = np.zeros(H.shape + (4,), np.uint8)
    img[..., 0] = v >> 8
    img[..., 1] = v & 255
    img[..., 2] = np.where(H > 0, 255, 0)
    img[..., 3] = 255
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img, "RGBA").save(OUT / "elev.png", optimize=True)
    SCACHE.mkdir(parents=True, exist_ok=True)
    np.save(SCACHE / "elev.npy", H.astype(np.float32))
    write_json(OUT / "elev.meta.json", {
        "bbox": [LON0, LAT0, LON1, LAT1], "step": STEP, "width": H.shape[1], "height": H.shape[0],
        "encoding": "v=elev_m+12000; R=v>>8, G=v&255; B=255 if elev>0",
        "source": f"AWS Open Data Terrain Tiles (Terrarium), z{Z}" + ("; polar caps ETOPO1 Ice Surface (NOAA)" if LAT0 < -60 or LAT1 > 83.5 else ""),
        "attribution": "Terrain Tiles: Mapzen; SRTM, GMTED2010, ETOPO1 and other public sources",
        "min": float(H.min()), "max": float(H.max()),
    })
    print("elev", H.shape, f"{H.min():.0f}..{H.max():.0f} m")


if __name__ == "__main__":
    main()
