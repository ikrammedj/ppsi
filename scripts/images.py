# h3_to_sentinel2_image.py
# pip install earthengine-api h3 shapely requests

import ee
import h3
import requests
from shapely.geometry import Polygon

def h3_to_polygon_lonlat(h3_id: str) -> Polygon:
    """
    Retourne un Polygon shapely en (lon, lat) à partir d'une cellule H3.
    Compatible avec plusieurs versions de h3-py.
    """
    if hasattr(h3, "cell_to_boundary"):
        boundary = h3.cell_to_boundary(h3_id)  # -> liste de (lat, lon) dans ta version
    else:
        boundary = h3.h3_to_geo_boundary(h3_id, geo_json=False)  # v3

    # Convertit (lat, lon) -> (lon, lat)
    coords_lonlat = [(lon, lat) for (lat, lon) in boundary]
    return Polygon(coords_lonlat)

def get_sentinel2_rgb_for_h3(
    h3_id: str,
    start_date: str = "2025-01-01",
    end_date: str = "2025-12-31",
    cloud_pct_max: float = 20,
    out_png: str = "h3_s2.png",
    pixel_size_m: int = 10,
):
    """
    Télécharge un PNG RGB (True Color) Sentinel-2 sur la zone H3.
    - start_date/end_date: "YYYY-MM-DD"
    - cloud_pct_max: filtre sur CLOUDY_PIXEL_PERCENTAGE
    """
    # Init Earth Engine (si première fois: lance une fois ee.Authenticate() dans un terminal/colab)
    try:
        ee.Initialize(project="population-prediction")
    except Exception:
        ee.Authenticate()
        ee.Initialize(project="population-prediction")

    poly = h3_to_polygon_lonlat(h3_id)
    ee_geom = ee.Geometry.Polygon(list(poly.exterior.coords))

    # Collection Sentinel-2 SR harmonisée
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(ee_geom)
           .filterDate(start_date, end_date)
           .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_pct_max)))

    # Si tu veux “la meilleure image”, tu peux remplacer median() par .sort(...).first()
    img = col.median().clip(ee_geom)

    # RGB: B4,B3,B2 (True color)
    rgb = img.select(["B4", "B3", "B2"])

    # Visualisation (valeurs SR typiques ~0..3000/4000 ; ajuste si besoin)
    vis = {"min": 0, "max": 3000}

    # Génère un lien PNG (thumbnail) et télécharge
    url = rgb.visualize(**vis).getThumbURL({
        "region": ee_geom,
        "scale": 5,
        "format": "png"
    })

    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_png, "wb") as f:
        f.write(r.content)

    return out_png

if __name__ == "__main__":
    # Exemple: remplace par TON hexagone H3
    H3_ID = "88395a4991fffff"
    path = get_sentinel2_rgb_for_h3(
        H3_ID,
        start_date="2025-06-01",
        end_date="2025-09-30",
        cloud_pct_max=15,
        out_png="my_hex_sentinel2.png"
    )
    print("Saved:", path)