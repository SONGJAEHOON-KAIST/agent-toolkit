#!/usr/bin/env python3
"""Print the project's wiki directory (project-root-relative POSIX path).

    python3 wiki-dir.py --project-root "$(pwd)"
      → wiki            (default)
      → docs/codewiki   (when `.code-wiki-dir` or $CODE_WIKI_DIR says so)

Commands use this to resolve every `wiki/` they mention — see lib/wiki_path.py.
Exit 2 with a message on stderr if the configured location is not a safe
relative path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import wiki_path as wp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the resolved wiki directory.")
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(wp.configure(args.project_root.resolve()))
    except wp.WikiDirError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
