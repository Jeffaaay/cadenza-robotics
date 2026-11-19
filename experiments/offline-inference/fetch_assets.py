"""Fetch the public, immutable model/data snapshots listed in sources.lock.json."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import requests


def checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    lock = Path(__file__).with_name("sources.lock.json")
    manifest = json.loads(lock.read_text(encoding="utf-8"))

    def fetch(item):
        source = manifest["sources"][item["alias"]]
        path = args.assets / item["alias"] / item["path"]
        if path.is_file() and checksum(path) == item["sha256"]:
            return
        prefix = "datasets/" if source["kind"] == "dataset" else ""
        url = f"https://huggingface.co/{prefix}{source['repo']}/resolve/{source['revision']}/{item['path']}"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with requests.get(url, stream=True, timeout=(30, 180)) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for block in response.iter_content(1024 * 1024):
                    output.write(block)
        if temporary.stat().st_size != item["bytes"] or checksum(temporary) != item["sha256"]:
            raise ValueError(f"Download integrity failure: {item['alias']}/{item['path']}")
        temporary.replace(path)
        print(f"Verified {item['alias']}/{item['path']}", flush=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, manifest["files"]))
    (args.assets / "manifest.json").write_bytes(lock.read_bytes())


if __name__ == "__main__":
    main()
