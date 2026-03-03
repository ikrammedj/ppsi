# landsat_h3_square_png.py

import os
import ee
import h3
import requests
from io import BytesIO

OUT_DIR = "ppsi/images/landsat_images"
os.makedirs(OUT_DIR, exist_ok=True)

START_DATE = "2025-01-01"
END_DATE   = "2025-12-31"
CLOUD_MAX  = 40            
PADDING_RATIO = 0.08      
PIXELS = 1024              
SCALE_M = 30               

def ee_init():
    try:
        ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize()

def h3_to_square_bounds_latlon(h3_id: str, padding_ratio: float = 0.08):
    # boundary: [(lat, lon), ...]
    boundary = h3.cell_to_boundary(h3_id)

    lats = [lat for lat, lon in boundary]
    lons = [lon for lat, lon in boundary]

    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    # centre
    clat = (lat_min + lat_max) / 2
    clon = (lon_min + lon_max) / 2

    # force carré: prend le plus grand côté (en degrés, approx OK pour petite zone)
    half_lat = (lat_max - lat_min) / 2
    half_lon = (lon_max - lon_min) / 2
    half = max(half_lat, half_lon) * (1.0 + padding_ratio)

    return (clon - half, clat - half, clon + half, clat + half)  # (lon_min, lat_min, lon_max, lat_max)

def bounds_to_ee_region(bounds):
    lon_min, lat_min, lon_max, lat_max = bounds
    return ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max], proj="EPSG:4326", geodesic=False)

def mask_landsat_clouds(img: ee.Image) -> ee.Image:
    # QA_PIXEL bits (Collection 2 L2)
    qa = img.select("QA_PIXEL")

    # bits: 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow
    dilated = qa.bitwiseAnd(1 << 1).neq(0)
    cirrus  = qa.bitwiseAnd(1 << 2).neq(0)
    cloud   = qa.bitwiseAnd(1 << 3).neq(0)
    shadow  = qa.bitwiseAnd(1 << 4).neq(0)

    mask = dilated.Or(cirrus).Or(cloud).Or(shadow).Not()
    return img.updateMask(mask)

def scale_landsat_sr(img: ee.Image) -> ee.Image:
    # SR_B* scale/offset (Landsat C2 L2)
    # reflectance = SR * 0.0000275 + (-0.2)
    optical = img.select(["SR_B2","SR_B3","SR_B4"]).multiply(0.0000275).add(-0.2)
    return img.addBands(optical, overwrite=True)

def get_landsat_rgb(region: ee.Geometry, start_date: str, end_date: str, cloud_max: int = 40) -> ee.Image:
    l8 = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
          .filterBounds(region)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lte("CLOUD_COVER", cloud_max))
          .map(mask_landsat_clouds)
          .map(scale_landsat_sr))

    l9 = (ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
          .filterBounds(region)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lte("CLOUD_COVER", cloud_max))
          .map(mask_landsat_clouds)
          .map(scale_landsat_sr))

    col = l8.merge(l9)

    # composite médian
    comp = col.median()

    # RGB Landsat: B4=Red, B3=Green, B2=Blue
    rgb = comp.select(["SR_B4","SR_B3","SR_B2"]).clamp(0, 0.3)

    return rgb

def download_png(img: ee.Image, region: ee.Geometry, out_path: str, pixels: int = 1024):
    # visualize (stretch)
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


def download_landsat_for_h3(h3_id: str, name: str):
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    region = bounds_to_ee_region(bounds)

    rgb = get_landsat_rgb(region, START_DATE, END_DATE, cloud_max=CLOUD_MAX)

    out_path = os.path.join(OUT_DIR, f"{name}.png")
    download_png(rgb, region, out_path, pixels=PIXELS)

if __name__ == "__main__":
    ee_init()

    h3_id = "89395a4b213ffff"  # <-- remplace par ton H3
    download_landsat_for_h3(h3_id, "Garden_city_landsat_rgb")