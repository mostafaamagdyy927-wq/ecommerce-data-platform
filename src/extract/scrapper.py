import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


URL = "https://scrapingsandbox.com/"
OUTPUT_FILE = Path(__file__).with_name("products.json")


def get_text(element, selectors):
    """Return text from the first matching selector."""
    if element is None:
        return None

    for selector in selectors:
        found = element.select_one(selector)
        if found:
            value = found.get_text(" ", strip=True)
            if value:
                return value

    return None


def get_price_value(value):
    """Convert a displayed price into an int or float."""
    if value is None:
        return None

    cleaned = re.sub(r"[^\d.,-]", "", str(value)).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    try:
        number = float(match.group())
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def get_image(card, page_url):
    """Extract a product image URL from a product card."""
    if card is None:
        return None

    image = card.select_one("img, [data-image]")
    if image:
        image_url = (
            image.get("src")
            or image.get("data-src")
            or image.get("data-lazy-src")
            or image.get("data-image")
        )

        if not image_url:
            srcset = image.get("srcset")
            if srcset:
                image_url = srcset.split(",")[0].strip().split()[0]

        if image_url:
            return urljoin(page_url, image_url)

    for element in card.select("[style]"):
        match = re.search(
            r"""background-image\s*:\s*url\(['"]?(.*?)['"]?\)""",
            element.get("style", ""),
            re.IGNORECASE,
        )
        if match:
            return urljoin(page_url, match.group(1))

    return None


def get_product_url(card, page_url):
    """Find the product details URL, preferably from the title's link."""
    title_element = card.select_one(
        ".product-name, .product-title, h2, h3"
    )

    anchor = None
    if title_element:
        anchor = title_element.find_parent("a", href=True)
        if anchor is None:
            anchor = title_element.select_one("a[href]")

    if anchor is None:
        anchor = card.select_one("a[href]")

    if anchor:
        href = anchor.get("href", "").strip()
        if href and not href.startswith(("javascript:", "#")):
            return urljoin(page_url, href)

    return None


def get_product_id(card, fallback_id):
    for attribute in ("data-id", "data-product-id", "id"):
        value = card.get(attribute)
        if value:
            match = re.search(r"\d+", str(value))
            if match:
                return int(match.group())

    return fallback_id


def find_product_cards(soup):
    selectors = [
        ".product-card",
        ".product-item",
        "[data-product-id]",
        "[data-id]",
    ]

    for selector in selectors:
        cards = soup.select(selector)
        cards = [
            card for card in cards
            if card.select_one(".product-name, .product-title, h2, h3")
        ]
        if cards:
            return cards

    cards = []
    for title in soup.select(".product-name, .product-title"):
        card = title
        while card and card.name not in ("body", "html"):
            if card.select_one(".price") and card.select_one(".category"):
                break
            card = card.parent

        if card and card.name not in ("body", "html"):
            cards.append(card)

    unique_cards = []
    seen = set()
    for card in cards:
        marker = id(card)
        if marker not in seen:
            seen.add(marker)
            unique_cards.append(card)

    return unique_cards


def extract_products_from_listing(page, starting_id=1):
    """Extract fields available on the listing page, including each detail URL."""
    soup = BeautifulSoup(page.content(), "html.parser")
    products = []

    for card in find_product_cards(soup):
        title = get_text(
            card, [".product-name", ".product-title", "[data-title]", "h2", "h3"]
        )
        if not title:
            continue

        category = get_text(
            card, [".category", ".product-category", "[data-category]"]
        )
        vendor = get_text(
            card,
            [".vendor", ".product-vendor", ".brand", ".product-brand",
             "[data-vendor]", "[data-brand]"],
        )
        price_text = get_text(
            card, [".price", ".product-price", "[data-price]"]
        )
        compare_text = get_text(
            card,
            [".compare-at-price", ".compareAtPrice", ".original-price",
             ".old-price", ".price-original", "[data-compare-at-price]",
             "del", "s", "strike"],
        )

        products.append({
            "id": get_product_id(card, starting_id + len(products)),
            "title": title,
            "vendor": vendor,
            "category": category,
            "price": get_price_value(price_text),
            "compareAtPrice": get_price_value(compare_text),
            "description": None,
            "image": get_image(card, page.url),
            "_productUrl": get_product_url(card, page.url),
        })

    return products


