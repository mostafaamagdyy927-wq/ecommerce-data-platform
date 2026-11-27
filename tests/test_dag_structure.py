"""Structural tests for the Airflow DAG file.

Airflow is not installed in the local venv, so the DAG cannot be imported here.
These tests parse the file with `ast` instead: they catch a wrong task id, a
missing `append_env`, or a task that runs the wrong module before you rebuild
the Docker image.
"""

import ast
from pathlib import Path

DAG_PATH = Path(__file__).resolve().parents[1] / "airflow" / "dags" / "depi_pipeline_dag.py"

EXPECTED_TASKS = {
    "extract_api",
    "load_books",
    "load_olist",
    "transform_all",
    "quality_checks",
}

EXPECTED_MODULES = {
    "extract.api_client",
    "load.books_loader",
    "load.olist_loader",
    "transform.run_all",
    "quality.run_checks",
}


def dag_source():
    assert DAG_PATH.is_file(), f"missing DAG file: {DAG_PATH}"
    return DAG_PATH.read_text(encoding="utf-8")


def dag_tree():
    return ast.parse(dag_source())


def bash_operators(tree):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BashOperator"
    ]


def module_constant(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not defined at module level")


def run_commands(tree):
    """Every string passed to the DAG's run() helper."""
    commands = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "run":
            commands.extend(arg.value for arg in node.args if isinstance(arg, ast.Constant))
    return commands


def test_dag_id_and_schedule():
    tree = dag_tree()
    assert module_constant(tree, "DAG_ID") == "depi_pipeline"
    assert module_constant(tree, "SCHEDULE") == "0 2 * * *"


def test_task_ids():
    tree = dag_tree()
    task_ids = {
        keyword.value.value
        for call in bash_operators(tree)
        for keyword in call.keywords
        if keyword.arg == "task_id"
    }
    assert task_ids == EXPECTED_TASKS


def test_every_task_inherits_the_container_environment():
    for call in bash_operators(dag_tree()):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "append_env" in keywords, "append_env is required to see POSTGRES_* and PYTHONPATH"
        assert keywords["append_env"].value is True


def test_tasks_run_the_expected_modules():
    modules = set()
    for command in run_commands(dag_tree()):
        assert command.startswith("python -m "), command
        modules.add(command.split("python -m ", 1)[1].split()[0])
    assert modules == EXPECTED_MODULES


def test_run_helper_stops_on_first_error_and_enters_the_project():
    source = dag_source()
    assert "set -euo pipefail" in source
    assert "cd {PROJECT_DIR}" in source
    assert module_constant(dag_tree(), "PROJECT_DIR") == "/opt/airflow/project"


def test_quality_gate_runs_last():
    source = dag_source()
    assert ">> transform_all >> quality_checks" in source
    assert "[extract_api, load_books, load_olist] >> transform_all" in source


def test_quality_task_receives_the_run_id():
    source = dag_source()
    assert '--run-id "{{ run_id }}"' in source


def test_no_task_overrides_the_batch_id():
    """Batch ids must come from the data, otherwise a second run duplicates rows."""
    for call in bash_operators(dag_tree()):
        keyword_names = {keyword.arg for keyword in call.keywords}
        assert "env" not in keyword_names, (
            "do not pin PIPELINE_BATCH_ID per task: it makes every run a new batch"
        )
