#!/usr/bin/env python3
"""Download a Geofabrik OpenStreetMap extract with integrity verification.

The script only acquires source data. It never imports, transforms, or deletes
records in PostGIS, so it is safe to run before the OSM import pipeline exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_REGION = "shanghai"
DEFAULT_BASE_URL = "https://download.geofabrik.de/asia/china"
CHUNK_SIZE = 1024 * 1024
USER_AGENT = "GenTrip/1.0 (local OSM data acquisition)"


def extract_url(base_url: str, region: str) -> str:
    return f"{base_url.rstrip('/')}/{region}-latest.osm.pbf"


def md5_url(data_url: str) -> str:
    return f"{data_url}.md5"


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def remote_md5(data_url: str) -> str:
    value = request_bytes(md5_url(data_url)).decode("utf-8").strip().split()[0]
    if len(value) != 32 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError(f"Invalid MD5 response from {md5_url(data_url)}")
    return value.lower()


def file_md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec B324 - Geofabrik publishes MD5 integrity files.
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download(data_url: str, destination: Path, expected_md5: str, *, force: bool) -> bool:
    if destination.exists() and not force:
        actual_md5 = file_md5(destination)
        if actual_md5 == expected_md5:
            print(f"Already verified: {destination}")
            return False
        raise RuntimeError(
            f"Existing file checksum differs: {destination}. Use --force to replace it."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(data_url, headers={"User-Agent": USER_AGENT})
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{destination.name}.", suffix=".part", dir=destination.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                expected_size = response.headers.get("Content-Length")
                downloaded = 0
                while chunk := response.read(CHUNK_SIZE):
                    temporary.write(chunk)
                    downloaded += len(chunk)
                    if expected_size:
                        print(f"\rDownloaded {downloaded / 1024 / 1024:.1f}/{int(expected_size) / 1024 / 1024:.1f} MiB", end="", flush=True)
            print()
            temporary.flush()
            os.fsync(temporary.fileno())
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    actual_md5 = file_md5(temporary_path)
    if actual_md5 != expected_md5:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch: expected {expected_md5}, received {actual_md5}")
    temporary_path.replace(destination)
    return True


def write_manifest(destination: Path, *, data_url: str, checksum: str) -> None:
    manifest = {
        "source": "OpenStreetMap via Geofabrik",
        "data_url": data_url,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "file": destination.name,
        "bytes": destination.stat().st_size,
        "md5": checksum,
        "coordinate_reference_system": "WGS84 (EPSG:4326)",
        "license": "ODbL-1.0; attribute OpenStreetMap contributors",
    }
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest written: {manifest_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and verify a Geofabrik OSM PBF extract.")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Geofabrik region filename prefix (default: shanghai).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Geofabrik directory URL.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/osm"), help="Destination directory.")
    parser.add_argument("--force", action="store_true", help="Replace an existing file whose checksum differs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_url = extract_url(args.base_url, args.region)
    destination = args.output_dir / f"{args.region}-latest.osm.pbf"
    try:
        checksum = remote_md5(data_url)
        changed = download(data_url, destination, checksum, force=args.force)
        write_manifest(destination, data_url=data_url, checksum=checksum)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError, RuntimeError) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1
    if changed:
        print(f"Verified OSM extract: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