def extract_detail_data(page, product):
    """Open one product detail page and extract description/prices/data JSON."""
    product_url = product.get("_productUrl")
    if not product_url:
        print(f"  No product link found for: {product['title']}")
        return

    try:
        page.goto(
            product_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(300)

        soup = BeautifulSoup(page.content(), "html.parser")

        # Some product pages show the product data as JSON inside a <pre>.
        # Use it when present, since it can contain several fields at once.
        json_product = None
        for pre in soup.select("pre"):
            raw_text = pre.get_text(strip=True)
            if not raw_text:
                continue
            try:
                candidate = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            if isinstance(candidate, dict) and (
                "title" in candidate or "description" in candidate
            ):
                json_product = candidate
                break

        if json_product:
            if json_product.get("description"):
                product["description"] = json_product["description"]

            if json_product.get("compareAtPrice") is not None:
                product["compareAtPrice"] = get_price_value(
                    json_product["compareAtPrice"]
                )

            # Fill missing listing fields if the JSON detail object has them.
            for field in ("vendor", "category", "price", "image"):
                if json_product.get(field) is not None:
                    if field == "price":
                        product[field] = get_price_value(json_product[field])
                    elif not product.get(field):
                        product[field] = json_product[field]

        # Fallback to the HTML selectors supplied by you.
        if not product.get("description"):
            description_element = soup.select_one(
                "p.text-sm.text-muted-foreground.leading-relaxed"
            )
            if description_element:
                product["description"] = description_element.get_text(
                    " ", strip=True
                )

        if product.get("compareAtPrice") is None:
            compare_text = get_text(
                soup,
                [".compare-at-price", ".compareAtPrice", ".original-price",
                 ".old-price", ".price-original", "[data-compare-at-price]",
                 "del", "s", "strike"],
            )
            product["compareAtPrice"] = get_price_value(compare_text)

        # Product details may contain a better image URL than the listing.
        if not product.get("image"):
            image = soup.select_one("img[src], img[data-src]")
            if image:
                src = image.get("src") or image.get("data-src")
                if src:
                    product["image"] = urljoin(page.url, src)

    except PlaywrightTimeoutError:
        print(f"  Timed out opening: {product_url}")
    except Exception as error:
        print(f"  Could not extract details for {product['title']}: {error}")


def get_page_signature(page):
    return tuple(
        title.inner_text().strip()
        for title in page.locator(".product-name, .product-title").all()
    )


def main():
    all_products = []
    seen_products = set()
    next_fallback_id = 1

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            print("Opening website...")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.locator(".product-name, .product-title").first.wait_for(
                timeout=30000
            )

            page_number = 1

            # First collect product cards and their detail links from every listing page.
            while True:
                page.wait_for_timeout(500)
                products = extract_products_from_listing(
                    page, starting_id=next_fallback_id
                )

                new_count = 0
                for product in products:
                    key = (
                        product["title"],
                        product["vendor"],
                        product["category"],
                        product["price"],
                    )
                    if key not in seen_products:
                        seen_products.add(key)
                        all_products.append(product)
                        new_count += 1

                next_fallback_id = len(all_products) + 1
                print(
                    f"Page {page_number}: {new_count} new products | "
                    f"Total: {len(all_products)}"
                )

                previous_signature = get_page_signature(page)
                numbered_buttons = page.locator(
                    'button[data-slot="button"]'
                ).filter(has_text=re.compile(r"^\s*\d+\s*$"))

                next_page = None
                for button in numbered_buttons.all():
                    text = button.inner_text().strip()
                    if text.isdigit() and int(text) > page_number:
                        number = int(text)
                        if next_page is None or number < next_page[0]:
                            next_page = (number, button)

                if next_page is None:
                    print("No next numbered page found.")
                    break

                next_page_number, button = next_page
                if not button.is_enabled():
                    print("Pagination button is disabled.")
                    break

                button.click()
                try:
                    page.wait_for_function(
                        """previous => {
                            const current = Array.from(
                                document.querySelectorAll(
                                    '.product-name, .product-title'
                                )
                            ).map(el => el.innerText.trim());
                            return current.length > 0 &&
                                JSON.stringify(current) !== JSON.stringify(previous);
                        }""",
                        arg=list(previous_signature),
                        timeout=15000,
                    )
                except PlaywrightTimeoutError:
                    print("Product list did not change. Stopping pagination.")
                    break

                page_number = next_page_number

            # Then visit each product detail page to collect description and compareAtPrice.
            total = len(all_products)
            print(f"\nOpening detail pages for {total} products...")
            for index, product in enumerate(all_products, start=1):
                print(f"[{index}/{total}] {product['title']}")
                extract_detail_data(page, product)

            # Internal URL is only for navigation; don't include it in the JSON output.
            for product in all_products:
                product.pop("_productUrl", None)

            with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
                json.dump(all_products, file, ensure_ascii=False, indent=2)

            print("\nScraping finished!")
            print(f"Total unique products: {len(all_products)}")
            print(f"JSON file saved to: {OUTPUT_FILE}")

            for field in (
                "vendor", "category", "price", "compareAtPrice",
                "description", "image",
            ):
                missing_count = sum(
                    product.get(field) is None for product in all_products
                )
                if missing_count:
                    print(
                        f"Warning: {missing_count} products are missing '{field}'."
                    )

        finally:
            browser.close()


if __name__ == "__main__":
    main()
