# pip install pandas requests h3
import time
import math
import ast
import re
import unicodedata
from difflib import SequenceMatcher

import requests
import pandas as pd
import h3

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# =========================
# 1) Récupération OSM
# =========================
def h3_to_overpass_poly(h3_id: str) -> str:
    boundary = h3.cell_to_boundary(h3_id)
    return " ".join([f"{lat} {lon}" for (lat, lon) in boundary])


def overpass_query(poly_str: str) -> str:
    return f"""
    [out:json][timeout:60];
    (
      nwr(poly:"{poly_str}")["amenity"];
      nwr(poly:"{poly_str}")["shop"];
      nwr(poly:"{poly_str}")["tourism"];
      nwr(poly:"{poly_str}")["office"];
      nwr(poly:"{poly_str}")["building"];
      nwr(poly:"{poly_str}")["building:levels"];
      nwr(poly:"{poly_str}")["landuse"];
      nwr(poly:"{poly_str}")["natural"];
            nwr(poly:"{poly_str}")["leisure"];
            nwr(poly:"{poly_str}")["historic"];
            nwr(poly:"{poly_str}")["railway"];
    );
    out tags center;
        way(poly:"{poly_str}")["highway"];
        out tags geom;
    """


def fetch_overpass_data(query: str) -> dict:
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
    r.raise_for_status()
    return r.json()


