# E-Commerce Data Platform with Price Intelligence

End-to-end Data Engineering platform that collects e-commerce data from
multiple sources, validates and transforms it, loads it into a star-schema
data warehouse, and adds AI-powered price analysis with an interactive dashboard.

> DEPI Graduation Project: Data Engineer Track (Cohort 5)

## Problem
An e-commerce company receives product, customer, order, and price data from
different sources (CSV/JSON files, APIs, public web sources). The data contains
duplicates, missing values, and inconsistent formats, so analysts have no
reliable dataset for sales reporting.

## Objective
Build an automated pipeline that extracts data from multiple sources, cleans
and validates it, stores it in a relational data warehouse, and serves
analytics and AI insights through a dashboard and a REST API.

## Architecture
Sources → Raw Layer → Validate → Transform → Warehouse (Star Schema) → AI Layer → API + Dashboard
                        (orchestrated by Apache Airflow)

*(Architecture diagram and ERD: coming soon)*

## Data Model (Star Schema)
- Fact Sales
- Dim Customer
- Dim Product
- Dim Date
- Price history table (price snapshots over time)

## Features (planned)
- Multi-source ingestion (CSV/JSON, REST API, permitted public sources)
- Raw layer kept separate from cleaned data
- Data validation, duplicate and missing-value handling
- Incremental loading
- Airflow DAG: Extract → Validate → Transform → Load → Quality Check
- Logging, retries, and error handling
- SQL views and indexes for analytical queries
- AI layer: price anomaly and fake-discount detection
- REST API (FastAPI) and interactive dashboard

## Tech Stack
Python · Pandas · PostgreSQL · Apache Airflow · FastAPI · Docker ·
scikit-learn · Streamlit / Power BI

## Responsible Data Collection
Only publicly available data from sources that allow it is used. Each source's
robots.txt and terms are checked, requests are rate-limited, and no personal
data is collected.

## Project Structure
