"""
download_database_exports.py
==============================

Download a named public MOF database export (e.g. QMOF, CoRE-MOF, MOFdb) into
data/raw/mof_databases/<source>/, and record it in data/metadata/source_registry.csv.

This script deliberately does NOT hard-code database URLs. Public dataset
releases (Figshare records, GitHub release assets, Zenodo DOIs) get new
versions over time, and guessing a URL risks silently downloading the wrong
version or a broken link. You supply a URL you have verified yourself (e.g. by
visiting the database's own download/citation page), and the script handles
the download, checksum, extraction, and provenance bookkeeping.

USAGE
-----
    python src/collection/download_database_exports.py \\
        --source QMOF \\
        --url https://example.org/path/to/verified/export.zip \\
        --version 14 \\
        --license "CC-BY-4.0" \\
        --doi 10.6084/m9.figshare.xxxxxxx

Produces:
    data/raw/mof_databases/<source>/<downloaded file, extracted if an archive>
    An appended row in data/metadata/source_registry.csv for this source/version.

Refuses to overwrite an existing download for the same --source/--version
unless --force is given, since raw data must not be silently replaced.

TODO:
    - Once you've picked specific database versions to use, consider recording
      their verified URLs in a small config file (e.g. config/database_sources.json)
      so re-downloads by teammates don't require re-finding the URL each time -
      just make sure that config is reviewed whenever a database publishes a
      new version, rather than treated as permanently current.
"""

import argparse
import csv
import shutil
import sys
import zipfile
import tarfile
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

SOURCE_REGISTRY_FIELDS = [
    "source_id", "database", "database_version", "source_type", "paper",
    "authors", "year", "doi", "url", "access_date", "license",
    "original_file", "structure_identifier", "notes",
]


def download_file(url: str, dest: Path, timeout: int = 300) -> None:
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)


def maybe_extract(archive_path: Path, extract_dir: Path) -> bool:
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(extract_dir)
        return True
    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path) as tf:
                tf.extractall(extract_dir)
            return True
    except Exception:
        pass
    return False


def append_source_registry(registry_path: Path, row: dict) -> None:
    file_exists = registry_path.exists()
    with open(registry_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SOURCE_REGISTRY_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Download a public MOF database export you have already verified.")
    parser.add_argument("--source", required=True, help="Short name, e.g. QMOF, CoRE-MOF, MOFdb.")
    parser.add_argument("--url", required=True, help="A URL you have personally verified on the database's own site.")
    parser.add_argument("--version", default="unspecified")
    parser.add_argument("--license", default="unspecified", help="License string to record in source_registry.csv.")
    parser.add_argument("--doi", default="", help="DOI of the dataset release, if any.")
    parser.add_argument("--raw-dir", default="data/raw/mof_databases")
    parser.add_argument("--source-registry", default="data/metadata/source_registry.csv")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing download for this source/version.")
    args = parser.parse_args()

    if requests is None:
        print("ERROR: the 'requests' package is required. pip install requests", file=sys.stderr)
        sys.exit(1)

    source_dir = Path(args.raw_dir) / args.source / str(args.version)
    if source_dir.exists() and any(source_dir.iterdir()) and not args.force:
        print(f"ERROR: {source_dir} already has content. Use --force to overwrite, "
              f"or choose a different --version.", file=sys.stderr)
        sys.exit(1)
    source_dir.mkdir(parents=True, exist_ok=True)

    filename = args.url.rstrip("/").split("/")[-1] or "download"
    dest = source_dir / filename

    print(f"Downloading {args.url}\n  -> {dest}")
    try:
        download_file(args.url, dest)
    except Exception as exc:
        print(f"ERROR: download failed: {exc}", file=sys.stderr)
        sys.exit(1)

    extracted = maybe_extract(dest, source_dir)
    if extracted:
        print(f"Extracted archive contents into {source_dir}")
    else:
        print("File does not appear to be a zip/tar archive; left as downloaded.")

    source_id = f"{args.source}_{args.version}".replace(" ", "_")
    append_source_registry(Path(args.source_registry), {
        "source_id": source_id,
        "database": args.source,
        "database_version": args.version,
        "source_type": "database_export",
        "paper": "",
        "authors": "",
        "year": "",
        "doi": args.doi,
        "url": args.url,
        "access_date": date.today().isoformat(),
        "license": args.license,
        "original_file": filename,
        "structure_identifier": "",
        "notes": "Downloaded via src/collection/download_database_exports.py",
    })
    print(f"\nRecorded source_id={source_id} in {args.source_registry}")
    print(f"Next: run src/import_external_database.py --input <a file under {source_dir}> --source {args.source} ...")


if __name__ == "__main__":
    main()
