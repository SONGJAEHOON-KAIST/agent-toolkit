"""Wiki location override: `.code-wiki-dir` / `$CODE_WIKI_DIR` / default `wiki`.

The default must behave exactly as before (every other test in this suite runs
on the default). These tests cover a project whose `wiki/` is already taken, so
the code wiki lives at `docs/codewiki/`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from lib import config as cfg
from lib import links
from lib import wiki_path as wp

BIN = Path(__file__).resolve().parent.parent / "bin"


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.delenv(wp.ENV_VAR, raising=False)
    yield
    wp.configure(tmp_path / "__no_such_dir__")  # back to default for later tests


def _project(tmp_path: Path, wiki_dir: str | None = "docs/codewiki") -> Path:
    root = tmp_path / "proj"
    (root / "engine").mkdir(parents=True)
    (root / "engine" / "core.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "wiki").mkdir()  # the project's own, unrelated wiki
    (root / "wiki" / "index.md").write_text("---\ntitle: other\n---\n", encoding="utf-8")
    if wiki_dir:
        (root / wp.DIR_FILE).write_text(f"# comment\n{wiki_dir}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "init"], check=True)
    return root


def _bin(script: str, root: Path, *args: str, env: dict | None = None):
    e = dict(os.environ)
    e.pop(wp.ENV_VAR, None)
    e.update(env or {})
    e["CLAUDE_PLUGIN_ROOT"] = str(BIN.parent)
    return subprocess.run([sys.executable, str(BIN / script), "--project-root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", env=e)


# ── resolution ────────────────────────────────────────────────────────

def test_default_is_wiki(tmp_path):
    assert wp.configure(tmp_path) == PurePosixPath("wiki")


def test_file_sets_location(tmp_path):
    root = _project(tmp_path)
    assert wp.configure(root) == PurePosixPath("docs/codewiki")
    assert wp.source_folder_to_wiki("engine") == PurePosixPath("docs/codewiki/engine/index.md")
    assert wp.source_file_to_wiki("engine/core.py") == PurePosixPath("docs/codewiki/engine/core.md")


def test_env_wins_over_file(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setenv(wp.ENV_VAR, "kb/code")
    assert wp.configure(root) == PurePosixPath("kb/code")


@pytest.mark.parametrize("bad", ["", "/abs", "C:/abs", "../up", "a/../b", "./x",
                                 ".code-wiki/x", ".git"])
def test_unsafe_locations_rejected(bad):
    with pytest.raises(wp.WikiDirError):
        wp.validate_wiki_dir(bad)


def test_backslashes_and_trailing_slash_normalized():
    assert wp.validate_wiki_dir("docs\\codewiki\\") == PurePosixPath("docs/codewiki")


def test_wiki_to_source_folder_multi_part(tmp_path):
    wp.configure(_project(tmp_path))
    assert wp.wiki_to_source_folder("docs/codewiki/engine/index.md") == PurePosixPath("engine")
    assert wp.wiki_to_source_folder("docs/codewiki/engine/core.md") == PurePosixPath("engine")
    # the project's own wiki/ is NOT the code wiki
    assert wp.wiki_to_source_folder("wiki/engine/index.md") is None
    assert wp.wiki_to_source_folder("docs/other/x.md") is None


def test_link_classification_follows_wiki_dir(tmp_path):
    wp.configure(_project(tmp_path))
    page_dir = PurePosixPath("docs/codewiki/engine")
    assert links._classify("core.md", page_dir, ["engine"]) == ("wiki", "docs/codewiki/engine/core.md")
    assert links._classify("../../../engine/core.py", page_dir, ["engine"]) == ("source", "engine/core.py")
    # a link into the project's own wiki/ is not a code-wiki link
    assert links._classify("../../../wiki/index.md", page_dir, ["engine"])[0] == "other"


# ── config rules ──────────────────────────────────────────────────────

def test_config_loaded_from_wiki_dir(tmp_path):
    root = _project(tmp_path)
    d = root / "docs" / "codewiki"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("version: 1\nsource_roots:\n  - path: engine\n",
                                   encoding="utf-8")
    conf = cfg.load(root)
    assert conf["source_roots"] == [{"path": "engine"}]
    assert cfg.config_path().as_posix() == "docs/codewiki/config.yaml"


@pytest.mark.parametrize("src,msg", [("docs/codewiki/x", "reserved"), ("docs", "contains the wiki"),
                                     (".code-wiki", "reserved")])
def test_source_root_cannot_overlap_wiki_dir(tmp_path, src, msg):
    root = _project(tmp_path)
    (root / src).mkdir(parents=True, exist_ok=True)
    wp.configure(root)
    with pytest.raises(cfg.ConfigError, match=msg):
        cfg.validate({"version": 1, "source_roots": [{"path": src}]}, root)


def test_projects_own_wiki_dir_is_a_valid_source_root_when_moved(tmp_path):
    """With the code wiki moved, `wiki/` is just another folder (not reserved)."""
    root = _project(tmp_path)
    wp.configure(root)
    cfg.validate({"version": 1, "source_roots": [{"path": "wiki"}]}, root)


# ── end to end through the bin scripts ────────────────────────────────

def test_init_with_wiki_dir_records_location(tmp_path):
    root = _project(tmp_path, wiki_dir=None)
    r = _bin("init.py", root, "--source-roots", "engine", "--wiki-dir", "docs/codewiki")
    assert r.returncode == 0, r.stderr
    assert (root / "docs/codewiki/config.yaml").is_file()
    assert (root / "docs/codewiki/CLAUDE.md").is_file()
    assert (root / wp.DIR_FILE).read_text(encoding="utf-8").strip().endswith("docs/codewiki")
    # the project's own wiki/ is untouched
    assert sorted(p.name for p in (root / "wiki").iterdir()) == ["index.md"]
    assert _bin("wiki-dir.py", root).stdout.strip() == "docs/codewiki"


def test_init_without_wiki_dir_refuses_existing_wiki(tmp_path):
    root = _project(tmp_path, wiki_dir=None)
    r = _bin("init.py", root, "--source-roots", "engine")
    assert r.returncode != 0 and "--wiki-dir" in (r.stderr + r.stdout)


def test_init_refuses_conflicting_dir_file(tmp_path):
    root = _project(tmp_path)  # .code-wiki-dir → docs/codewiki
    r = _bin("init.py", root, "--source-roots", "engine", "--wiki-dir", "kb")
    assert r.returncode != 0 and "already points at" in (r.stderr + r.stdout)


def test_walk_tree_emits_paths_under_wiki_dir(tmp_path):
    root = _project(tmp_path, wiki_dir=None)
    assert _bin("init.py", root, "--source-roots", "engine",
                "--wiki-dir", "docs/codewiki").returncode == 0
    r = _bin("walk-tree.py", root)
    assert r.returncode == 0, r.stderr
    items = json.loads(r.stdout)
    items = items if isinstance(items, list) else items.get("items", [])
    assert items and all(i["wiki_path"].startswith("docs/codewiki/") for i in items)


def test_lint_reads_only_the_code_wiki(tmp_path):
    root = _project(tmp_path, wiki_dir=None)
    assert _bin("init.py", root, "--source-roots", "engine",
                "--wiki-dir", "docs/codewiki").returncode == 0
    r = _bin("lint.py", root)
    out = r.stdout
    assert "wiki/index.md" not in out  # the project's own wiki is never linted
    assert "config-invalid" not in out


def test_wiki_dir_script_rejects_unsafe_file(tmp_path):
    root = _project(tmp_path, wiki_dir="../outside")
    r = _bin("wiki-dir.py", root)
    assert r.returncode == 2 and "must not contain" in r.stderr


# ── precondition check (`--require-config`) ───────────────────────────

def test_require_config_checks_resolved_dir(tmp_path):
    """The 'wiki initialized?' check must look in the moved dir, not a literal wiki/."""
    root = _project(tmp_path)  # .code-wiki-dir → docs/codewiki; wiki/ is the project's own
    r = _bin("wiki-dir.py", root, "--require-config")
    assert r.returncode == 3 and "docs/codewiki/config.yaml not found" in r.stderr
    (root / "docs/codewiki").mkdir(parents=True)
    (root / "docs/codewiki/config.yaml").write_text("version: 1\n", encoding="utf-8")
    r = _bin("wiki-dir.py", root, "--require-config")
    assert r.returncode == 0 and r.stdout.strip() == "docs/codewiki"


def test_require_config_default_location(tmp_path):
    root = _project(tmp_path, wiki_dir=None)  # wiki/ exists but has no config.yaml
    r = _bin("wiki-dir.py", root, "--require-config")
    assert r.returncode == 3 and "wiki/config.yaml not found" in r.stderr


def test_commands_never_test_literal_wiki_config():
    """Every command's precondition goes through --require-config."""
    import re
    cmds = BIN.parent / "commands"
    for f in cmds.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"Verify `wiki/config\.yaml` exists", text), f.name
    for name in ["build.md", "sync.md", "query.md", "topic.md", "rebuild.md"]:
        assert "--require-config" in (cmds / name).read_text(encoding="utf-8"), name
