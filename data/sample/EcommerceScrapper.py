
import csv
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


URL = "https://scrapingsandbox.com/"
OUTPUT_FILE = Path(__file__).with_name("products.csv")


def extract_products(page):
    """Extract product title, category, and price from the current page."""

    soup = BeautifulSoup(page.content(), "html.parser")
    products = []

    for title_element in soup.select(".product-name"):
        # Walk up the HTML tree until we find the product card
        card = title_element

        while card is not None:
            if card.select_one(".category") and card.select_one(".price"):
                break
            card = card.parent

        if card is None:
            continue

        category_element = card.select_one(".category")
        price_element = card.select_one(".price")

        if not category_element or not price_element:
            continue

        products.append({
            "Title": title_element.get_text(strip=True),
            "Category": category_element.get_text(strip=True),
            "Price": price_element.get_text(" ", strip=True),
        })

    return products


def get_page_signature(page):
    """Return visible product titles to detect page changes."""
    return tuple(
        title.inner_text().strip()
        for title in page.locator(".product-name").all()
    )


def main():
    all_products = []
    seen_products = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            print("Opening website...")

            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.locator(".product-name").first.wait_for(timeout=30000)

            page_number = 1

            while True:
                page.wait_for_timeout(500)

                products = extract_products(page)
                new_count = 0

                for product in products:
                    # Use all fields to avoid accidentally merging
                    # different products that share a title.
                    key = (
                        product["Title"],
                        product["Category"],
                        product["Price"],
                    )

                    if key not in seen_products:
                        seen_products.add(key)
                        all_products.append(product)
                        new_count += 1

                print(
                    f"Page {page_number}: "
                    f"{new_count} new products | "
                    f"Total collected: {len(all_products)}"
                )

                previous_signature = get_page_signature(page)

                # Find visible numbered pagination buttons
                numbered_buttons = page.locator(
                    'button[data-slot="button"]'
                ).filter(
                    has_text=re.compile(r"^\s*\d+\s*$")
                )

                next_button = None

                for button in numbered_buttons.all():
                    text = button.inner_text().strip()

                    if not text.isdigit():
                        continue

                    number = int(text)

                    # Choose the smallest number greater than
                    # the current page number.
                    if number > page_number:
                        if (
                            next_button is None
                            or number < next_button[0]
                        ):
                            next_button = (number, button)

                if next_button is None:
                    print(
                        "No higher numbered page button found. "
                        "Stopping pagination."
                    )
                    break

                next_page_number, button = next_button

                if not button.is_enabled():
                    print("Next page button is disabled.")
                    break

                button.click()

                try:
                    page.wait_for_function(
                        """previous => {
                            const current = Array.from(
                                document.querySelectorAll('.product-name')
                            ).map(el => el.innerText.trim());

                            return current.length > 0 &&
                                JSON.stringify(current) !==
                                JSON.stringify(previous);
                        }""",
                        arg=list(previous_signature),
                        timeout=15000,
                    )
                except PlaywrightTimeoutError:
                    print(
                        "Product list did not change after clicking. "
                        "Stopping to avoid an infinite loop."
                    )
                    break

                page_number = next_page_number

        finally:
            browser.close()

    # Save all collected products to CSV
    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        fieldnames = ["Title", "Category", "Price"]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(all_products)

    print("\nScraping finished.")
    print(f"Total unique products: {len(all_products)}")
    print(f"CSV saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
