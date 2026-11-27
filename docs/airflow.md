# Airflow pipeline + data quality checks

Phase 2 of the project: the same pipeline you run by hand (`python src/transform/run_all.py`)
now runs as an Airflow DAG, and a data quality gate checks the result before the run is
allowed to finish.

Everything below that says "expected" or "target" is what the run **should** produce on this
machine. Those numbers have not been confirmed yet - the first real signal is the first run.

## What was added

| File | What it is |
| --- | --- |
| `docker-compose.airflow.yml` | Airflow 3.4 (api-server, scheduler, dag-processor) + its own metadata database |
| `airflow/Dockerfile` | Airflow image with the extra Python libraries the pipeline needs |
| `airflow/requirements-airflow.txt` | Those libraries (`psycopg2-binary`, `requests`, `python-dotenv`) |
| `airflow/dags/depi_pipeline_dag.py` | The DAG: 3 extracts -> transform -> quality gate |
| `src/quality/checks.py` | The quality rules (pure Python, one SQL query per rule) |
| `src/quality/run_checks.py` | Runs the rules, stores the results, exits 1 on a failed error check |
| `tests/test_quality_checks.py` | Unit tests for the rules (no database needed) |
| `tests/test_dag_structure.py` | Checks the DAG file without importing Airflow |
| `tests/test_batch_ids.py` | Proves batch ids stay the same for unchanged input |
| `docs/airflow.md` | This page |

Two existing files changed, both so a repeated run cannot store the same data twice:

* `src/extract/api_client.py` - batch id from the fetched products (was: timestamp + random).
* `src/load/books_loader.py` - batch id from the books JSON content, and a batch that is
  already loaded is skipped (was: random id, no guard).

## The DAG

```
extract_api  ─┐
load_books   ─┼─> transform_all ─> quality_checks
load_olist   ─┘
```

| Task | Command it runs |
| --- | --- |
| `extract_api` | `python -m extract.api_client` |
| `load_books` | `python -m load.books_loader` |
| `load_olist` | `python -m load.olist_loader` |
| `transform_all` | `python -m transform.run_all` |
| `quality_checks` | `python -m quality.run_checks --run-id "<airflow run id>"` |

Schedule: every day at 02:00 Cairo time, no catch-up runs, one run at a time.
A task retries once after 3 minutes before the run is marked failed.

## Before the first run

1. Docker Desktop is running and has at least **6 GB** of memory (Airflow runs 4 containers).
2. Start the application database first. This also creates the Docker network Airflow joins:

   ```bash
   docker compose up -d postgres
   ```

   Airflow reaches the warehouse over that network as `postgres:5432`. The published host
   port and the `127.0.0.1` binding in `docker-compose.yml` stay exactly as they are.

3. `data/raw/books_raw.json` and the Olist CSVs in `data/olist/` are still on disk.
   They are not in git, and the containers read them from the mounted project folder.
4. `.env` has the database settings (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
   `POSTGRES_PORT=5433`). Add one line so the Airflow containers use the normal user id:

   ```
   AIRFLOW_UID=50000
   ```

5. The Airflow stack expects the network `ecommerce-data-platform_default` (the one the
   application project creates). Check it exists:

   ```bash
   docker network ls
   ```

   If the name is different, add `APP_NETWORK=<that name>` to `.env`.

## Start Airflow

```bash
docker compose -f docker-compose.airflow.yml build
docker compose -f docker-compose.airflow.yml up -d
docker compose -f docker-compose.airflow.yml ps
```

Target result of `ps`: `depi_airflow_apiserver`, `depi_airflow_scheduler`,
`depi_airflow_dagprocessor` and `depi_airflow_postgres` running, and `depi_airflow_init`
**exited with code 0**.

Open <http://localhost:8080> (bound to 127.0.0.1 only) and sign in with **admin / admin**
(or change the user with `_AIRFLOW_WWW_USER_USERNAME` / `_AIRFLOW_WWW_USER_PASSWORD` in `.env`).

