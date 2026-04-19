import subprocess
import sys
import os


def test_web_help():
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.__main__", "web", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        cwd="/Users/axureboutique/Projects/auto-image-pipeline",
    )
    assert result.returncode == 0
    assert "--port" in result.stdout or "--port" in result.stderr


def test_web_help_debug_flag():
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.__main__", "web", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        cwd="/Users/axureboutique/Projects/auto-image-pipeline",
    )
    assert result.returncode == 0
    assert "--debug" in result.stdout or "--debug" in result.stderr
