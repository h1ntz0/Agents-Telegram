"""The release version must be stated once and agree everywhere it is repeated."""

import re
from pathlib import Path

import src

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def test_pyproject_takes_its_version_from_the_package():
    """The version has a single source of truth: src/__init__.py."""
    text = PYPROJECT.read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in text
    assert re.search(r'^version\s*=\s*"', text, re.MULTILINE) is None
    assert 'version = { attr = "src.__version__" }' in text


def test_changelog_documents_the_current_version():
    """A release without a changelog entry is a release nobody can read about."""
    assert CHANGELOG.exists(), "CHANGELOG.md is missing"

    headings = re.findall(r"^##\s+\[?v?(\d+\.\d+\.\d+)", CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE)

    assert headings, "CHANGELOG.md has no version heading"
    assert headings[0] == src.__version__, (
        f"CHANGELOG.md documents {headings[0]} as the newest release, "
        f"but src/__init__.py declares {src.__version__}"
    )
