#!/usr/bin/env bash
# Audit every locked dependency (runtime + all dependency groups) for known vulnerabilities.
# Exits non-zero when pip-audit finds a vulnerability that is not in the allowlist.
set -euo pipefail

# Pinned so a new pip-audit release cannot change CI behaviour silently.
PIP_AUDIT_VERSION="2.10.1"
ALLOWLIST=".github/pip-audit-allowlist.txt"

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

# --no-deps/--disable-pip: the export is already fully resolved, so audit it as-is.
uvx "pip-audit==${PIP_AUDIT_VERSION}" \
  --requirement "$workdir/requirements.txt" \
  --no-deps \
  --disable-pip \
  --progress-spinner off \
  "${ignore_args[@]}"