The DAG `depi_pipeline` appears paused. Unpause it with the toggle on the left.

## Run it once

```bash
docker compose -f docker-compose.airflow.yml run --rm airflow-cli airflow dags unpause depi_pipeline
docker compose -f docker-compose.airflow.yml run --rm airflow-cli airflow dags trigger depi_pipeline
```

Or press **Trigger** in the UI (play button, right side of the DAG row).

Expected (target) log lines, task by task:

* `extract_api`: `Fetched 194 products`, `Starting batch api_<hash>`, `Processed 194 rows`
* `load_books`: `Batch ID: books_<hash>`, `Rows inserted: 1000`
* `load_olist`: `olist_csv: read=... inserted=...` for the 9 tables
* `transform_all`: `applied 08_clean_sources.sql`, `api: {... 'loaded': 194 ...}`,
  `scraping: {... 'loaded': 1000 ...}`, `applied 05_stg_olist.sql`, `applied 06_clean_olist.sql`
* `quality_checks`:

```
== data quality checks ==
run_id: scheduled__2026-11-28T00:00:00+00:00

[PASS] raw_sources_loaded             observed=3       expected >= 3      (error)
[PASS] clean_sources_present          observed=3       expected >= 3      (error)
...
summary: 15 checks | 15 passed | 0 error(s) | 0 warning(s)
RESULT: PASSED (fail on error)
```

Run the same checks outside Airflow any time:

```bash
python -m quality.run_checks            # same PYTHONPATH=src as run_all
python -m quality.run_checks --list     # print the rules, no database
python -m quality.run_checks --fail-on warn
```

If Python cannot find the `quality` module, set the same `PYTHONPATH` you already use for
`run_all` (`$env:PYTHONPATH="src"` in PowerShell). Inside Airflow this is already set.

## What a green run means

A green `depi_pipeline` run says three things:

1. All three loaders ran and exited 0. Each one raises instead of passing quietly:
   `load_books` fails if `data/raw/books_raw.json` is missing, empty or missing required
   fields; `load_olist` fails if a CSV is missing or its header is wrong; `extract_api`
   fails if the API returns nothing. So green means the three sources were really read.
2. `transform_all` applied the clean layer for all three sources (`08_clean_sources.sql`,
   the two Python transforms, `05_stg_olist.sql`, `06_clean_olist.sql`).
3. All 12 error-level quality checks passed. They include per-source product and snapshot
   counts, the three-source `dwh.v_price_history` view, duplicate products, empty titles,
   price sanity, discount above price, rating/stock ranges, and currency per source.
   A failing error-level check fails the task and the run turns red.

It does **not** mean new rows were inserted. With unchanged input a run inserts nothing
(see the next section), and that is correct: the pipeline recorded that state already.

## The quality rules

| Rule | Severity | Fails when |
| --- | --- | --- |
| `raw_sources_loaded` | error | fewer than 3 sources have a raw batch |
| `clean_sources_present` | error | fewer than 3 sources have products in `dwh` |
| `products_per_source` | error | a source has 0 products |
| `snapshots_per_source` | error | a source has 0 price snapshots |
| `unified_view_sources` | error | `dwh.v_price_history` does not return 3 sources |
| `missing_titles` | error | a product has an empty title |
| `duplicate_products` | error | a product is stored twice for one source |
| `invalid_prices` | error | price <= 0 or > 1,000,000 |
| `discount_above_price` | error | price after discount is higher than the price |
| `bad_rating_or_stock` | error | rating outside 0-5 or negative stock |
| `currency_mismatch` | error | a source uses the wrong currency (GBP / USD / BRL) |
| `currency_format` | error | a currency code is not 3 uppercase letters |
| `rejected_records_recent` | warn | a record was rejected in the last 7 days |
| `stale_sources` | warn | the API or scraping source has no snapshot from the last 7 days |
| `products_without_snapshot` | warn | an API/scraped product has no price snapshot |

