import random
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup


def scrape_smartphones():
    product_price = []
    product_rate = []
    product_number_reviews = []
    product_url = []
    product_brand = []
    product_discount = []
    product_description = []
    product_storage = []
    product_ram = []

    page = 1

    while page <= 50:
        url = f"https://www.jumia.com.eg/catalog/?q=smartphone&page={page}#catalog-listing"
        response = requests.get(url)

        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        containers = soup.find_all("article", {"class": "prd"})

        if len(containers) == 0:
            break

        for container in containers:
            name_tag = container.find("h3", {"class": "name"})
            description = name_tag.text if name_tag else None
            product_description.append(description)

            price_tag = container.find("div", {"class": "prc"})
            product_price.append(
                price_tag.text.replace("EGP ", "") if price_tag else None
            )

            rate_tag = container.find("div", {"class": "stars _s"})
            product_rate.append(rate_tag.text.split()[0] if rate_tag else None)

            reviews_tag = container.find("div", {"class": "rev"})
            product_number_reviews.append(
                reviews_tag.text.split()[-1].replace("5(", "").replace(")", "")
                if reviews_tag
                else None
            )

            link_tag = container.find("a", class_="core")
            link = (
                "https://www.jumia.com.eg" + link_tag.get("href")
                if link_tag
                else None
            )
            product_url.append(link)

            product_brand.append(name_tag.text.split()[0] if name_tag else None)

            discount_tag = container.find("div", {"class": "bdg _dsct _sm"})
            product_discount.append(discount_tag.text if discount_tag else "0")

            if description:
                ram_match = re.search(r"(\d+)\s*GB", description)
                ram = ram_match.group(1) + "GB" if ram_match else None

                storage_match = re.search(
                    r"(\d{3}\s*GB|\d+\s*GB\s*(?!RAM))", description
                )
                if not storage_match:
                    all_gb = re.findall(r"(\d+\s*GB)", description)
                    storage = all_gb[-1] if len(all_gb) > 1 else None
                else:
                    storage = storage_match.group(1)
            else:
                ram = None
                storage = None

            product_ram.append(ram)
            product_storage.append(storage)

        print(f"Smartphones - Page {page} done")
        time.sleep(random.uniform(2, 5))
        page += 1

    jumia_smartphones_df = pd.DataFrame(
        {
            "platform": "Jumia",
            "category": "Smartphones",
            "product_description": product_description,
            "product_price": product_price,
            "product_rate": product_rate,
            "product_number_reviews": product_number_reviews,
            "product_url": product_url,
            "product_brand": product_brand,
            "product_discount": product_discount,
            "product_storage": product_storage,
            "product_ram": product_ram,
        }
    )

    jumia_smartphones_df.to_csv("Jumia_smartpnones_data.csv")
    return jumia_smartphones_df


def scrape_headphones():
    product_description = []
    product_price = []
    product_rate = []
    product_number_reviews = []
    product_url = []
    product_brand = []
    product_discount = []

    page = 1

    while page <= 50:
        url = f"https://www.jumia.com.eg/catalog/?q=headphones&page={page}#catalog-listing"
        response = requests.get(url)

        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        containers = soup.find_all("article", {"class": "c-prd"})

        if len(containers) == 0:
            break

        for container in containers:
            name_tag = container.find("h3", {"class": "name"})
            description = name_tag.text if name_tag else None
            product_description.append(description)

            price_tag = container.find("div", {"class": "prc"})
            product_price.append(
                price_tag.text.replace("EGP ", "") if price_tag else None
            )

            rate_tag = container.find("div", {"class": "stars _s"})
            product_rate.append(rate_tag.text.split()[0] if rate_tag else None)

            reviews_tag = container.find("div", {"class": "rev"})
            product_number_reviews.append(
                reviews_tag.text.split()[-1].replace("5(", "").replace(")", "")
                if reviews_tag
                else None
            )

            link_tag = container.find("a", {"class": "core"})
            link = (
                "https://www.jumia.com.eg" + link_tag.get("href")
                if link_tag
                else None
            )
            product_url.append(link)

            product_brand.append(name_tag.text.split()[0] if name_tag else None)

            discount_tag = container.find("div", {"class": "bdg _dsct _sm"})
            product_discount.append(discount_tag.text if discount_tag else None)

        print(f"Headphones - Page {page} done")
        time.sleep(random.uniform(2, 5))
        page += 1

    jumia_headphones_df = pd.DataFrame(
        {
            "platform": "Jumia",
            "category": "Headphones",
            "product_description": product_description,
            "product_price": product_price,
            "product_rate": product_rate,
            "product_number_reviews": product_number_reviews,
            "product_url": product_url,
            "product_brand": product_brand,
            "product_discount": product_discount,
        }
    )

    jumia_headphones_df.to_csv("Jumia_Headphones_data.csv")
    jumia_headphones_df.info()
    return jumia_headphones_df


def merge_datasets():
    df_headphones = pd.read_csv("Jumia_Headphones_data.csv", index_col=0)
    df_smartphones = pd.read_csv("Jumia_smartpnones_data.csv", index_col=0)

    df_combined = pd.concat([df_headphones, df_smartphones], ignore_index=True)
    df_combined.to_csv("Jumia_combined_data.csv", index=False)

    print(df_combined.shape)
    print(df_combined["category"].value_counts())
    return df_combined


if __name__ == "__main__":
    scrape_smartphones()
    scrape_headphones()
    merge_datasets()
