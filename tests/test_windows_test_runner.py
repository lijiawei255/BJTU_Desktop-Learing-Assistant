"""Exercise batch argument handling and exit codes without launching API tests."""

import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows batch runner")
RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_headless_tests.bat"


@pytest.mark.parametrize("args, child_exit", [([], 0), ([], 7), (["--api"], 7), (["-v"], 0)])
def test_runner_propagates_pytest_result(tmp_path, args, child_exit):
    # Only this child process sees the fake python command.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python.cmd").write_text(
        f"@echo off\necho PYTEST_ARGS %*\nexit /b {child_exit}\n", encoding="ascii"
    )
    env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(RUNNER), *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == child_exit, result.stdout + result.stderr
    assert "PYTEST_ARGS -m pytest tests" in result.stdout
    assert ('--run-api' in result.stdout) == ('--api' in args)
    assert '-m "not hardware"' in result.stdout
    if child_exit:
        assert f"Test run failed with exit code {child_exit}." in result.stdout
    else:
        assert "No unexpected test failures." in result.stdout


def test_runner_rejects_unknown_option(tmp_path):
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(RUNNER), "--unknown"],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert "Unknown option" in result.stdout
