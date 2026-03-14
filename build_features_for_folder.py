from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from build_features_from_csv import run_batch


def _process_one_csv(
    csv_file: Path,
    output_dir: Path,
    building_count_csv: Path | None,
    sleep_sec: float,
    h3_workers: int,
) -> tuple[Path, Path]:
    output_file = output_dir / f"{csv_file.stem}_features.csv"
    run_batch(
        input_csv=csv_file,
        output_csv=output_file,
        building_count_csv=building_count_csv,
        sleep_sec=sleep_sec,
        workers=h3_workers,
    )
    return csv_file, output_file


def process_folder(
    input_dir: Path,
    output_dir: Path,
    building_count_csv: Path | None,
    sleep_sec: float,
    workers: int,
    h3_workers: int,
) -> None:
    if not input_dir.exists():
        raise FileNotFoundError(f"Dossier introuvable: {input_dir}")

    csv_files = sorted(p for p in input_dir.glob("*.csv") if p.is_file())
    if not csv_files:
        raise ValueError(f"Aucun fichier CSV trouvé dans: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(csv_files)
    pending_csv_files: list[Path] = []
    for csv_file in csv_files:
        output_file = output_dir / f"{csv_file.stem}_features.csv"
        if output_file.exists():
            print(f"{output_file.name} existe déjà → skip")
            continue
        pending_csv_files.append(csv_file)

    if not pending_csv_files:
        print("Tous les fichiers existent déjà, rien à traiter.")
        return

    workers = max(1, workers)
    print(f"Lancement parallèle avec {workers} workers sur {len(pending_csv_files)} fichiers.")

    done_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_csv = {
            executor.submit(
                _process_one_csv,
                csv_file,
                output_dir,
                building_count_csv,
                sleep_sec,
                h3_workers,
            ): csv_file
            for csv_file in pending_csv_files
        }

        for future in as_completed(future_to_csv):
            csv_file = future_to_csv[future]
            try:
                _, output_file = future.result()
                done_count += 1
                print(f"OK: {csv_file.name} -> {output_file.name} ({done_count}/{len(pending_csv_files)})")
            except Exception as exc:
                failed_count += 1
                print(f"ERREUR: {csv_file.name} -> {exc}")

    print(
        f"\nTerminé. Total={total}, traités={done_count}, erreurs={failed_count}, sortie={output_dir}"
    )

    if failed_count:
        raise RuntimeError(f"{failed_count} fichier(s) en échec pendant le traitement parallèle.")


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    default_input_dir = project_dir / "wilayas_csv"
    default_output_dir = project_dir / "wilayas_with_features"
    default_building_csv = project_dir / "building_count_88.csv"

    parser = argparse.ArgumentParser(
        description="Traite tous les CSV d'un dossier et génère un fichier <nom>_features.csv pour chacun."
    )
    parser.add_argument(
        "--input-dir",
        default=str(default_input_dir),
        help="Dossier contenant les CSV source (défaut: wilayas_csv).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output_dir),
        help="Dossier de sortie (défaut: wilayas_with_features).",
    )
    parser.add_argument(
        "--building-count-csv",
        default=str(default_building_csv),
        help="CSV des building counts (défaut: building_count_88.csv).",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.0,
        help="Pause entre appels API Overpass en secondes (défaut: 0.01).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Nombre de workers parallèles (défaut: 8).",
    )
    parser.add_argument(
        "--h3-workers",
        type=int,
        default=16,
        help="Nombre de workers parallèles h3index par fichier (défaut: 16).",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    building_count_csv = Path(args.building_count_csv).resolve() if args.building_count_csv.strip() else None

    if building_count_csv is not None and not building_count_csv.exists():
        print(f"Info: fichier building count non trouvé ({building_count_csv}), building_count=0 sera utilisé.")
        building_count_csv = None

    process_folder(
        input_dir=input_dir,
        output_dir=output_dir,
        building_count_csv=building_count_csv,
        sleep_sec=args.sleep_sec,
        workers=args.workers,
        h3_workers=args.h3_workers,
    )


if __name__ == "__main__":
    main()
