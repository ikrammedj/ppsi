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
      way(poly:"{poly_str}")["highway"];
      nwr(poly:"{poly_str}")["landuse"];
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
    for col in ["amenity", "shop", "tourism", "office", "building", "highway", "landuse", "natural"]:
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


def merge_two_rows(base: pd.Series, other: pd.Series) -> pd.Series:
    merged = base.copy()

    cols_priority = [
        "name", "amenity", "shop", "tourism", "office",
        "building", "building_levels", "highway", "landuse", "natural",
        "brand", "operator"
    ]

    for col in cols_priority:
        base_val = merged.get(col)
        other_val = other.get(col)

        if (pd.isna(base_val) or str(base_val).strip() == "") and pd.notna(other_val) and str(other_val).strip() != "":
            merged[col] = other_val

    tags1 = merged.get("tags", {}) if isinstance(merged.get("tags", {}), dict) else {}
    tags2 = other.get("tags", {}) if isinstance(other.get("tags", {}), dict) else {}

    merged_tags = dict(tags1)
    for k, v in tags2.items():
        if k not in merged_tags or pd.isna(merged_tags[k]) or str(merged_tags[k]).strip() == "":
            merged_tags[k] = v

    merged["tags"] = merged_tags

    if pd.isna(merged.get("name")) or str(merged.get("name")).strip() == "":
        merged["name"] = get_tag_value(
            merged_tags, "name", "name:fr", "name:ar", "brand", "brand:fr", "brand:ar"
        )

    if pd.isna(merged.get("amenity")) or str(merged.get("amenity")).strip() == "":
        val = get_tag_value(merged_tags, "amenity")
        if val:
            merged["amenity"] = val

    if pd.isna(merged.get("shop")) or str(merged.get("shop")).strip() == "":
        val = get_tag_value(merged_tags, "shop")
        if val:
            merged["shop"] = val

    if pd.isna(merged.get("tourism")) or str(merged.get("tourism")).strip() == "":
        val = get_tag_value(merged_tags, "tourism")
        if val:
            merged["tourism"] = val

    if pd.isna(merged.get("office")) or str(merged.get("office")).strip() == "":
        val = get_tag_value(merged_tags, "office")
        if val:
            merged["office"] = val

    if pd.isna(merged.get("building")) or str(merged.get("building")).strip() == "":
        val = get_tag_value(merged_tags, "building")
        if val:
            merged["building"] = val

    if pd.isna(merged.get("landuse")) or str(merged.get("landuse")).strip() == "":
        val = get_tag_value(merged_tags, "landuse")
        if val:
            merged["landuse"] = val

    if pd.isna(merged.get("natural")) or str(merged.get("natural")).strip() == "":
        val = get_tag_value(merged_tags, "natural")
        if val:
            merged["natural"] = val

    if pd.isna(merged.get("highway")) or str(merged.get("highway")).strip() == "":
        val = get_tag_value(merged_tags, "highway")
        if val:
            merged["highway"] = val

    if pd.isna(merged.get("building_levels")) or str(merged.get("building_levels")).strip() == "":
        val = get_tag_value(merged_tags, "building:levels")
        if val:
            merged["building_levels"] = pd.to_numeric(val, errors="coerce")

    if pd.isna(merged.get("brand")) or str(merged.get("brand")).strip() == "":
        merged["brand"] = get_tag_value(merged_tags, "brand", "brand:fr", "brand:ar")

    if pd.isna(merged.get("operator")) or str(merged.get("operator")).strip() == "":
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


# =========================
# 4) Exemple d'utilisation
# =========================
if __name__ == "__main__":
    h3_id = "88395a4831fffff"

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

    print(df_clean.head(10)[[
        "h3_id", "osm_type", "osm_id", "name", "brand", "operator",
        "amenity", "shop", "building", "building_levels",
        "highway", "landuse", "natural", "lat", "lon",
        "merged_count", "merged_from"
    ]])

    df.to_csv(f"osm_raw_{h3_id}.csv", index=False, encoding="utf-8")
    df_clean.to_csv(f"osm_clean_{h3_id}.csv", index=False, encoding="utf-8")
    df_groups.to_csv(f"osm_merge_groups_{h3_id}.csv", index=False, encoding="utf-8")

    print("Saved:", f"osm_raw_{h3_id}.csv")
    print("Saved:", f"osm_clean_{h3_id}.csv")
    print("Saved:", f"osm_merge_groups_{h3_id}.csv")