def elements_to_table(osm_json: dict, h3_id: str) -> pd.DataFrame:
    rows = []

    for el in osm_json.get("elements", []):
        tags = el.get("tags", {}) or {}

        geometry = el.get("geometry")

        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
            if (lat is None or lon is None) and isinstance(geometry, list) and geometry:
                lats = [p.get("lat") for p in geometry if isinstance(p, dict) and p.get("lat") is not None]
                lons = [p.get("lon") for p in geometry if isinstance(p, dict) and p.get("lon") is not None]
                if lats and lons:
                    lat = sum(lats) / len(lats)
                    lon = sum(lons) / len(lons)

        road_length_m = None
        if tags.get("highway") and isinstance(geometry, list) and len(geometry) >= 2:
            seg_len = 0.0
            for p1, p2 in zip(geometry[:-1], geometry[1:]):
                if (
                    isinstance(p1, dict) and isinstance(p2, dict)
                    and p1.get("lat") is not None and p1.get("lon") is not None
                    and p2.get("lat") is not None and p2.get("lon") is not None
                ):
                    seg_len += haversine_m(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
            road_length_m = seg_len

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
            "leisure": tags.get("leisure"),
            "historic": tags.get("historic"),
            "railway": tags.get("railway"),
            "road_length_m": road_length_m,
            "geometry": geometry,
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


# =========================
# 2) Helpers nettoyage
# =========================
def safe_parse_tags(x):
    if isinstance(x, dict):
        return x
    if pd.isna(x):
        return {}
    x = str(x).strip()
    if not x:
        return {}
    try:
        return ast.literal_eval(x)
    except Exception:
        return {}


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    if pd.isna(text) or not str(text).strip():
        return ""
    s = str(text).strip().lower()
    s = strip_accents(s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_name(name: str) -> str:
    s = normalize_text(name)
    if not s:
        return ""

    stopwords = {
        "mall", "centre", "center", "shopping",
        "station", "service", "fuel", "petrol", "gas",
        "algerie", "algérie"
    }
    tokens = [t for t in s.split() if t not in stopwords]
    return " ".join(tokens).strip()


def get_tag_value(tags: dict, *keys) -> str:
    if not isinstance(tags, dict):
        return ""
    for k in keys:
        v = tags.get(k)
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    return ""


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def best_name_similarity_from_lists(names1, names2) -> float:
    if not names1 or not names2:
        return 0.0

    best = 0.0
    for a in names1:
        for b in names2:
            sim = name_similarity(a, b)
            if sim > best:
                best = sim
    return best


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    aa = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(aa), math.sqrt(1 - aa))


def pick_category(row) -> str:
    for col in [
        "amenity", "shop", "tourism", "office", "building",
        "highway", "landuse", "natural", "leisure", "historic", "railway"
    ]:
        val = row.get(col)
        if pd.notna(val) and str(val).strip() != "":
            return f"{col}:{val}"
    return "unknown"


def categories_compatible(c1: str, c2: str) -> bool:
    if c1 == c2:
        return True

    if c1 == "unknown" or c2 == "unknown":
        return True

    if c1.startswith("building:") and c2 != "unknown":
        return True

    if c2.startswith("building:") and c1 != "unknown":
        return True

    commercial_like = {"shop:mall", "landuse:retail", "shop:supermarket", "shop:department_store"}
    if c1 in commercial_like and c2 in commercial_like:
        return True

    return False


def get_all_names(row) -> list:
    tags = row.get("tags", {}) if isinstance(row.get("tags", {}), dict) else {}

    candidates = [
        row.get("name"),
        tags.get("name"),
        tags.get("name:fr"),
        tags.get("name:ar"),
        tags.get("official_name"),
        tags.get("alt_name"),
        tags.get("short_name"),
        tags.get("brand"),
        tags.get("brand:fr"),
        tags.get("brand:ar"),
        tags.get("operator"),
    ]

    out = []
    for x in candidates:
        nx = normalize_name(x)
        if nx and nx not in out:
            out.append(nx)

    return out


def get_brand_operator_keys(row):
    tags = row.get("tags", {}) if isinstance(row.get("tags", {}), dict) else {}

    brand = normalize_name(get_tag_value(tags, "brand", "brand:fr", "brand:ar"))
    operator_ = normalize_name(get_tag_value(tags, "operator", "operator:fr", "operator:ar"))

    return brand, operator_


def non_null_count(row) -> int:
    cols = [
        "name", "amenity", "shop", "tourism", "office",
        "building", "building_levels", "highway", "landuse", "natural",
        "leisure", "historic", "railway",
        "brand", "operator"
    ]
    score = 0

    for c in cols:
        v = row.get(c)
        if pd.notna(v) and str(v).strip() != "":
            score += 1

    tags = row.get("tags", {})
    if isinstance(tags, dict):
        score += len(tags) * 0.1

    return score


def is_blank_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return False
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def merge_two_rows(base: pd.Series, other: pd.Series) -> pd.Series:
    merged = base.copy()

    cols_priority = [
        "name", "amenity", "shop", "tourism", "office",
        "building", "building_levels", "highway", "landuse", "natural",
        "leisure", "historic", "railway", "road_length_m", "geometry",
        "brand", "operator"
    ]

    for col in cols_priority:
        base_val = merged.get(col)
        other_val = other.get(col)

        if is_blank_value(base_val) and not is_blank_value(other_val):
            merged[col] = other_val

    tags1 = merged.get("tags", {}) if isinstance(merged.get("tags", {}), dict) else {}
    tags2 = other.get("tags", {}) if isinstance(other.get("tags", {}), dict) else {}

    merged_tags = dict(tags1)
    for k, v in tags2.items():
        if k not in merged_tags or is_blank_value(merged_tags[k]):
            merged_tags[k] = v

    merged["tags"] = merged_tags

    if is_blank_value(merged.get("name")):
        merged["name"] = get_tag_value(
            merged_tags, "name", "name:fr", "name:ar", "brand", "brand:fr", "brand:ar"
        )

    if is_blank_value(merged.get("amenity")):
        val = get_tag_value(merged_tags, "amenity")
        if val:
            merged["amenity"] = val

    if is_blank_value(merged.get("shop")):
        val = get_tag_value(merged_tags, "shop")
        if val:
            merged["shop"] = val

    if is_blank_value(merged.get("tourism")):
        val = get_tag_value(merged_tags, "tourism")
        if val:
            merged["tourism"] = val

    if is_blank_value(merged.get("office")):
        val = get_tag_value(merged_tags, "office")
        if val:
            merged["office"] = val

    if is_blank_value(merged.get("building")):
        val = get_tag_value(merged_tags, "building")
        if val:
            merged["building"] = val

    if is_blank_value(merged.get("landuse")):
        val = get_tag_value(merged_tags, "landuse")
        if val:
            merged["landuse"] = val

    if is_blank_value(merged.get("natural")):
        val = get_tag_value(merged_tags, "natural")
        if val:
            merged["natural"] = val

    if is_blank_value(merged.get("leisure")):
        val = get_tag_value(merged_tags, "leisure")
        if val:
            merged["leisure"] = val

    if is_blank_value(merged.get("historic")):
        val = get_tag_value(merged_tags, "historic")
        if val:
            merged["historic"] = val

    if is_blank_value(merged.get("railway")):
        val = get_tag_value(merged_tags, "railway")
        if val:
            merged["railway"] = val

    if is_blank_value(merged.get("highway")):
        val = get_tag_value(merged_tags, "highway")
        if val:
            merged["highway"] = val

    if is_blank_value(merged.get("building_levels")):
        val = get_tag_value(merged_tags, "building:levels")
        if val:
            merged["building_levels"] = pd.to_numeric(val, errors="coerce")

    if is_blank_value(merged.get("brand")):
        merged["brand"] = get_tag_value(merged_tags, "brand", "brand:fr", "brand:ar")

    if is_blank_value(merged.get("operator")):
        merged["operator"] = get_tag_value(merged_tags, "operator", "operator:fr", "operator:ar")

    return merged


# =========================
# 3) Détection / fusion doublons
# =========================
def are_probable_duplicates_fast(
    r1,
    r2,
    distance_threshold_m=35,
    fuzzy_threshold=0.85,
    same_name_distance_m=60,
    strong_brand_distance_m=80
):
    d = haversine_m(r1["lat"], r1["lon"], r2["lat"], r2["lon"])

    max_d = max(distance_threshold_m, same_name_distance_m, strong_brand_distance_m)
    if d > max_d:
        return False

    c1 = r1["main_category"]
    c2 = r2["main_category"]
    same_cat = categories_compatible(c1, c2)

    same_brand = bool(r1["brand_norm"] and r2["brand_norm"] and r1["brand_norm"] == r2["brand_norm"])
    same_operator = bool(r1["operator_norm"] and r2["operator_norm"] and r1["operator_norm"] == r2["operator_norm"])

    same_wikidata = bool(r1["wikidata_norm"] and r2["wikidata_norm"] and r1["wikidata_norm"] == r2["wikidata_norm"])
    same_website = bool(r1["website_norm"] and r2["website_norm"] and r1["website_norm"] == r2["website_norm"])
    same_phone = bool(r1["phone_norm"] and r2["phone_norm"] and r1["phone_norm"] == r2["phone_norm"])

    if same_wikidata and d <= strong_brand_distance_m:
        return True

    if same_website and d <= strong_brand_distance_m:
        return True

    if (same_brand or same_operator) and d <= strong_brand_distance_m:
        return True

    if same_phone and d <= strong_brand_distance_m:
        return True

    sim = best_name_similarity_from_lists(r1["all_names"], r2["all_names"])

    if sim >= fuzzy_threshold and d <= distance_threshold_m and same_cat:
        return True

    names1 = set(r1["all_names"])
    names2 = set(r2["all_names"])
    if names1 and names2 and names1.intersection(names2) and d <= same_name_distance_m and same_cat:
        return True

    if d <= distance_threshold_m and (same_brand or sim >= fuzzy_threshold):
        if (
            c1.startswith("building:") or c2.startswith("building:")
            or c1 == "unknown" or c2 == "unknown"
        ):
            return True

    mall_like = {"shop:mall", "landuse:retail"}
    if d <= distance_threshold_m and sim >= fuzzy_threshold:
        if c1 in mall_like and c2 in mall_like:
            return True

    return False


def clean_osm_duplicates(
    df: pd.DataFrame,
    distance_threshold_m=35,
    fuzzy_threshold=0.85,
    same_name_distance_m=60,
    strong_brand_distance_m=80
):
    if df.empty:
        return df.copy(), pd.DataFrame()

    df = df.copy()
    df["tags"] = df["tags"].apply(safe_parse_tags)

    def fill_from_tags(row, col, *tag_keys):
        val = row.get(col)
        if pd.notna(val) and str(val).strip() != "":
            return val
        tags = row.get("tags", {})
        return get_tag_value(tags, *tag_keys)

    df["name"] = df.apply(
        lambda r: fill_from_tags(r, "name", "name", "name:fr", "name:ar", "brand", "brand:fr", "brand:ar"),
        axis=1
    )
    df["amenity"] = df.apply(lambda r: fill_from_tags(r, "amenity", "amenity"), axis=1)
    df["shop"] = df.apply(lambda r: fill_from_tags(r, "shop", "shop"), axis=1)
    df["tourism"] = df.apply(lambda r: fill_from_tags(r, "tourism", "tourism"), axis=1)
    df["office"] = df.apply(lambda r: fill_from_tags(r, "office", "office"), axis=1)
    df["building"] = df.apply(lambda r: fill_from_tags(r, "building", "building"), axis=1)
    df["highway"] = df.apply(lambda r: fill_from_tags(r, "highway", "highway"), axis=1)
    df["landuse"] = df.apply(lambda r: fill_from_tags(r, "landuse", "landuse"), axis=1)
    df["natural"] = df.apply(lambda r: fill_from_tags(r, "natural", "natural"), axis=1)
    df["leisure"] = df.apply(lambda r: fill_from_tags(r, "leisure", "leisure"), axis=1)
    df["historic"] = df.apply(lambda r: fill_from_tags(r, "historic", "historic"), axis=1)
    df["railway"] = df.apply(lambda r: fill_from_tags(r, "railway", "railway"), axis=1)

    df["brand"] = df["tags"].apply(lambda t: get_tag_value(t, "brand", "brand:fr", "brand:ar"))
    df["operator"] = df["tags"].apply(lambda t: get_tag_value(t, "operator", "operator:fr", "operator:ar"))

    if "building_levels" in df.columns:
        df["building_levels"] = df["building_levels"].fillna(
            df["tags"].apply(lambda t: pd.to_numeric(get_tag_value(t, "building:levels"), errors="coerce"))
        )

    df = df.drop_duplicates(subset=["osm_type", "osm_id"]).reset_index(drop=True)

    # pré-calculs
    df["name_norm"] = df["name"].apply(normalize_name)
    df["main_category"] = df.apply(pick_category, axis=1)
    df["info_score"] = df.apply(non_null_count, axis=1)
    df["all_names"] = df.apply(get_all_names, axis=1)

    df["brand_norm"] = df["brand"].apply(normalize_name)
    df["operator_norm"] = df["operator"].apply(normalize_name)

    df["wikidata_norm"] = df["tags"].apply(
        lambda t: normalize_text(get_tag_value(t, "wikidata", "brand:wikidata"))
    )
    df["website_norm"] = df["tags"].apply(
        lambda t: normalize_text(get_tag_value(t, "website", "contact:website", "brand:website"))
    )
    df["phone_norm"] = df["tags"].apply(
        lambda t: normalize_text(get_tag_value(t, "phone", "contact:phone"))
    )

    # tri spatial simple
    df = df.sort_values(["lat", "lon"]).reset_index(drop=True)

    # conversion distance mètres -> degrés latitude
    lat_buffer = max(distance_threshold_m, same_name_distance_m, strong_brand_distance_m) / 111320.0

    used = set()
    cleaned_rows = []
    groups = []

    for i in range(len(df)):
        if i in used:
            continue

        current = df.iloc[i].copy()
        group_indices = [i]
        used.add(i)

        lat_i = current["lat"]

        for j in range(i + 1, len(df)):
            if j in used:
                continue

            other = df.iloc[j]

            # arrêt anticipé si trop loin en latitude
            if other["lat"] - lat_i > lat_buffer:
                break

            if are_probable_duplicates_fast(
                current,
                other,
                distance_threshold_m=distance_threshold_m,
                fuzzy_threshold=fuzzy_threshold,
                same_name_distance_m=same_name_distance_m,
                strong_brand_distance_m=strong_brand_distance_m
            ):
                if other["info_score"] > current["info_score"]:
                    current, other = other.copy(), current.copy()

                current = merge_two_rows(current, other)

                # mise à jour des champs dérivés après fusion
                current["name_norm"] = normalize_name(current.get("name"))
                current["main_category"] = pick_category(current)
                current["info_score"] = non_null_count(current)
                current["all_names"] = get_all_names(current)
                current["brand_norm"] = normalize_name(current.get("brand"))
                current["operator_norm"] = normalize_name(current.get("operator"))

                tags_cur = current.get("tags", {}) if isinstance(current.get("tags", {}), dict) else {}
                current["wikidata_norm"] = normalize_text(get_tag_value(tags_cur, "wikidata", "brand:wikidata"))
                current["website_norm"] = normalize_text(get_tag_value(tags_cur, "website", "contact:website", "brand:website"))
                current["phone_norm"] = normalize_text(get_tag_value(tags_cur, "phone", "contact:phone"))

                group_indices.append(j)
                used.add(j)

        group_df = df.iloc[group_indices]
        source_ids = [f"{r['osm_type']}/{r['osm_id']}" for _, r in group_df.iterrows()]
        source_names = [
            str(r["name"]) for _, r in group_df.iterrows()
            if pd.notna(r["name"]) and str(r["name"]).strip() != ""
        ]

        current["merged_from"] = " | ".join(source_ids)
        current["merged_count"] = len(group_indices)

        cleaned_rows.append(current)

        groups.append({
            "kept_osm_type": current["osm_type"],
            "kept_osm_id": current["osm_id"],
            "kept_name": current.get("name"),
            "merged_count": len(group_indices),
            "merged_from": " | ".join(source_ids),
            "source_names": " | ".join(source_names)
        })

    cleaned = pd.DataFrame(cleaned_rows).reset_index(drop=True)
    groups_df = pd.DataFrame(groups)

    cleaned = cleaned.drop(
        columns=[
            "name_norm", "main_category", "info_score", "all_names",
            "brand_norm", "operator_norm", "wikidata_norm", "website_norm", "phone_norm"
        ],
        errors="ignore"
    )

    return cleaned, groups_df

def compute_intersection_count(df_roads: pd.DataFrame) -> int:
    if df_roads.empty or "geometry" not in df_roads.columns:
        return 0

    node_to_way_ids: dict[tuple[float, float], set[str]] = {}

    for _, row in df_roads.iterrows():
        geom = row.get("geometry")
        if not isinstance(geom, list) or len(geom) < 2:
            continue

        way_id = f"{row.get('osm_type')}/{row.get('osm_id')}"
        for p in geom:
            if not isinstance(p, dict) or p.get("lat") is None or p.get("lon") is None:
                continue
            key = (round(float(p["lat"]), 6), round(float(p["lon"]), 6))
            node_to_way_ids.setdefault(key, set()).add(way_id)

    return int(sum(1 for ways in node_to_way_ids.values() if len(ways) >= 2))


def compute_population_proxy_features(
    df_other: pd.DataFrame,
    h3_id: str,
    df_roads: pd.DataFrame | None = None,
    df_all: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if df_roads is None:
        if df_all is not None and "highway" in df_all.columns:
            has_highway = df_all["highway"].notna() & (df_all["highway"].astype(str).str.strip() != "")
            df_roads = df_all[has_highway].copy()
        else:
            df_roads = pd.DataFrame()

    area_km2 = h3.cell_area(h3_id, unit="km^2")

    features = {
        "h3_id": h3_id,
        "school": 0,
        "university": 0,
        "college": 0,
        "kindergarten": 0,
        "library": 0,
        "hospital": 0,
        "clinic": 0,
        "pharmacy": 0,
        "health_offices": 0,
        "food_places": 0,
        "supermarket": 0,
        "marketplace": 0,
        "convenience": 0,
        "mall": 0,
        "retail_shops": 0,
        "place_of_worship": 0,
        "hotel": 0,
        "culture_places": 0,
        "park": 0,
        "stadium": 0,
        "sports_centre": 0,
        "post_office": 0,
        "police": 0,
        "fire_station": 0,
        "townhall": 0,
        "courthouse": 0,
        "bank": 0,
        "atm": 0,
        "bus_stop": 0,
        "station": 0,
        "parking": 0,
        "taxi": 0,
        "fuel": 0,
        "bus_station": 0,
        "train_station": 0,
        "primary_roads": 0,
        "secondary_roads": 0,
        "tertiary_roads": 0,
        "residential_roads": 0,
        "road_length_total": 0.0,
        "intersection_count": 0,
        "building_count": 0,
        "avg_building_levels": 0.0,
        "building_density": 0.0,
        "poi_total": 0,
        "shop_total": 0,
        "amenity_total": 0,
        "tourism_total": 0,
    }

    def cleaned_value_counts(df_local: pd.DataFrame, col: str) -> pd.Series:
        if col not in df_local.columns or df_local.empty:
            return pd.Series(dtype="int64")
        values = df_local[col].fillna("").astype(str).str.strip()
        values = values[values != ""]
        if values.empty:
            return pd.Series(dtype="int64")
        return values.value_counts()

    amenity_counts = cleaned_value_counts(df_other, "amenity")
    shop_counts = cleaned_value_counts(df_other, "shop")
    tourism_counts = cleaned_value_counts(df_other, "tourism")
    leisure_counts = cleaned_value_counts(df_other, "leisure")
    landuse_counts = cleaned_value_counts(df_other, "landuse")
    other_highway_counts = cleaned_value_counts(df_other, "highway")
    railway_counts = cleaned_value_counts(df_other, "railway")
    roads_highway_counts = cleaned_value_counts(df_roads, "highway")

    # Éducation
    features["school"] = int(amenity_counts.get("school", 0))
    features["university"] = int(amenity_counts.get("university", 0))
    features["college"] = int(amenity_counts.get("college", 0))
    features["kindergarten"] = int(amenity_counts.get("kindergarten", 0))
    features["library"] = int(amenity_counts.get("library", 0))

    # Santé
    features["hospital"] = int(amenity_counts.get("hospital", 0))
    features["clinic"] = int(amenity_counts.get("clinic", 0))
    features["pharmacy"] = int(amenity_counts.get("pharmacy", 0))
    features["health_offices"] = int(amenity_counts.get("doctors", 0) + amenity_counts.get("dentist", 0))

    # Restauration
    features["food_places"] = int(
        amenity_counts.get("restaurant", 0)
        + amenity_counts.get("cafe", 0)
        + amenity_counts.get("fast_food", 0)
        + amenity_counts.get("food_court", 0)
    )

    # Commerce
    features["supermarket"] = int(shop_counts.get("supermarket", 0))
    features["marketplace"] = int(amenity_counts.get("marketplace", 0) + shop_counts.get("marketplace", 0))
    features["convenience"] = int(shop_counts.get("convenience", 0))
    features["mall"] = int(shop_counts.get("mall", 0))
    features["retail_shops"] = int(
        shop_counts.get("clothes", 0)
        + shop_counts.get("bakery", 0)
        + shop_counts.get("butcher", 0)
        + shop_counts.get("electronics", 0)
        + shop_counts.get("general", 0)
    )

    # Religion
    features["place_of_worship"] = int(amenity_counts.get("place_of_worship", 0))

    # Tourisme / culture / sport
    features["hotel"] = int(tourism_counts.get("hotel", 0) + tourism_counts.get("guest_house", 0))
    features["culture_places"] = int(
        tourism_counts.get("museum", 0)
        + amenity_counts.get("museum", 0)
        + amenity_counts.get("theatre", 0)
        + amenity_counts.get("cinema", 0)
    )
    features["park"] = int(leisure_counts.get("park", 0) + landuse_counts.get("park", 0))
    features["stadium"] = int(leisure_counts.get("stadium", 0) + amenity_counts.get("stadium", 0))
    features["sports_centre"] = int(leisure_counts.get("sports_centre", 0) + amenity_counts.get("sports_centre", 0))

    # 7) Services publics
    features["post_office"] = int(amenity_counts.get("post_office", 0))
    features["police"] = int(amenity_counts.get("police", 0))
    features["fire_station"] = int(amenity_counts.get("fire_station", 0))
    features["townhall"] = int(amenity_counts.get("townhall", 0) + amenity_counts.get("town_hall", 0))
    features["courthouse"] = int(amenity_counts.get("courthouse", 0))
    features["bank"] = int(amenity_counts.get("bank", 0))
    features["atm"] = int(amenity_counts.get("atm", 0))

    # Transport
    features["bus_stop"] = int(other_highway_counts.get("bus_stop", 0))
    features["station"] = int(railway_counts.get("station", 0))
    features["parking"] = int(amenity_counts.get("parking", 0))
    features["taxi"] = int(amenity_counts.get("taxi", 0))
    features["fuel"] = int(amenity_counts.get("fuel", 0))
    features["bus_station"] = int(amenity_counts.get("bus_station", 0))
    features["train_station"] = int(railway_counts.get("station", 0) + railway_counts.get("halt", 0))

    # 9) Routes
    features["primary_roads"] = int(roads_highway_counts.get("primary", 0) + roads_highway_counts.get("primary_link", 0))
    features["secondary_roads"] = int(roads_highway_counts.get("secondary", 0) + roads_highway_counts.get("secondary_link", 0))
    features["tertiary_roads"] = int(roads_highway_counts.get("tertiary", 0) + roads_highway_counts.get("tertiary_link", 0))
    features["residential_roads"] = int(
        roads_highway_counts.get("residential", 0)
        + roads_highway_counts.get("living_street", 0)
        + roads_highway_counts.get("unclassified", 0)
    )

    if "road_length_m" in df_roads.columns:
        features["road_length_total"] = float(pd.to_numeric(df_roads["road_length_m"], errors="coerce").fillna(0).sum())

    features["intersection_count"] = compute_intersection_count(df_roads)

    # Features géographiques utiles
    features["building_count"] = int(cleaned_value_counts(df_other, "building").sum())
    if "building_levels" in df_other.columns:
        building_levels_numeric = pd.to_numeric(df_other["building_levels"], errors="coerce")
        has_building = df_other["building"].fillna("").astype(str).str.strip() != ""
        mean_levels = building_levels_numeric[has_building].mean()
        features["avg_building_levels"] = float(mean_levels) if pd.notna(mean_levels) else 0.0
    features["building_density"] = (features["building_count"] / area_km2) if area_km2 else 0.0

    poi_mask = pd.Series(False, index=df_other.index)
    for col in ["amenity", "shop", "tourism", "office", "leisure", "historic"]:
        if col in df_other.columns:
            poi_mask = poi_mask | (df_other[col].fillna("").astype(str).str.strip() != "")
    features["poi_total"] = int(poi_mask.sum())

    features["shop_total"] = int(shop_counts.sum())
    features["amenity_total"] = int(amenity_counts.sum())
    features["tourism_total"] = int(tourism_counts.sum())

    return pd.DataFrame([features])

# =========================
# 4) Exemple d'utilisation
# =========================
if __name__ == "__main__":
    h3_id = "88395a4819fffff"

    df = osm_tabular_from_h3(h3_id)
    print("Avant nettoyage:", len(df))

    df_clean, df_groups = clean_osm_duplicates(
        df,
        distance_threshold_m=40,
        fuzzy_threshold=0.82,
        same_name_distance_m=80,
        strong_brand_distance_m=100
    )

    print("Après nettoyage:", len(df_clean))
    print("Doublons fusionnés:", len(df) - len(df_clean))

    # =========================
    # Séparation routes / reste
    # =========================

    has_highway = df_clean["highway"].notna() & (df_clean["highway"].astype(str).str.strip() != "")
    df_roads = df_clean[has_highway].copy()
    df_other = df_clean[~has_highway].copy()
    df_features = compute_population_proxy_features(df_other, h3_id, df_roads=df_roads, df_all=df_clean)

    out_file = f"features_{h3_id}.csv"
    df_features.to_csv(out_file, index=False, encoding="utf-8")
    print("Saved:", out_file)