import os
import time
import requests
import h3
from urllib.parse import urlencode
from pyproj import Transformer

OUT = "ppsi/images/esri_images"
os.makedirs(OUT, exist_ok=True)

BASE = "https://tiledbasemaps.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/export"

PX = 1024                 # taille image finale
FORMAT = "jpg"            # jpg ou png
PADDING_RATIO = 0.08      # même logique que Bing
REQUEST_TIMEOUT = 120

# ✅ token via variable d'environnement
ESRI_TOKEN = os.getenv("ESRI_TOKEN", "")
if not ESRI_TOKEN:
    print("⚠️ ESRI_TOKEN non défini. Exemple Mac: export ESRI_TOKEN='TON_TOKEN'")


WGS84_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)  # lon,lat -> x,y (m)
MERC_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)  # x,y -> lon,lat


def h3_to_square_bounds_latlon(h3_id: str, padding_ratio: float = 0.08):
    boundary = h3.cell_to_boundary(h3_id)  # [(lat, lon), ...]

    xs, ys = [], []
    for lat, lon in boundary:
        x, y = WGS84_TO_MERC.transform(lon, lat)  # lon,lat
        xs.append(x)
        ys.append(y)

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2

    half = max((xmax - xmin), (ymax - ymin)) / 2
    half *= (1.0 + padding_ratio)

    sxmin, sxmax = cx - half, cx + half
    symin, symax = cy - half, cy + half

    lon_min, lat_min = MERC_TO_WGS84.transform(sxmin, symin)
    lon_max, lat_max = MERC_TO_WGS84.transform(sxmax, symax)

    return lon_min, lat_min, lon_max, lat_max


def latlon_bounds_to_mercator_bbox(bounds_latlon):
    lon_min, lat_min, lon_max, lat_max = bounds_latlon
    xmin, ymin = WGS84_TO_MERC.transform(lon_min, lat_min)
    xmax, ymax = WGS84_TO_MERC.transform(lon_max, lat_max)
    return xmin, ymin, xmax, ymax

def download_esri_from_bounds(bounds_latlon, out_name: str, px: int = 1024, fmt: str = "jpg"):
    xmin, ymin, xmax, ymax = latlon_bounds_to_mercator_bbox(bounds_latlon)

    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{px},{px}",
        "format": fmt,
        "f": "image",
        "token": ESRI_TOKEN
    }

    url = BASE + "?" + urlencode(params)
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    path = os.path.join(OUT, f"{out_name}.{fmt}")
    with open(path, "wb") as f:
        f.write(r.content)

    print("✅ Saved:", path)


def download_esri_square_from_h3(h3_id: str, out_name: str):
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    download_esri_from_bounds(bounds, out_name, px=PX, fmt=FORMAT)


if __name__ == "__main__":
    h3_id = "89395a4b213ffff"
    download_esri_square_from_h3(h3_id, "Garden_city_esri_square_like_bing")