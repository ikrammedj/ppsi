# sentinel2_h3_square_png.py

import os
import ee
import h3
import requests

OUT_DIR = "ppsi/images/sentinel2_images"
os.makedirs(OUT_DIR, exist_ok=True)

START_DATE = "2025-01-01"
END_DATE   = "2025-12-31"

CLOUD_MAX = 30         
PADDING_RATIO = 0.08    
PIXELS = 1024           
SCALE_M = 10            


def ee_init():
    try:
        ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize()


def h3_to_square_bounds_latlon(h3_id: str, padding_ratio: float = 0.08):
    boundary = h3.cell_to_boundary(h3_id)  # [(lat, lon), ...]

    lats = [lat for lat, lon in boundary]
    lons = [lon for lat, lon in boundary]

    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    clat = (lat_min + lat_max) / 2
    clon = (lon_min + lon_max) / 2

    half_lat = (lat_max - lat_min) / 2
    half_lon = (lon_max - lon_min) / 2
    half = max(half_lat, half_lon) * (1.0 + padding_ratio)

    return (clon - half, clat - half, clon + half, clat + half)

def bounds_to_region(bounds):
    lon_min, lat_min, lon_max, lat_max = bounds
    return ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max], proj="EPSG:4326", geodesic=False)

def mask_s2_clouds(img: ee.Image) -> ee.Image:
    # SCL classes to mask: 3=shadow, 8=cloud med, 9=cloud high, 10=cirrus, 11=snow
    scl = img.select("SCL")
    bad = scl.eq(3).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10)).Or(scl.eq(11))
    return img.updateMask(bad.Not())

def get_s2_rgb(region: ee.Geometry, start_date: str, end_date: str, cloud_max: int = 30) -> ee.Image:
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(region)
           .filterDate(start_date, end_date)
           .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_max))
           .map(mask_s2_clouds))

    comp = col.median()

    # RGB Sentinel-2: B4=Red, B3=Green, B2=Blue
    rgb = comp.select(["B4", "B3", "B2"]).divide(10000).clamp(0, 0.3)
    return rgb

def download_png(img: ee.Image, region: ee.Geometry, out_path: str, pixels: int = 1024):
    vis = img.visualize(min=0.0, max=0.3, gamma=1.2)

    url = vis.getThumbURL({
        "region": region,
        "dimensions": pixels,
        "format": "png"
    })

    r = requests.get(url, timeout=180)
    r.raise_for_status()

    with open(out_path, "wb") as f:
        f.write(r.content)

    print("✅ Saved:", out_path)


def download_sentinel2_for_h3(h3_id: str, name: str):
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    region = bounds_to_region(bounds)

    rgb = get_s2_rgb(region, START_DATE, END_DATE, cloud_max=CLOUD_MAX)

    out_path = os.path.join(OUT_DIR, f"{name}.png")
    download_png(rgb, region, out_path, pixels=PIXELS)

if __name__ == "__main__":
    ee_init()

    h3_id = "89395a4b213ffff"  # remplace par ton H3
    download_sentinel2_for_h3(h3_id, "Garden_city_sentinel2_rgb")