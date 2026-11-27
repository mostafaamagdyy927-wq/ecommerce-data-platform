"""DEPI pipeline DAG: extract -> raw -> clean -> data quality, every day at 02:00 Cairo.

The DAG does not import project code. Every task is a shell command that runs one
module from the project folder mounted at /opt/airflow/project, using the
container's Python (the Windows .venv is not used inside Docker).

Batch ids: every source derives its batch id from the data it just read (the API
response, data/raw/books_raw.json, the Olist CSVs), so a run with unchanged input
stores nothing twice. PIPELINE_BATCH_ID still overrides all three when it is set.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

DAG_ID = "depi_pipeline"
SCHEDULE = "0 2 * * *"
PROJECT_DIR = "/opt/airflow/project"
CAIRO = ZoneInfo("Africa/Cairo")


def run(*commands: str) -> str:
    """Shell command that runs from the project root and stops on the first error."""
    body = "\n".join(commands)
    return f"set -euo pipefail\ncd {PROJECT_DIR}\n{body}"


with DAG(
    dag_id=DAG_ID,
    description="E-commerce price platform: raw -> clean -> data quality (3 sources)",
    schedule=SCHEDULE,
    start_date=datetime(2026, 11, 1, tzinfo=CAIRO),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    default_args={
        "depends_on_past": False,
        "retries": 1,
        "retry_delay": timedelta(minutes=3),
    },
    tags=["depi", "ecommerce", "pipeline"],
    doc_md=__doc__,
) as dag:

    # 1) Extract: three sources in parallel, each into its own raw table.
    extract_api = BashOperator(
        task_id="extract_api",
        bash_command=run("python -m extract.api_client"),
        append_env=True,
    )

    load_books = BashOperator(
        task_id="load_books",
        bash_command=run("python -m load.books_loader"),
        append_env=True,
    )

    load_olist = BashOperator(
        task_id="load_olist",
        bash_command=run("python -m load.olist_loader"),
        append_env=True,
    )

    # 2) Transform: the same steps as `python src/transform/run_all.py`.
    transform_all = BashOperator(
        task_id="transform_all",
        bash_command=run("python -m transform.run_all"),
        append_env=True,
    )

    # 3) Quality gate: fails the run when an error-level check fails.
    quality_checks = BashOperator(
        task_id="quality_checks",
        bash_command=run('python -m quality.run_checks --run-id "{{ run_id }}"'),
        append_env=True,
    )

    [extract_api, load_books, load_olist] >> transform_all >> quality_checks
