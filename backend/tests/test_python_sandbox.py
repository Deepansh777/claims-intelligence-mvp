"""The analysis sandbox runs standard-library code on query results and nothing else."""

import asyncio
from pathlib import Path

import pytest

from app.llm.schemas import QueryResult
from app.services import python_sandbox

RESULTS = {
    "q1": QueryResult(
        columns=["category", "admissions"],
        types=["text", "numeric"],
        rows=[["Cardiac", 3], ["Respiratory", 9], ["Other", 4]],
        row_count=3,
        truncated=False,
    )
}


def run(code: str) -> dict:
    return asyncio.run(python_sandbox.run_script(code, RESULTS))


def test_runs_standard_library_analysis_on_the_results():
    out = run(
        "import statistics\n"
        "vals = [r['admissions'] for r in results['q1']]\n"
        "top = max(results['q1'], key=lambda r: r['admissions'])\n"
        "print(top['category'], round(statistics.mean(vals), 2))"
    )
    assert out == {
        "status": "succeeded",
        "output": "Respiratory 5.33\n",
        "duration_ms": out["duration_ms"],
    }


@pytest.mark.parametrize(
    "code",
    [
        "import socket",
        "import subprocess",
        "import ctypes",
        "import os; os.system('true')",
        "import os; os.fork()",
        "open('/etc/passwd').read()",
        f"open({str(Path(__file__).resolve())!r}).read()",
        "import pathlib; pathlib.Path('/etc/hostname').read_text()",
        "import os; os.listdir('/')",
        "open('out.txt', 'w').write('x')",
    ],
)
def test_blocks_network_processes_files_and_native_code(code):
    out = run(code)
    assert out["status"] == "failed" and "PermissionError" in out["output"]


def test_environment_holds_no_app_settings():
    # Python itself sets LC_CTYPE when it coerces the C locale.
    assert run("import os; print(sorted(os.environ))")["output"] in ("[]\n", "['LC_CTYPE']\n")


def test_long_runs_are_stopped_and_output_is_capped(monkeypatch):
    monkeypatch.setattr(python_sandbox, "TIMEOUT_S", 1)
    assert run("import time; time.sleep(5)") == {
        "status": "failed",
        "output": "Stopped after 1 s.",
        "duration_ms": pytest.approx(1000, abs=900),
    }
    out = run("print('x' * 10000)")
    assert out["status"] == "succeeded" and out["output"].endswith("… output truncated")
    assert len(out["output"]) < python_sandbox.MAX_OUTPUT + 30
