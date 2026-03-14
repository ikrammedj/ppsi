from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from overpass_features import (
    clean_osm_duplicates,
    compute_population_proxy_features,
    load_building_counts_map,
    osm_tabular_from_h3,
)


def compute_features_for_h3(h3_id: str, building_count_value: int = 0, sleep_sec: float = 0.0) -> dict:
    df_raw = osm_tabular_from_h3(h3_id, sleep_sec=sleep_sec)

    if df_raw.empty:
        empty_features = compute_population_proxy_features(
            df_other=pd.DataFrame(),
            h3_id=h3_id,
            df_roads=pd.DataFrame(),
            df_all=pd.DataFrame(),
            building_count_value=building_count_value,
        )
        row = empty_features.iloc[0].to_dict()
        row["h3index"] = row.pop("h3_id")
        row["fetch_error"] = ""
        return row

    df_clean, _ = clean_osm_duplicates(
        df_raw,
        distance_threshold_m=40,
        fuzzy_threshold=0.82,
        same_name_distance_m=80,
        strong_brand_distance_m=100,
    )

    has_highway = df_clean["highway"].notna() & (df_clean["highway"].astype(str).str.strip() != "")
    df_roads = df_clean[has_highway].copy()
    df_other = df_clean[~has_highway].copy()

    df_features = compute_population_proxy_features(
        df_other=df_other,
        h3_id=h3_id,
        df_roads=df_roads,
        df_all=df_clean,
        building_count_value=building_count_value,
    )

    row = df_features.iloc[0].to_dict()
    row["h3index"] = row.pop("h3_id")
    row["fetch_error"] = ""
    return row


def run_batch(
    input_csv: Path,
    output_csv: Path,
    building_count_csv: Path | None,
    sleep_sec: float,
    workers: int = 16,
) -> None:
    df_input = pd.read_csv(input_csv)
    if "h3index" not in df_input.columns:
        raise ValueError("Le fichier CSV doit contenir la colonne 'h3index'.")

    df_input["h3index"] = df_input["h3index"].astype(str).str.strip()
    unique_h3 = [h for h in df_input["h3index"].dropna().unique() if h]

    if building_count_csv is not None:
        building_map = load_building_counts_map(building_count_csv)
    else:
        building_map = {}

    feature_rows: list[dict] = []

    workers = max(1, workers)
    print(f"Traitement parallèle des h3index avec {workers} workers.")

    def _safe_compute(h3_id_local: str) -> dict:
        try:
            building_count_value = int(building_map.get(h3_id_local, 0))
            return compute_features_for_h3(
                h3_id_local,
                building_count_value=building_count_value,
                sleep_sec=sleep_sec,
            )
        except Exception as exc:
            return {
                "h3index": h3_id_local,
                "fetch_error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_h3 = {
            executor.submit(_safe_compute, h3_id): h3_id
            for h3_id in unique_h3
        }

        done_count = 0
        total_h3 = len(unique_h3)
        for future in as_completed(future_to_h3):
            h3_id = future_to_h3[future]
            row = future.result()
            feature_rows.append(row)
            done_count += 1
            print(f"[{done_count}/{total_h3}] h3index={h3_id} terminé")

    df_features = pd.DataFrame(feature_rows)

    overlap_cols = [c for c in df_features.columns if c in df_input.columns and c != "h3index"]
    if overlap_cols:
        df_input = df_input.drop(columns=overlap_cols)

    df_out = df_input.merge(df_features, on="h3index", how="left")
    df_out.to_csv(output_csv, index=False, encoding="utf-8")

    print(f"Terminé. Fichier généré: {output_csv}")
    print(f"Lignes entrée: {len(df_input)} | h3 uniques traités: {len(unique_h3)}")


def main() -> None:
    default_building_csv = Path(__file__).resolve().parent / "building_count_88.csv"

    parser = argparse.ArgumentParser(
        description="Lit un CSV avec h3index, calcule les features Overpass par h3, et concatène avec les colonnes existantes."
    )
    parser.add_argument("--input", required=True, help="Chemin du CSV d'entrée (doit contenir h3index).")
    parser.add_argument("--output", default="", help="Chemin du CSV de sortie. Défaut: <input>_with_features.csv")
    parser.add_argument(
        "--building-count-csv",
        default=str(default_building_csv),
        help="Chemin vers un CSV contenant h3index,building_count (défaut: building_count_88.csv).",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.0,
        help="Pause (secondes) entre appels API Overpass (défaut: 0).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(32, (os.cpu_count() or 8) * 4),
        help="Nombre de workers parallèles pour les h3index (défaut: auto).",
    )

    args = parser.parse_args()

    input_csv = Path(args.input).resolve()
    if not input_csv.exists():
        raise FileNotFoundError(f"Fichier introuvable: {input_csv}")

    if args.output.strip():
        output_csv = Path(args.output).resolve()
    else:
        output_csv = input_csv.with_name(f"{input_csv.stem}_with_features.csv")

    building_csv = Path(args.building_count_csv).resolve() if args.building_count_csv.strip() else None
    if building_csv is not None and not building_csv.exists():
        print(f"Info: fichier building count non trouvé ({building_csv}), building_count=0 sera utilisé.")
        building_csv = None

    run_batch(
        input_csv=input_csv,
        output_csv=output_csv,
        building_count_csv=building_csv,
        sleep_sec=args.sleep_sec,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
