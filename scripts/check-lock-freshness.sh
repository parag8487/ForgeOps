#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# scripts/check-lock-freshness.sh — regenerate both backend lockfiles in an
# isolated copy and fail if either committed lock differs (design.md §7.7, §8.3).
#
# Why an isolated COPY of the inputs rather than a bare temp output path:
# pip-compile records its own invocation in the generated header, including the
# --output-file value. Writing to /tmp/xxxx/requirements.lock would therefore
# always differ from the committed file in that one comment line and report a
# false staleness. The check instead copies pyproject.toml into a temp directory
# and regenerates with the SAME relative output filename, so a clean tree
# produces byte-identical output including the header.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# shellcheck source=scripts/lib/pip-compile.sh
. "$SCRIPT_DIR/lib/pip-compile.sh"
resolve_pip_compile "$REPO_ROOT"

TMPDIR_LOCK="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCK"' EXIT

cp "$BACKEND_DIR/pyproject.toml" "$TMPDIR_LOCK/pyproject.toml"

printf '==> check-lock-freshness: regenerating both locks in an isolated copy\n'

cd "$TMPDIR_LOCK"

run_pip_compile \
	--generate-hashes \
	--allow-unsafe \
	--strip-extras \
	--output-file=requirements.lock \
	--quiet \
	pyproject.toml

run_pip_compile \
	--generate-hashes \
	--allow-unsafe \
	--strip-extras \
	--extra=dev \
	--output-file=requirements-dev.lock \
	--quiet \
	pyproject.toml

cd "$REPO_ROOT"

FAILED=0

for lock in requirements.lock requirements-dev.lock; do
	# Committed files may be checked out CRLF on Windows; compare content, not
	# line-ending policy, so a correct lock is never reported stale.
	if diff -u --strip-trailing-cr "$BACKEND_DIR/$lock" "$TMPDIR_LOCK/$lock" >/dev/null 2>&1; then
		printf 'ok:   %s is up to date\n' "$lock"
	else
		printf 'ERROR: backend/%s is stale. Run: make lock-backend\n' "$lock" >&2
		diff -u --strip-trailing-cr "$BACKEND_DIR/$lock" "$TMPDIR_LOCK/$lock" >&2 || true
		FAILED=1
	fi
done

if [ "$FAILED" -eq 1 ]; then
	exit 1
fi

printf 'check-lock-freshness: both lockfiles are up to date\n'
