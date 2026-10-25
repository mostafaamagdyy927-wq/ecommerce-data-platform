import json
import time
from datetime import date
from pathlib import Path

import requests

URL = "https://makeup-api.herokuapp.com/api/v1/products.json"
SOURCE = "makeup_api"

try:
    ROOT = Path(__file__).resolve().parents[2]
except NameError:
    ROOT = Path.cwd()

RAW_DIR = ROOT / "data" / "raw"


def fetch_products(retries=3):
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(URL, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            print(f"Attempt {attempt}/{retries} failed: {exc}")
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def main():
    data = fetch_products()
    if not data:
        raise RuntimeError("API returned no products")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{SOURCE}_{date.today()}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(len(data), "products saved to", path)


if __name__ == "__main__":
    main()
