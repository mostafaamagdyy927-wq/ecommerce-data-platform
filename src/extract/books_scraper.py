
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = "RetailLens-Educational-Scraper/1.0"

rating_map = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5
}

# Check robots.txt
robots = RobotFileParser()
robots.set_url(urljoin(BASE_URL, "robots.txt"))
robots.read()

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

all_books = []
page_url = BASE_URL
page_number = 1
visited_pages = set()

scraped_at = datetime.now(timezone.utc).isoformat()

while page_url:

    if page_url in visited_pages:
        raise RuntimeError("Repeated page detected")

    visited_pages.add(page_url)

    if not robots.can_fetch(USER_AGENT, page_url):
        raise RuntimeError(f"Scraping not permitted: {page_url}")

    print(f"Scraping page {page_number}...")

    response = session.get(page_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")

    books = soup.select("article.product_pod")

    if not books:
        raise RuntimeError(f"No books found: {page_url}")

    for book in books:
        link = book.select_one("h3 a")
        rating_element = book.select_one(".star-rating")

        rating = None

        if rating_element:
            rating = next(
                (rating_map[c] for c in rating_element["class"]
                 if c in rating_map),
                None
            )

        all_books.append({
            "title": link["title"],
            "price": book.select_one(
                ".price_color"
            ).get_text(strip=True),
            "currency": "GBP",
            "rating": rating,
            "availability": book.select_one(
                ".availability"
            ).get_text(" ", strip=True),
            "product_url": urljoin(page_url, link["href"]),
            "source": "books.toscrape.com",
            "scraped_at": scraped_at
        })

    print(f"Total collected: {len(all_books)}")

    # Find the next page
    next_button = soup.select_one("li.next a")

    if next_button:
        page_url = urljoin(page_url, next_button["href"])
        page_number += 1
        time.sleep(1)
    else:
        page_url = None

# Save dataset
output = Path("data/raw/books_raw.json")
output.parent.mkdir(parents=True, exist_ok=True)

output.write_text(
    json.dumps(all_books, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

unique_urls = len({
    book["product_url"] for book in all_books
})

print("-------------------------")
print("Scraping Completed!")
print(f"Pages: {page_number}")
print(f"Total Books: {len(all_books)}")
print(f"Unique URLs: {unique_urls}")
print(f"Saved to: {output}")

if len(all_books) != 1000 or unique_urls != len(all_books):
    print("WARNING: Review dataset completeness or duplicates.")
