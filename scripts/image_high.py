import logging
import os
import sys
import re
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boto3

from utils.config_parser import get_config
from utils.logger import configure_logger


# Mots-clés fréquents de variantes "basse qualité"
LOW_QUALITY_MARKERS = ("thumb", "thumbnail", "small", "sm", "medium", "low", "preview")


def normalize_key_for_variants(key: str) -> str:
    """
    Si ton bucket contient plusieurs versions d'une même image (thumb/small/high),
    on normalise le nom pour regrouper les variantes.
    Exemple:
      photos/img_123_thumb.jpg  -> photos/img_123.jpg
      photos/img_123_small.webp -> photos/img_123.webp
    """
    dirname, filename = os.path.split(key)

    # retire des suffixes type _thumb, -small, .preview etc. avant l'extension
    base, ext = os.path.splitext(filename)
    base = re.sub(r"([_-])(thumb|thumbnail|small|sm|medium|low|preview)$", "", base, flags=re.IGNORECASE)

    return os.path.join(dirname, base + ext)


def is_low_quality_path(key: str) -> bool:
    """
    Ignore certains dossiers typiques de miniatures.
    Ajuste selon ta structure S3 (ex: 'thumbs/', 'previews/', etc.)
    """
    parts = key.lower().split("/")
    return any(p in ("thumb", "thumbs", "thumbnails", "previews", "preview") for p in parts)


def list_all_objects(client, bucket: str, prefix: str = ""):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj  # contient Key, Size, LastModified, ...


def download_best_images(base_data_dir: str, bucket: str, prefix: str = ""):
    """
    Télécharge la meilleure variante (la plus grosse Size) pour chaque image "logique".
    Si ton bucket n'a qu'une seule version par image, ça téléchargera tout normalement.
    """
    logging.info(f"Downloading best-quality images into {base_data_dir}/ (bucket={bucket}, prefix='{prefix}')...")

    client = boto3.client("s3")
    s3 = boto3.resource("s3")

    # 1) Lister et filtrer
    candidates = []
    for obj in list_all_objects(client, bucket=bucket, prefix=prefix):
        key = obj["Key"]

        # Skip "folders"
        if key.endswith("/"):
            continue

        # Optionnel: ne garder que les images
        if not key.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
            continue

        # Ignorer dossiers miniatures
        if is_low_quality_path(key):
            continue

        candidates.append(obj)

    if not candidates:
        logging.warning("No image objects found with given filters.")
        return

    # 2) Grouper par image "logique" et choisir la meilleure (plus grosse taille fichier)
    groups = defaultdict(list)
    for obj in candidates:
        key = obj["Key"]
        group_key = normalize_key_for_variants(key)
        groups[group_key].append(obj)

    # 3) Télécharger
    total_groups = len(groups)
    done = 0

    for logical_key, objs in groups.items():
        # Choix "meilleure qualité" : plus grande taille fichier
        best = max(objs, key=lambda o: o.get("Size", 0))
        best_key = best["Key"]
        best_size = best.get("Size", 0)

        done += 1
        logging.info(f"[{done}/{total_groups}] Downloading best: {best_key} (Size={best_size} bytes)")

        dest_pathname = os.path.join(base_data_dir, best_key)
        os.makedirs(os.path.dirname(dest_pathname), exist_ok=True)

        # Téléchargement S3 (ne recompress pas => qualité inchangée)
        s3.meta.client.download_file(bucket, best_key, dest_pathname)

    logging.info("Done.")


if __name__ == "__main__":
    boto3.set_stream_logger("", logging.ERROR)
    configure_logger(("boto3", "CRITICAL"))

    config = get_config()

    # Si tu sais où sont les originaux, mets un prefix:
    # ex: prefix="images/original/" ou "dataset/high_res/"
    prefix = getattr(config, "prefix", "")  # optionnel si tu l'ajoutes à ton config

    download_best_images(config.base_data_dir, config.bucket, prefix=prefix)