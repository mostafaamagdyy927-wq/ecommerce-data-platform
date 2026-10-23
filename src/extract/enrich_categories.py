
import json
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# Files
input_file = Path("data/raw/books_raw.json")
output_file = Path("data/raw/books_with_categories.json")

# Load original books
books = json.loads(input_file.read_text(encoding="utf-8"))

# Resume previous progress
if output_file.exists():
    enriched = json.loads(
        output_file.read_text(encoding="utf-8")
    )
else:
    enriched = []

completed = {
    book["product_url"] for book in enriched
    if book.get("category")
}

session = requests.Session()
user_agent = "RetailLens-Educational-Scraper/1.0"
session.headers.update({"User-Agent": user_agent})

robots = RobotFileParser()
robots.set_url("https://books.toscrape.com/robots.txt")
robots.read()

def save_progress():
    # Write safely through a temporary file
    temp = output_file.with_suffix(".tmp")
    temp.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp.replace(output_file)

try:
    for index, book in enumerate(books, start=1):
        url = book["product_url"]

        if url in completed:
            continue

        if not robots.can_fetch(user_agent, url):
            raise RuntimeError(f"Scraping not permitted: {url}")

        response = session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select("ul.breadcrumb li a")

        if len(links) < 3:
            raise ValueError(f"Category not found: {url}")

        category = links[-1].get_text(strip=True)

        enriched_book = book.copy()
        enriched_book["category"] = category

        enriched.append(enriched_book)
        completed.add(url)

        print(f"[{index}/{len(books)}] {category}")

        # Save after every 10 books
        if len(enriched) % 10 == 0:
            save_progress()

        time.sleep(1)

finally:
    save_progress()
    print("-------------------------")
    print(f"Saved books: {len(enriched)}")
    print(f"File: {output_file}")

if len(enriched) == len(books):
    print("All categories collected successfully!")
