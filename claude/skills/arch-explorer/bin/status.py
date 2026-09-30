#!/usr/bin/env python3
"""Is the architecture map fresh, and is the code-wiki fresh?

Read-only: this never writes to the work tree, `wiki/` or `.code-wiki/`,
except for `record`, which writes the map's sidecar on request.

    status.py check  --root <repo> --map <index.html>
    status.py record --root <repo> --map <index.html> --scope <path> [--scope …]

`check` prints {"map": {...}, "wiki": {...}} as JSON.

Map states:  missing | unknown | stale | fresh
Wiki states: missing | unknown | stale | fresh
(`no-plugin` is decided by the open skill, which can see installed skills.)

The wiki check reads code-wiki's on-disk contract only — `wiki/config.yaml`
and `.code-wiki/state.json` (schema v1) — and never imports or runs code-wiki.
It is conservative: `ignore_patterns` are not applied, so it may call a wiki
stale when only ignored files changed (sync then reports "up to date"), but
it never calls a stale wiki fresh.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_NAME = "arch-explorer.json"
SIDECAR_VERSION = 1
WIKI_STATE_VERSION = 1
SAMPLE = 10
# Never counted as source changes: they are outputs, not inputs.
ALWAYS_EXCLUDED = ("wiki/", ".code-wiki/")


def _git(root: Path, *args: str) -> str | None:
    """Run git in `root`; None when git fails (not a repo, unknown sha, …)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout


def _head(root: Path) -> str | None:
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out else None


def _is_commit(root: Path, sha: str) -> bool:
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}") is not None


def _changed(root: Path, base: str, paths: list[str], exclude: list[str]) -> list[str] | None:
    """Files changed between `base` and HEAD under `paths`, minus `exclude` prefixes."""
    out = _git(root, "diff", "--name-only", base, "HEAD", "--", *paths)
    if out is None:
        return None
    prefixes = [p if p.endswith("/") else p + "/" for p in exclude]
    return [
        f for f in out.splitlines()
        if f and not any(f == p.rstrip("/") or f.startswith(p) for p in prefixes)
    ]


def _rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _changes_result(changed: list[str], base: str) -> dict:
    if changed:
        return {"state": "stale", "sha": base, "changed": len(changed),
                "sample": changed[:SAMPLE]}
    return {"state": "fresh", "sha": base}


# ---------------------------------------------------------------- map

def map_status(root: Path, map_path: Path) -> dict:
    if not map_path.is_file():
        return {"state": "missing"}
    sidecar = map_path.parent / SIDECAR_NAME
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": "unknown", "reason": "no sidecar (map built before 0.3.0)"}
    except (OSError, json.JSONDecodeError) as e:
        return {"state": "unknown", "reason": f"unreadable sidecar: {e}"}
    if not isinstance(meta, dict) or meta.get("version") != SIDECAR_VERSION:
        return {"state": "unknown", "reason": "unsupported sidecar version"}
    if meta.get("dirty"):
        return {"state": "unknown", "sha": meta.get("sha"),
                "reason": "built from uncommitted changes"}
    sha = meta.get("sha")
    if not isinstance(sha, str) or not _is_commit(root, sha):
        return {"state": "unknown", "reason": f"build commit {sha!r} not found"}
    scope = meta.get("scope") or ["."]
    exclude = list(ALWAYS_EXCLUDED)
    out_dir = _rel(root, map_path.parent)
    if out_dir and out_dir != ".":
        exclude.append(out_dir)
    changed = _changed(root, sha, scope, exclude)
    if changed is None:
        return {"state": "unknown", "reason": "git diff failed"}
    result = _changes_result(changed, sha)
    result["built_at"] = meta.get("built_at")
    result["scope"] = scope
    return result


def record(root: Path, map_path: Path, scope: list[str]) -> dict:
    """Write the sidecar next to the map: which commit and scope it was built from."""
    head = _head(root)
    if head is None:
        raise SystemExit("record: not a git repository (or no commits yet)")
    scope = scope or ["."]
    porcelain = _git(root, "status", "--porcelain", "--", *scope) or ""
    out_dir = _rel(root, map_path.parent)
    dirty = any(
        line and not (out_dir and out_dir != "." and line[3:].startswith(out_dir + "/"))
        for line in porcelain.splitlines()
    )
    meta = {
        "version": SIDECAR_VERSION,
        "sha": head,
        "scope": scope,
        "dirty": dirty,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (map_path.parent / SIDECAR_NAME).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# ---------------------------------------------------------------- wiki

def _source_roots(root: Path) -> list[str] | None:
    """source_roots from wiki/config.yaml; None when PyYAML is absent or the file is odd."""
    try:
        import yaml  # code-wiki's own dependency; optional here
    except ImportError:
        return None
    try:
        data = yaml.safe_load((root / "wiki/config.yaml").read_text(encoding="utf-8"))
    except Exception:
        return None
    entries = data.get("source_roots") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None
    paths = []
    for e in entries:
        p = e.get("path") if isinstance(e, dict) else e
        if not isinstance(p, str) or not p:
            return None
        paths.append(p)
    return paths


def wiki_status(root: Path) -> dict:
    if not (root / "wiki/config.yaml").is_file():
        return {"state": "missing"}
    state_path = root / ".code-wiki/state.json"
    base, basis = None, None
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "unknown", "reason": "unreadable .code-wiki/state.json"}
        if not isinstance(state, dict) or state.get("version") != WIKI_STATE_VERSION:
            return {"state": "unknown", "reason": "unsupported code-wiki state version"}
        base, basis = state.get("last_ingested_sha"), "state"
    else:
        # Same inference code-wiki's bootstrap uses, without writing state.json.
        out = _git(root, "log", "-1", "--format=%H", "--", "wiki/")
        base, basis = (out.strip() or None) if out else None, "inferred"
    if not base:
        return {"state": "unknown", "reason": "no ingest commit recorded or inferable"}
    if not _is_commit(root, base):
        return {"state": "unknown", "reason": f"ingest commit {base} not found"}
    roots = _source_roots(root)
    changed = _changed(root, base, roots or ["."], list(ALWAYS_EXCLUDED))
    if changed is None:
        return {"state": "unknown", "reason": "git diff failed"}
    result = _changes_result(changed, base)
    result["basis"] = basis
    result["source_roots"] = roots  # None means "whole repo" (conservative)
    return result


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True, type=Path)
        p.add_argument("--map", required=True, type=Path)
        if name == "record":
            p.add_argument("--scope", action="append", default=[])
    args = ap.parse_args(argv)
    root = args.root.resolve()
    map_path = (args.map if args.map.is_absolute() else root / args.map).resolve()
    if args.cmd == "record":
        out = record(root, map_path, args.scope)
    else:
        out = {"map": map_status(root, map_path), "wiki": wiki_status(root)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