`error` fails the Airflow task. `warn` only shows up in the report. Olist is excluded from
the last two rules on purpose: it is a historical dataset and only snapshots products that
were actually sold.

Results are kept in the database, one row per rule per run:

```sql
SELECT check_name, severity, observed, expectation, passed, checked_at
FROM dwh.dq_check_result
WHERE run_id = 'scheduled__2026-11-28T00:00:00+00:00'
ORDER BY severity, check_name;
```

## Adding a rule

Add one `Check(...)` to `CHECKS` in `src/quality/checks.py`. The query must be a single
`SELECT` that returns one number, and you give it `min_value` and/or `max_value`.
Add a line for it in the table above and the tests keep passing. No DAG change needed.

## Re-running: idempotency

Every source derives its batch id from the data it just read, so the same input maps to the
same batch:

* API: hash of the fetched products (`api_<hash>`).
* Scraping: hash of `books_raw.json` (`books_<hash>`).
* Olist: hash of the CSV files (`olist_<hash>`).
* `run_all` and the SQL files are idempotent (upserts, `ON CONFLICT`, `CREATE OR REPLACE`).

So a second full run with unchanged input inserts **zero** rows: the API batch is skipped by
`ON CONFLICT` in raw, `load_books` finds its batch already loaded, the Olist rows are skipped
by `ON CONFLICT`, and the transforms upsert the same dimension rows and skip the existing
snapshots. `scripts/verify_clean.py` prints the same numbers before and after.

The **first** Airflow run does add exactly one batch per source, because the batches in the
database today were created with timestamp/random ids. So expect, right after the first run
(and stable from then on):

| Source | products | snapshots |
| --- | --- | --- |
| `books_to_scrape` | 1000 | 2000 (old batch + new one) |
| `dummyjson_api` | 194 | 388 |
| `olist_csv` | 101 | 103 |

The clean layer still holds 1000 / 194 / 101 distinct products. The extra snapshot rows are
one extra price observation per product, not duplicate products.

A retried task is safe for the same reason: the retry recomputes the same batch id.

## Troubleshooting

**`network ecommerce-data-platform_default declared as external, but could not be found`.**
The application project has not created its network yet, or its name is different. Run
`docker compose up -d postgres` first, then `docker network ls` and put the real name in
`.env` as `APP_NETWORK=<name>`. Do not change the port mapping in `docker-compose.yml`.

**The pipeline tasks cannot reach Postgres** (`could not connect to server`). The container
looks for `postgres:5432` on the shared network. Check that `ecommerce_postgres` is running
(`docker compose ps`) and that both compose files use the same `APP_NETWORK`.

**Port 8080 is already used.** Add `AIRFLOW_PORT=8081` to `.env` and run
`docker compose -f docker-compose.airflow.yml up -d` again. The UI stays on 127.0.0.1.

**The image build fails downloading the constraints file.** `airflow/Dockerfile` installs the
extra libraries against Airflow's official constraints file (needs internet). If GitHub is not
reachable, delete the `--constraint ...` line and build again; the pinned versions in
`airflow/requirements-airflow.txt` already match Airflow 3.4.0's constraints.

**`depi_airflow_init` failed.** Run it alone to read the full log:
`docker compose -f docker-compose.airflow.yml run --rm airflow-init`.

**A task says `ModuleNotFoundError: extract`.** `PYTHONPATH` must be
`/opt/airflow/project/src`; it is set in `docker-compose.airflow.yml`. If you changed it,
recreate the containers: `docker compose -f docker-compose.airflow.yml up -d --force-recreate`.

**Nothing happens at 02:00.** The DAG is paused by default
(`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`). Unpause it once; the setting survives restarts.

**Stop everything** (keeps the metadata database and logs):
`docker compose -f docker-compose.airflow.yml down`.
Add `-v` to also delete the Airflow metadata and logs.
