"""Static checks on the GitHub Actions workflows (supply-chain and release safety)."""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))

# Events whose runs can be started by a pull request (directly or through another workflow).
PR_REACHABLE_EVENTS = {"pull_request", "pull_request_target", "workflow_run"}

# `uses: owner/repo[/path]@<40-hex SHA> # vX.Y.Z`
PINNED_USES = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> set[str]:
    # PyYAML (YAML 1.1) parses the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(event) for event in on}
    return {str(event) for event in (on or {})}


def _uses_lines(path: Path) -> list[str]:
    # Raw text is needed to see the version comment that follows the SHA.
    values = []
    for line in path.read_text().splitlines():
        match = re.match(r"^\s*(?:-\s+)?uses:\s*(.+?)\s*$", line)
        if match:
            values.append(match.group(1))
    return values


def test_workflow_files_found():
    assert WORKFLOWS_DIR / "publish.yml" in WORKFLOW_FILES
    assert WORKFLOWS_DIR / "ci.yml" in WORKFLOW_FILES


def test_publish_is_not_reachable_from_pull_requests():
    triggers = _triggers(_load(WORKFLOWS_DIR / "publish.yml"))
    assert triggers, "publish.yml has no triggers"
    assert not triggers & PR_REACHABLE_EVENTS, f"publish.yml must not run on {triggers & PR_REACHABLE_EVENTS}"


def test_publish_requires_ci_before_uploading():
    jobs = _load(WORKFLOWS_DIR / "publish.yml")["jobs"]
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"

    def ancestors(name: str) -> set[str]:
        needs = jobs[name].get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        result = set(needs)
        for parent in needs:
            result |= ancestors(parent)
        return result

    # Every job that can mint an OIDC token or write to the repo must run after CI.
    privileged = [
        name
        for name, job in jobs.items()
        if (job.get("permissions") or {}).get("id-token") == "write"
        or (job.get("permissions") or {}).get("contents") == "write"
    ]
    assert privileged, "expected at least one privileged publish job"
    for name in privileged:
        assert "ci" in ancestors(name), f"job {name!r} does not depend on CI"


def test_ci_is_reusable_by_publish():
    assert "workflow_call" in _triggers(_load(WORKFLOWS_DIR / "ci.yml"))


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_workflow_declares_top_level_permissions(path: Path):
    assert "permissions" in _load(path), f"{path.name} relies on the default GITHUB_TOKEN permissions"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_actions_are_pinned_to_full_sha(path: Path):
    for uses in _uses_lines(path):
        if uses.startswith("./"):
            # Local reusable workflows/actions are versioned with the repo itself.
            continue
        assert PINNED_USES.match(uses), f"{path.name}: {uses!r} is not pinned to a full SHA with a version comment"
