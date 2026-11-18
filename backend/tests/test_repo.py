"""Repo hygiene: the version is the same in every place, and the releases folder is well formed.
Skipped when the rest of the repo is not there (for example when only backend/ is deployed)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "bump_version.py").is_file() or not (ROOT / "frontend").is_dir(),
    reason="the whole repository is not present",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_is_the_same_everywhere():
    assert _load("bump_version").check() == []


def test_releases_are_well_formed():
    assert _load("check_releases").check() == []
