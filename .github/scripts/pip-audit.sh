#!/usr/bin/env bash
# Audit every locked dependency (runtime + all dependency groups) for known vulnerabilities.
# Exits non-zero when pip-audit finds a vulnerability that is not in the allowlist.
set -euo pipefail

# Pinned so a new pip-audit release cannot change CI behaviour silently.
PIP_AUDIT_VERSION="2.10.1"
ALLOWLIST=".github/pip-audit-allowlist.txt"
# Every supported Python version (same list as the test matrix in ci.yml; checked by tests/test_workflows.py).
PYTHON_VERSIONS=("3.10" "3.11" "3.12" "3.13" "3.14")

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# Export the exact pinned versions from uv.lock; the project itself is not on PyPI under this version.
uv export --frozen --all-groups --no-hashes --no-emit-project --output-file "$workdir/requirements.txt" >/dev/null

# Build one --ignore-vuln flag per allowlisted ID (text before '#', blank lines skipped).
ignore_args=()
if [[ -f "$ALLOWLIST" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    vuln_id="$(echo "${line%%#*}" | xargs)"
    if [[ -n "$vuln_id" ]]; then
      ignore_args+=(--ignore-vuln "$vuln_id")
    fi
  done <"$ALLOWLIST"
fi

# pip-audit evaluates environment markers with the interpreter it runs on and silently skips
# lines that do not match (e.g. `python_full_version < '3.11'`). The lock pins different versions
# per Python, so audit the same export once per supported version (keep in sync with ci.yml).
failed_versions=()
for python_version in "${PYTHON_VERSIONS[@]}"; do
  echo "::group::pip-audit on Python ${python_version}"
  # --no-deps/--disable-pip: the export is already fully resolved, so audit it as-is.
  if ! uvx --python "$python_version" "pip-audit==${PIP_AUDIT_VERSION}" \
    --requirement "$workdir/requirements.txt" \
    --no-deps \
    --disable-pip \
    --progress-spinner off \
    "${ignore_args[@]}"; then
    failed_versions+=("$python_version")
  fi
  echo "::endgroup::"
done

# Fail if any single Python version has a known vulnerability.
if ((${#failed_versions[@]} > 0)); then
  echo "pip-audit found vulnerabilities on Python: ${failed_versions[*]}" >&2
  exit 1
fi
