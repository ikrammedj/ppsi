import os
import requests
import h3
from PIL import Image
from io import BytesIO
from pyproj import Transformer

# =========================
# CONFIG
# =========================

MAPBOX_TOKEN = "pk.eyJ1IjoiYmFkb3VobSIsImEiOiJjbW1haGNlbXcwZDV1MnByNGVqNXYzb2cwIn0.as5JxLTkj6b-soccvcI8mA"
OUTPUT_FOLDER = "images/mapbox_images"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

FINAL_SIZE = 1024
PADDING_RATIO = 0.08

# =========================
# PROJECTIONS
# =========================

WGS84_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
MERC_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

# =========================
# H3 -> BBOX CARRE
# =========================

def h3_to_square_bounds_latlon(h3_id: str, padding_ratio: float = 0.08):

    boundary = h3.cell_to_boundary(h3_id)

    xs, ys = [], []
    for lat, lon in boundary:
        x, y = WGS84_TO_MERC.transform(lon, lat)
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

# =========================
# DOWNLOAD MAPBOX IMAGE
# =========================

def download_mapbox_square_from_bounds(bounds, name):

    lon_min, lat_min, lon_max, lat_max = bounds

    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"[{lon_min},{lat_min},{lon_max},{lat_max}]"
        f"/{FINAL_SIZE}x{FINAL_SIZE}"
        f"?access_token={MAPBOX_TOKEN}"
    )

    response = requests.get(url)
    response.raise_for_status()

    img = Image.open(BytesIO(response.content)).convert("RGB")

    out_path = os.path.join(OUTPUT_FOLDER, f"{name}.jpg")
    img.save(out_path, quality=95)

    print("✅ Saved:", out_path)

# =========================
# MAIN
# =========================

def download_mapbox_square_from_h3(h3_id: str, out_name: str):
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    download_mapbox_square_from_bounds(bounds, out_name)


if __name__ == "__main__":
    h3_id = "89395a4b213ffff"
    download_mapbox_square_from_h3(h3_id, "Garden_city_18")