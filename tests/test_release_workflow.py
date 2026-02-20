"""
Tests for the GitHub Actions release workflow configuration.

Required test category notes:
- Concurrency/timing: Not applicable for static YAML validation.
- Performance: Not applicable for static configuration checks.
- Security-focused: Not applicable; no auth or security logic is executed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _read_release_workflow() -> str:
    """Read the release workflow file with explicit error handling."""
    try:
        return WORKFLOW_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        pytest.fail(f"Release workflow not found at {WORKFLOW_PATH}: {exc}")


def _load_release_workflow_yaml() -> dict:
    """Parse the release workflow YAML and fail with context on errors."""
    content = _read_release_workflow()
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        pytest.fail(f"Invalid YAML syntax in {WORKFLOW_PATH}: {exc}")
    if not isinstance(data, dict):
        pytest.fail("Release workflow YAML did not parse into a mapping")
    return data


class TestReleaseWorkflow:
    """Release workflow validation tests."""

    def test_yaml_syntax_is_valid_and_has_jobs(self) -> None:
        """Happy path: YAML parses and includes expected top-level keys."""
        # Arrange
        # Act
        data = _load_release_workflow_yaml()

        # Assert
        assert data, "Release workflow YAML should not be empty"
        assert "jobs" in data, "Release workflow should define jobs"

    def test_changelog_format_includes_author_attribution(self) -> None:
        """Boundary: changelog format must include author attribution token."""
        # Arrange
        content = _read_release_workflow()

        # Act
        has_author_attribution = "by @%an" in content

        # Assert
        assert has_author_attribution, (
            "Changelog format must include author attribution 'by @%an'"
        )

    def test_docs_guides_links_are_not_broken(self) -> None:
        """Invalid/malformed: docs/guides links must resolve to files."""
        # Arrange
        content = _read_release_workflow()
        pattern = re.compile(r"docs/guides/[A-Za-z0-9._/-]+")

        # Act
        referenced_paths = pattern.findall(content)

        # Assert
        if not referenced_paths:
            return

        for raw_path in referenced_paths:
            sanitized = raw_path.rstrip(").,;\"' ")
            full_path = REPO_ROOT / sanitized
            assert full_path.exists(), f"Broken documentation link: {sanitized}"

    def test_contributor_acknowledgement_not_old_thank_you_format(self) -> None:
        """Error condition: old 'Thank you' contributor format should be absent."""
        # Arrange
        content = _read_release_workflow()

        # Act
        uses_old_format = re.search(r"thank you", content, re.IGNORECASE) is not None

        # Assert
        assert not uses_old_format, (
            "Contributor acknowledgement must not use the old 'Thank you' format"
        )

    def test_readme_reference_exists_for_installation_instructions(self) -> None:
        """Null/empty: README reference should exist for installation guidance."""
        # Arrange
        content = _read_release_workflow()

        # Act
        has_installation_section = "## Installation" in content
        has_readme_reference = "README.md" in content

        # Assert
        assert has_installation_section, (
            "Release body should include an Installation section"
        )
        assert has_readme_reference, (
            "Release body should reference README.md for installation instructions"
        )
