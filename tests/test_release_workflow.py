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

    def test_changelog_format_uses_non_tagging_author_attribution(self) -> None:
        """Boundary: changelog format must include author names without GitHub tagging."""
        # Arrange
        content = _read_release_workflow()

        # Act
        has_author_attribution = "by %an" in content
        has_tagging_author_attribution = "by @%an" in content

        # Assert
        assert has_author_attribution, (
            "Changelog format must include author attribution 'by %an'"
        )
        assert not has_tagging_author_attribution, (
            "Changelog format must not include GitHub-tagging author attribution 'by @%an'"
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

    def test_contributor_acknowledgement_uses_thank_you_message(self) -> None:
        """Error condition: workflow must include the thank-you contributor message."""
        # Arrange
        content = _read_release_workflow()

        # Act
        thank_you_occurrences = len(
            re.findall(r"\*\*Thank you to all contributors!\*\*", content)
        )

        # Assert
        assert thank_you_occurrences >= 2, (
            "Contributor acknowledgement must include '**Thank you to all contributors!**' "
            "in both stable and nightly release sections"
        )

    def test_contributor_list_generation_is_removed(self) -> None:
        """Error condition: contributor list files should not be generated in workflow."""
        # Arrange
        content = _read_release_workflow()

        # Act
        has_stable_contributors_file = "CONTRIBUTORS.md" in content
        has_nightly_contributors_file = "NIGHTLY_CONTRIBUTORS.md" in content

        # Assert
        assert not has_stable_contributors_file, (
            "Stable release workflow must not generate CONTRIBUTORS.md"
        )
        assert not has_nightly_contributors_file, (
            "Nightly release workflow must not generate NIGHTLY_CONTRIBUTORS.md"
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
