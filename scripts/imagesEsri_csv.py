import os
import re
import csv
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import h3
from urllib.parse import urlencode
from pyproj import Transformer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CSV_FILE = "population_dz.csv"
OUT = "images_pop"

BASE = "https://tiledbasemaps.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/export"

PX = 1024
FORMAT = "jpg"
PADDING_RATIO = 0.08

REQUEST_TIMEOUT = (10, 40)

MAX_WORKERS = 20

MAX_ATTEMPTS = 3

RETRY_BASE_SLEEP = 1.5

ESRI_TOKEN = "AAPTaCvN5vHpu07q3U6Xu_rTDNg..r8nTPmHDSwzdUMG0d-XdqoWis9sR9HO7iYBj1zGKFZ0mxffDA9t6tbpUztjQSnF3f1kds0J5DnTkupbs9zSrWVCWTRhzxRqVISgrh_M1qIvK_LTUSCRM0F8f9ucXrkUJPl9XMTbcmm6DmZ3wsoVlSr6frrojVpyKwU403KC95ZmVeCZb_jHdPiyHb1QfGWxEh4g0oqXFkke9AdsYQQBiJiMGACaRjk75xOOLcPkXenOk9mOvFLMC-iigIg..AT1_J1fxR9uB"

FAILED_CSV = "failed_h3.csv"


os.makedirs(OUT, exist_ok=True)

WGS84_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
MERC_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

print_lock = threading.Lock()
failed_lock = threading.Lock()
counter_lock = threading.Lock()

progress = {
    "done": 0,
    "saved": 0,
    "skipped": 0,
    "failed": 0,
    "total": 0
}


def log(*args):
    with print_lock:
        print(*args, flush=True)


def safe_name(text: str) -> str:
    text = str(text).strip().upper()
    text = text.replace(" ", "_")
    text = re.sub(r"[^\w\-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text


def make_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 Python requests dataset downloader"
    })

    return session


SESSION = make_session()


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


def latlon_bounds_to_mercator_bbox(bounds_latlon):
    lon_min, lat_min, lon_max, lat_max = bounds_latlon
    xmin, ymin = WGS84_TO_MERC.transform(lon_min, lat_min)
    xmax, ymax = WGS84_TO_MERC.transform(lon_max, lat_max)
    return xmin, ymin, xmax, ymax


def build_export_url(bounds_latlon):
    xmin, ymin, xmax, ymax = latlon_bounds_to_mercator_bbox(bounds_latlon)

    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{PX},{PX}",
        "format": FORMAT,
        "f": "image",
    }

    token = ESRI_TOKEN.strip()
    if token:
        params["token"] = token

    return BASE + "?" + urlencode(params)


def is_valid_image_response(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    return "image" in content_type


def save_stream_to_file(response: requests.Response, out_path: str):
    tmp_path = out_path + ".tmp"

    with open(tmp_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise ValueError("Image vide ou trop petite")

    os.replace(tmp_path, out_path)


def append_failed_row(h3_id: str, wilaya: str, reason: str):
    with failed_lock:
        file_exists = os.path.exists(FAILED_CSV)

        with open(FAILED_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["h3index", "wilaya", "reason"])
            writer.writerow([h3_id, wilaya, reason])


def download_one_image(h3_id: str, wilaya: str, out_path: str) -> bool:
    bounds = h3_to_square_bounds_latlon(h3_id, padding_ratio=PADDING_RATIO)
    url = build_export_url(bounds)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True) as r:
                if r.status_code != 200:
                    preview = ""
                    try:
                        preview = r.text[:200]
                    except Exception:
                        preview = "<body illisible>"
                    log(f"❌ HTTP {r.status_code} | {h3_id} | attempt {attempt} | {preview}")
                    time.sleep(RETRY_BASE_SLEEP * attempt)
                    continue

                if not is_valid_image_response(r):
                    preview = ""
                    try:
                        preview = r.text[:200]
                    except Exception:
                        preview = "<body illisible>"
                    log(f"❌ Non-image | {h3_id} | attempt {attempt} | {preview}")
                    time.sleep(RETRY_BASE_SLEEP * attempt)
                    continue

                save_stream_to_file(r, out_path)
                return True

        except requests.exceptions.ReadTimeout:
            log(f"⏱️ Read timeout | {h3_id} | attempt {attempt}")
            time.sleep(RETRY_BASE_SLEEP * attempt)

        except requests.exceptions.ConnectTimeout:
            log(f"⏱️ Connect timeout | {h3_id} | attempt {attempt}")
            time.sleep(RETRY_BASE_SLEEP * attempt)

        except requests.exceptions.RequestException as e:
            log(f"❌ Network error | {h3_id} | attempt {attempt} | {e}")
            time.sleep(RETRY_BASE_SLEEP * attempt)

        except Exception as e:
            log(f"❌ Error | {h3_id} | attempt {attempt} | {e}")
            time.sleep(RETRY_BASE_SLEEP * attempt)

    append_failed_row(h3_id, wilaya, "download_failed")
    return False


def process_row(row):
    h3_id = str(row["h3index"]).strip()
    wilaya = safe_name(row["Wilaya_58"])

    wilaya_folder = os.path.join(OUT, wilaya)
    os.makedirs(wilaya_folder, exist_ok=True)

    out_path = os.path.join(wilaya_folder, f"{h3_id}.{FORMAT}")

    # anti-duplication
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        with counter_lock:
            progress["done"] += 1
            progress["skipped"] += 1
            done = progress["done"]
            total = progress["total"]
        log(f"[{done}/{total}] Skip: {out_path}")
        return

    # si fichier corrompu existant
    if os.path.exists(out_path):
        try:
            if os.path.getsize(out_path) <= 1024:
                os.remove(out_path)
        except Exception:
            pass

    success = download_one_image(h3_id, wilaya, out_path)

    with counter_lock:
        progress["done"] += 1
        if success:
            progress["saved"] += 1
        else:
            progress["failed"] += 1

        done = progress["done"]
        total = progress["total"]
        saved = progress["saved"]
        skipped = progress["skipped"]
        failed = progress["failed"]

    if success:
        log(f"[{done}/{total}] ✅ Saved: {out_path} | saved={saved} skipped={skipped} failed={failed}")
    else:
        log(f"[{done}/{total}] ❌ Failed: {h3_id} | saved={saved} skipped={skipped} failed={failed}")


def main():
    start_time = time.time()

    log("Loading CSV...")
    df = pd.read_csv(CSV_FILE)

    required_cols = ["h3index", "Wilaya_58"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Colonne manquante dans le CSV: {col}")

    df = df.dropna(subset=["h3index", "Wilaya_58"]).copy()
    df = df.drop_duplicates(subset=["h3index"]).reset_index(drop=True)

    progress["total"] = len(df)

    log(f"Total H3 uniques: {len(df)}")
    log(f"MAX_WORKERS = {MAX_WORKERS}")

    rows = df.to_dict(orient="records")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_row, row) for row in rows]

            for _ in as_completed(futures):
                pass

    except KeyboardInterrupt:
        log("\n⛔ Arrêt manuel détecté.")
        log("Les fichiers déjà téléchargés restent sauvegardés.")
        raise

    elapsed = time.time() - start_time
    mins = elapsed / 60
    
    log(f"Saved   : {progress['saved']}")
    log(f"Skipped : {progress['skipped']}")
    log(f"Failed  : {progress['failed']}")
    log(f"Temps   : {mins:.2f} minutes")


if __name__ == "__main__":
    main()
