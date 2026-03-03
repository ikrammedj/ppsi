# pip install h3 pandas requests
import time
import requests
import pandas as pd
import h3

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def h3_to_overpass_poly(h3_id: str) -> str:
    boundary = h3.cell_to_boundary(h3_id)
    return " ".join([f"{lat} {lon}" for (lat, lon) in boundary])

def overpass_query(poly_str: str) -> str:
    return f"""
    [out:json][timeout:60];
    (
      // POI (amenity/shop/tourism/office)
      nwr(poly:"{poly_str}")["amenity"];
      nwr(poly:"{poly_str}")["shop"];
      nwr(poly:"{poly_str}")["tourism"];
      nwr(poly:"{poly_str}")["office"];

      // Bâtiments
      nwr(poly:"{poly_str}")["building"];

      // building:levels (souvent sur des buildings)
      nwr(poly:"{poly_str}")["building:levels"];

      // Routes
      way(poly:"{poly_str}")["highway"];

      // Landuse (résidentiel, commercial, etc.)
      nwr(poly:"{poly_str}")["landuse"];

      // Natural (water, woodland, etc.)
      nwr(poly:"{poly_str}")["natural"];
    );
    out tags center;
    """

def fetch_overpass_data(query: str) -> dict:
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
    r.raise_for_status()
    return r.json()

def elements_to_table(osm_json: dict, h3_id: str) -> pd.DataFrame:
    rows = []
    for el in osm_json.get("elements", []):
        tags = el.get("tags", {}) or {}

        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")

        rows.append({
            "h3_id": h3_id,
            "osm_type": el.get("type"),
            "osm_id": el.get("id"),
            "lat": lat,
            "lon": lon,

            "name": tags.get("name"),
            "amenity": tags.get("amenity"),
            "shop": tags.get("shop"),
            "tourism": tags.get("tourism"),
            "office": tags.get("office"),
            "building": tags.get("building"),
            "building_levels": tags.get("building:levels"),
            "highway": tags.get("highway"),
            "landuse": tags.get("landuse"),
            "natural": tags.get("natural"),

            "tags": tags,
        })

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.dropna(subset=["lat", "lon"], how="any").reset_index(drop=True)

        if "building_levels" in df.columns:
            df["building_levels"] = pd.to_numeric(df["building_levels"], errors="coerce")

    return df

def osm_tabular_from_h3(h3_id: str, sleep_sec: float = 0.2) -> pd.DataFrame:
    poly = h3_to_overpass_poly(h3_id)
    q = overpass_query(poly)
    data = fetch_overpass_data(q)
    time.sleep(sleep_sec)
    return elements_to_table(data, h3_id)

if __name__ == "__main__":
    h3_id = "88382994abfffff"

    df = osm_tabular_from_h3(h3_id)

    print("Rows:", len(df))
    print(df.head(10)[[
        "h3_id","osm_type","osm_id","name",
        "amenity","shop","building","building_levels",
        "highway","landuse","natural","lat","lon"
    ]])

    df.to_csv(f"osm_{h3_id}.csv", index=False, encoding="utf-8")
    print("Saved:", f"osm_{h3_id}.csv")