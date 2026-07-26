#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# scripts/lib/pip-compile.sh — resolve the pinned pip-compile entry point.
#
# Sourced by scripts/lock-backend.sh and scripts/check-lock-freshness.sh.
#
# design.md §7.7 and §16.2 make `pip-tools==7.4.1` the ONLY lock generator, so
# this resolver refuses any other version rather than silently producing a lock
# with different resolution behaviour. `pip-compile` is frequently not on PATH
# (it lives inside the backend virtualenv), so the venv is searched first and the
# module entry point `python -m piptools compile` is used, which works on both
# Windows (Scripts/) and POSIX (bin/) layouts.
#
# Exports: PIP_COMPILE_CMD (an array-safe command string is avoided; callers use
# the run_pip_compile function instead).

PIP_TOOLS_REQUIRED_VERSION="${FORGEOPS_PIP_TOOLS_VERSION:-7.4.1}"

_PIP_COMPILE_PYTHON=""

_pip_compile_probe_python() {
	# _pip_compile_probe_python <python executable>
	[ -n "${1:-}" ] || return 1
	command -v "$1" >/dev/null 2>&1 || [ -x "$1" ] || return 1
	"$1" -c 'import piptools' >/dev/null 2>&1 || return 1
	# `python -m piptools` has no --version flag (only the pip-compile console
	# script does), so the installed distribution metadata is authoritative.
	_version=$("$1" -c 'import importlib.metadata as m; print(m.version("pip-tools"))' 2>/dev/null | tr -d '\r')
	[ -n "$_version" ] || return 1
	if [ "$_version" != "$PIP_TOOLS_REQUIRED_VERSION" ]; then
		printf 'note: %s has pip-tools %s, but ==%s is pinned; ignoring it\n' \
			"$1" "$_version" "$PIP_TOOLS_REQUIRED_VERSION" >&2
		return 1
	fi
	_PIP_COMPILE_PYTHON="$1"
	return 0
}

resolve_pip_compile() {
	# resolve_pip_compile <repo root>
	_root="${1:?resolve_pip_compile needs the repository root}"

	for _candidate in \
		"${FORGEOPS_PYTHON:-}" \
		"$_root/backend/.venv/Scripts/python.exe" \
		"$_root/backend/.venv/bin/python" \
		"$_root/.venv/Scripts/python.exe" \
		"$_root/.venv/bin/python" \
		python3 \
		python; do
		if _pip_compile_probe_python "$_candidate"; then
			printf 'using pip-tools %s via %s\n' "$PIP_TOOLS_REQUIRED_VERSION" "$_PIP_COMPILE_PYTHON"
			return 0
		fi
	done

	printf 'ERROR: pip-tools==%s not found.\n' "$PIP_TOOLS_REQUIRED_VERSION" >&2
	printf '       Create the backend virtualenv and install the pinned generator:\n' >&2
	printf '         py -3.13 -m venv backend/.venv\n' >&2
	printf "         backend/.venv/Scripts/python -m pip install 'pip-tools==%s'\n" \
		"$PIP_TOOLS_REQUIRED_VERSION" >&2
	return 1
}

run_pip_compile() {
	# run_pip_compile <pip-compile arguments...>
	if [ -z "$_PIP_COMPILE_PYTHON" ]; then
		printf 'ERROR: run_pip_compile called before resolve_pip_compile succeeded\n' >&2
		return 1
	fi
	"$_PIP_COMPILE_PYTHON" -m piptools compile "$@"
}
