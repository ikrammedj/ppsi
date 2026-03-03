import os
import time
import random
import requests
import mercantile
import h3
from PIL import Image
from io import BytesIO
from pyproj import Transformer

OUTPUT_FOLDER = "ppsi/images/bing_images"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

ZOOM = 18                 
FINAL_SIZE = 1024         
SLEEP_BETWEEN_TILES = 0.12
PADDING_RATIO = 0.08     

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/605.1.15"
})

ECN_HOSTS = [
    "ecn.t0.tiles.virtualearth.net",
    "ecn.t1.tiles.virtualearth.net",
    "ecn.t2.tiles.virtualearth.net",
    "ecn.t3.tiles.virtualearth.net",
]

def tile_url(x, y, z):
    quadkey = mercantile.quadkey(x, y, z)
    host = random.choice(ECN_HOSTS)
    return f"https://{host}/tiles/a{quadkey}.jpeg?g=1"

def download_tile(x, y, z, retries=6, timeout=45):
    last_err = None
    for attempt in range(retries):
        try:
            url = tile_url(x, y, z)
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")
        except Exception as e:
            last_err = e
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"Failed tile ({x},{y},{z}). Last error: {last_err}")


WGS84_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
MERC_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

def h3_to_square_bounds_latlon(h3_id: str, padding_ratio: float = 0.08):
    """
    Retourne un bbox CARRE (lon_min, lat_min, lon_max, lat_max) qui englobe l'hexagone H3,
    en se basant sur un bbox carré en mètres (EPSG:3857) => effet "carré rouge" sur la carte.
    """
    
    boundary = h3.cell_to_boundary(h3_id)

    # convertit en mètres (x,y)
    xs, ys = [], []
    for lat, lon in boundary:
        x, y = WGS84_TO_MERC.transform(lon, lat)
        xs.append(x); ys.append(y)

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    # centre
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2

    # on force un CARRÉ : on prend le plus grand côté
    half = max((xmax - xmin), (ymax - ymin)) / 2

    # padding (le carré rouge est souvent un peu plus grand)
    half *= (1.0 + padding_ratio)

    # bbox carré en mètres
    sxmin, sxmax = cx - half, cx + half
    symin, symax = cy - half, cy + half

    # reconvertir en lat/lon
    lon_min, lat_min = MERC_TO_WGS84.transform(sxmin, symin)
    lon_max, lat_max = MERC_TO_WGS84.transform(sxmax, symax)

    return lon_min, lat_min, lon_max, lat_max

def download_bing_square_from_bounds(bounds, name):
    lon_min, lat_min, lon_max, lat_max = bounds

    # toutes les tuiles qui couvrent le bbox
    tiles = list(mercantile.tiles(lon_min, lat_min, lon_max, lat_max, [ZOOM]))
    if not tiles:
        raise RuntimeError("Aucune tuile trouvée pour ce bbox (vérifie bounds/zoom).")

    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    width_tiles = x_max - x_min + 1
    height_tiles = y_max - y_min + 1

    big = Image.new("RGB", (width_tiles * 256, height_tiles * 256))

    for t in tiles:
        img = download_tile(t.x, t.y, t.z)
        px = (t.x - x_min) * 256
        py = (t.y - y_min) * 256
        big.paste(img, (px, py))
        time.sleep(SLEEP_BETWEEN_TILES)

    # On crop un carré central (ça “nettoie” et garantit carré)
    w, h = big.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cropped = big.crop((left, top, left + side, top + side))

    final_img = cropped.resize((FINAL_SIZE, FINAL_SIZE), Image.Resampling.BICUBIC)
    out_path = os.path.join(OUTPUT_FOLDER, f"{name}.jpg")
    final_img.save(out_path, quality=95)
    print("✅ Saved:", out_path)

def download_bing_square_from_h3(h3_id: str, out_name: str):
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    download_bing_square_from_bounds(bounds, out_name)


if __name__ == "__main__":
    h3_id = "89395a4b213ffff" 
    download_bing_square_from_h3(h3_id, "Garden_city_18")