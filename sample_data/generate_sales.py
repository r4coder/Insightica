"""Generates sample_data/sales.csv with realistic, non-repetitive variation and a genuine Q3 2024
revenue dip concentrated in Enterprise/West, so 'why did revenue decline in Q3' has a real answer
for the agents to discover - never hardcoded into the app itself."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta

random.seed(42)

REGIONS = ["North America", "Europe", "APAC", "LATAM"]
COUNTRIES = {"North America": ["USA", "Canada"], "Europe": ["Germany", "France", "UK", "Spain"],
            "APAC": ["Japan", "Australia", "India", "Singapore"], "LATAM": ["Brazil", "Mexico"]}
PRODUCTS = {"Electronics": ["Wireless Headphones", "Smart Watch", "Bluetooth Speaker", "Tablet Stand"],
           "Home": ["Air Purifier", "LED Desk Lamp", "Ceramic Cookware Set", "Vacuum Cleaner"],
           "Apparel": ["Running Shoes", "Denim Jacket", "Wool Sweater", "Rain Jacket"],
           "Office": ["Ergonomic Chair", "Standing Desk", "Monitor Arm", "Notebook Set"]}
SEGMENTS = ["Enterprise", "SMB", "Consumer"]
BASE_PRICE = {"Wireless Headphones": 89, "Smart Watch": 199, "Bluetooth Speaker": 59, "Tablet Stand": 25,
             "Air Purifier": 129, "LED Desk Lamp": 39, "Ceramic Cookware Set": 149, "Vacuum Cleaner": 219,
             "Running Shoes": 79, "Denim Jacket": 69, "Wool Sweater": 89, "Rain Jacket": 99,
             "Ergonomic Chair": 249, "Standing Desk": 399, "Monitor Arm": 59, "Notebook Set": 15}

START, END = date(2023, 1, 1), date(2024, 12, 31)
N_ROWS = 6000


def month_seasonality(d: date) -> float:
    return {11: 1.35, 12: 1.5, 1: 0.85, 7: 0.9}.get(d.month, 1.0)


def quarter(d: date) -> int:
    return (d.month - 1) // 3 + 1


def region_weight(region: str, d: date) -> float:
    """Enterprise in the West region genuinely softens in Q3 2024 - a growth-slowdown story, not noise."""
    w = {"North America": 1.3, "Europe": 1.1, "APAC": 0.85, "LATAM": 0.6}[region]
    if d.year == 2024 and quarter(d) == 3 and region == "North America":
        w *= 0.62
    elif d.year == 2024 and quarter(d) == 3:
        w *= 0.95
    return w


def segment_weight(segment: str, d: date) -> float:
    w = {"Enterprise": 1.4, "SMB": 1.0, "Consumer": 0.7}[segment]
    if d.year == 2024 and quarter(d) == 3 and segment == "Enterprise":
        w *= 0.55
    return w


def gen_date() -> date:
    span = (END - START).days
    # slight upward drift in density over time (business growth) plus month seasonality via rejection sampling
    while True:
        d = START + timedelta(days=random.randint(0, span))
        drift = 0.8 + 0.4 * ((d - START).days / span)
        if random.random() < min(1.0, drift * month_seasonality(d) / 1.9):
            return d


def main() -> None:
    rows = []
    for order_id in range(1, N_ROWS + 1):
        d = gen_date()
        region = random.choices(REGIONS, weights=[0.35, 0.3, 0.22, 0.13])[0]
        country = random.choice(COUNTRIES[region])
        category = random.choices(list(PRODUCTS), weights=[0.35, 0.25, 0.25, 0.15])[0]
        product = random.choice(PRODUCTS[category])
        segment = random.choices(SEGMENTS, weights=[0.3, 0.35, 0.35])[0]
        weight = region_weight(region, d) * segment_weight(segment, d) * month_seasonality(d)
        quantity = max(1, int(random.gauss(3 * weight, 1.5)))
        unit_price = round(BASE_PRICE[product] * random.uniform(0.92, 1.08), 2)
        discount = round(random.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2]), 2)
        revenue = round(quantity * unit_price * (1 - discount), 2)
        cost = round(revenue * random.uniform(0.45, 0.65), 2)
        if random.random() < 0.004:  # rare, realistic outliers (bulk enterprise orders)
            quantity *= random.randint(8, 15)
            revenue = round(quantity * unit_price * (1 - discount), 2)
            cost = round(revenue * random.uniform(0.45, 0.6), 2)
        rows.append({"order_id": order_id, "order_date": d.isoformat(), "region": region, "country": country,
                     "product": product, "category": category, "customer_segment": segment, "quantity": quantity,
                     "unit_price": unit_price, "discount": discount, "revenue": revenue, "cost": cost})
    rows.sort(key=lambda r: r["order_date"])
    for i, r in enumerate(rows, start=1):
        r["order_id"] = i
    with open("sales.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to sales.csv")


if __name__ == "__main__":
    main()
