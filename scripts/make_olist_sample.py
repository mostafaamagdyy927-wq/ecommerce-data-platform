"""Build a small, RELATIONALLY CONSISTENT sample of the Olist dataset.

Picks N orders (delivered first, deterministic), then keeps only the rows that
belong to them: their items, payments, reviews, and the customers, sellers and
products they reference. Category translation is copied in full. Geolocation is
filtered to the zip prefixes used by the sampled customers/sellers (a few rows
per prefix, capped). The same input always gives the same sample.

Usage: python scripts/make_olist_sample.py [--src data/olist] [--dst data/sample/olist] [--orders 100]
"""

import argparse
import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from load.olist_loader import FILES  # noqa: E402

ORDERS = "olist_orders_dataset.csv"
ITEMS = "olist_order_items_dataset.csv"
PAYMENTS = "olist_order_payments_dataset.csv"
REVIEWS = "olist_order_reviews_dataset.csv"
CUSTOMERS = "olist_customers_dataset.csv"
SELLERS = "olist_sellers_dataset.csv"
PRODUCTS = "olist_products_dataset.csv"
GEO = "olist_geolocation_dataset.csv"
TRANSLATION = "product_category_name_translation.csv"

GEO_PER_ZIP = 3
GEO_MAX = 300


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if r]
    return header, rows


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{path.name}: {len(rows)} rows")


def keep(header, rows, column, values):
    i = header.index(column)
    return [r for r in rows if r[i] in values]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=str(ROOT / "data" / "olist"))
    parser.add_argument("--dst", default=str(ROOT / "data" / "sample" / "olist"))
    parser.add_argument("--orders", type=int, default=100)
    args = parser.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)

    # 1) orders: delivered first, ordered by a hash of the id (deterministic, spread over time)
    h_orders, orders = read_csv(src / ORDERS)
    i_id, i_status = h_orders.index("order_id"), h_orders.index("order_status")
    orders.sort(key=lambda r: (r[i_status] != "delivered",
                               hashlib.sha1(r[i_id].encode()).hexdigest()))
    orders = orders[: args.orders]
    order_ids = {r[i_id] for r in orders}
    write_csv(dst / ORDERS, h_orders, orders)

    # 2) rows that belong to those orders
    h_items, items = read_csv(src / ITEMS)
    items = keep(h_items, items, "order_id", order_ids)
    write_csv(dst / ITEMS, h_items, items)

    h_pay, pay = read_csv(src / PAYMENTS)
    write_csv(dst / PAYMENTS, h_pay, keep(h_pay, pay, "order_id", order_ids))

    h_rev, rev = read_csv(src / REVIEWS)
    write_csv(dst / REVIEWS, h_rev, keep(h_rev, rev, "order_id", order_ids))

    # 3) referenced dimensions
    customer_ids = {r[h_orders.index("customer_id")] for r in orders}
    seller_ids = {r[h_items.index("seller_id")] for r in items}
    product_ids = {r[h_items.index("product_id")] for r in items}

    h_c, c = read_csv(src / CUSTOMERS)
    c = keep(h_c, c, "customer_id", customer_ids)
    write_csv(dst / CUSTOMERS, h_c, c)

    h_s, s = read_csv(src / SELLERS)
    s = keep(h_s, s, "seller_id", seller_ids)
    write_csv(dst / SELLERS, h_s, s)

    h_p, p = read_csv(src / PRODUCTS)
    write_csv(dst / PRODUCTS, h_p, keep(h_p, p, "product_id", product_ids))

    # 4) full category translation
    h_t, t = read_csv(src / TRANSLATION)
    write_csv(dst / TRANSLATION, h_t, t)

    # 5) geolocation: only zip prefixes we use, a few rows each, capped
    zips = {r[h_c.index("customer_zip_code_prefix")] for r in c}
    zips |= {r[h_s.index("seller_zip_code_prefix")] for r in s}
    h_g, g = read_csv(src / GEO)
    iz = h_g.index("geolocation_zip_code_prefix")
    seen, geo = {}, []
    for r in g:
        z = r[iz]
        if z in zips and seen.get(z, 0) < GEO_PER_ZIP:
            seen[z] = seen.get(z, 0) + 1
            geo.append(r)
    write_csv(dst / GEO, h_g, geo[:GEO_MAX])

    missing = set(FILES) - {ORDERS, ITEMS, PAYMENTS, REVIEWS, CUSTOMERS, SELLERS, PRODUCTS, GEO, TRANSLATION}
    if missing:
        print("WARNING: files not written:", sorted(missing))


if __name__ == "__main__":
    main()
