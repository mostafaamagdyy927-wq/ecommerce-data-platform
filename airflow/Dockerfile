# Airflow image for the DEPI pipeline.
#
# SQLAlchemy and psycopg (v3) come from the Airflow image itself, so they are
# NOT pinned here: Airflow 3.4 already ships SQLAlchemy 2.0.x, which is what the
# project code uses. Only the libraries the pipeline needs on top are added,
# installed against the official constraints file so Airflow's own dependencies
# stay consistent.
FROM apache/airflow:3.4.0-python3.12

ARG AIRFLOW_VERSION=3.4.0
ARG PYTHON_VERSION=3.12

COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir -r /requirements-airflow.txt \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
