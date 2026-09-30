import json
import sys
import unittest
from unittest import mock

from tests.helpers import Repo

import status

CONFIG = "source_roots:\n  - path: src\nwiki_language: ko\n"


def wiki_state(sha, version=1):
    return json.dumps({"version": version, "last_ingested_sha": sha, "wiki_pages": {},
                       "source_to_wiki": {}, "source_hashes": {}})


class MapStatusTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("src/a.py")
        self.repo.write("docs/architecture/index.html", "<html><body></body></html>")
        self.repo.commit()
        self.map = self.repo.root / "docs/architecture/index.html"

    def tearDown(self):
        self.repo.cleanup()

    def check(self):
        return status.map_status(self.repo.root, self.map)

    def test_missing(self):
        self.assertEqual(status.map_status(self.repo.root, self.repo.root / "nope.html"),
                         {"state": "missing"})

    def test_unknown_without_sidecar(self):
        self.assertEqual(self.check()["state"], "unknown")

    def test_fresh_after_record(self):
        meta = status.record(self.repo.root, self.map, ["src"])
        self.assertFalse(meta["dirty"])
        self.assertEqual(self.check()["state"], "fresh")

    def test_committing_the_map_itself_keeps_it_fresh(self):
        status.record(self.repo.root, self.map, ["."])
        self.repo.write("docs/architecture/README.md")
        self.repo.commit()
        self.assertEqual(self.check()["state"], "fresh")

    def test_stale_when_scope_changes(self):
        status.record(self.repo.root, self.map, ["src"])
        self.repo.write("src/b.py")
        self.repo.commit()
        r = self.check()
        self.assertEqual(r["state"], "stale")
        self.assertEqual(r["changed"], 1)
        self.assertEqual(r["sample"], ["src/b.py"])

    def test_changes_outside_scope_do_not_count(self):
        status.record(self.repo.root, self.map, ["src"])
        self.repo.write("other/c.py")
        self.repo.commit()
        self.assertEqual(self.check()["state"], "fresh")

    def test_wiki_changes_never_count(self):
        status.record(self.repo.root, self.map, ["."])
        self.repo.write("wiki/src/index.md")
        self.repo.commit()
        self.assertEqual(self.check()["state"], "fresh")

    def test_uncommitted_changes_make_record_dirty(self):
        self.repo.write("src/a.py", "changed\n")
        meta = status.record(self.repo.root, self.map, ["src"])
        self.assertTrue(meta["dirty"])
        self.assertEqual(self.check()["state"], "unknown")

    def test_uncommitted_map_output_is_not_dirty(self):
        self.map.write_text("<html>rebuilt</html>")
        self.assertFalse(status.record(self.repo.root, self.map, ["."])["dirty"])

    def test_unknown_when_build_commit_is_gone(self):
        (self.map.parent / status.SIDECAR_NAME).write_text(json.dumps(
            {"version": 1, "sha": "0" * 40, "scope": ["."], "dirty": False}))
        self.assertEqual(self.check()["state"], "unknown")


class WikiStatusTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("src/a.py")
        self.repo.write("wiki/config.yaml", CONFIG)
        self.repo.write("wiki/src/index.md")
        self.sha = self.repo.commit()

    def tearDown(self):
        self.repo.cleanup()

    def check(self):
        return status.wiki_status(self.repo.root)

    def set_state(self, sha, version=1):
        self.repo.write(".code-wiki/state.json", wiki_state(sha, version))

    def test_missing(self):
        (self.repo.root / "wiki/config.yaml").unlink()
        self.assertEqual(self.check(), {"state": "missing"})

    def test_fresh_from_state(self):
        self.set_state(self.sha)
        r = self.check()
        self.assertEqual((r["state"], r["basis"]), ("fresh", "state"))

    def test_stale_from_state(self):
        self.set_state(self.sha)
        self.repo.write("src/b.py")
        self.repo.commit()
        self.assertEqual(self.check()["state"], "stale")

    def test_source_roots_limit_what_counts(self):
        self.set_state(self.sha)
        self.repo.write("README.md")
        self.repo.commit()
        r = self.check()
        self.assertEqual(r["state"], "fresh")
        self.assertEqual(r["source_roots"], ["src"])

    def test_without_pyyaml_the_whole_repo_counts(self):
        self.set_state(self.sha)
        self.repo.write("README.md")
        self.repo.commit()
        with mock.patch.dict(sys.modules, {"yaml": None}):
            r = self.check()
        self.assertEqual(r["state"], "stale")
        self.assertIsNone(r["source_roots"])

    def test_inferred_from_git_log_without_state(self):
        r = self.check()
        self.assertEqual((r["state"], r["basis"], r["sha"]), ("fresh", "inferred", self.sha))
        self.repo.write("src/b.py")
        self.repo.commit()
        self.assertEqual(self.check()["state"], "stale")

    def test_unknown_when_wiki_never_committed(self):
        repo = Repo()
        try:
            repo.write("src/a.py")
            repo.commit()
            repo.write("wiki/config.yaml", CONFIG)
            self.assertEqual(status.wiki_status(repo.root)["state"], "unknown")
        finally:
            repo.cleanup()

    def test_unknown_on_other_state_version(self):
        self.set_state(self.sha, version=2)
        self.assertEqual(self.check()["state"], "unknown")

    def test_unknown_on_null_ingest_sha(self):
        self.set_state(None)
        self.assertEqual(self.check()["state"], "unknown")

    def test_check_writes_nothing(self):
        self.repo.write("src/b.py")
        self.repo.commit()
        before = self.repo.git("status", "--porcelain", "--ignored")
        status.wiki_status(self.repo.root)
        status.map_status(self.repo.root, self.repo.root / "docs/index.html")
        self.assertEqual(self.repo.git("status", "--porcelain", "--ignored"), before)
        self.assertFalse((self.repo.root / ".code-wiki").exists())


class SubdirWikiTest(unittest.TestCase):
    """A monorepo: wikis live next to their sub-projects, not at the repo root."""

    def setUp(self):
        self.repo = Repo()
        self.repo.write("web/api/src/a.py")
        self.repo.write("web/api/wiki/config.yaml", CONFIG)
        self.repo.write("web/api/wiki/src/index.md")
        self.repo.write("web/ui/src/b.ts")
        self.repo.write("web/ui/wiki/config.yaml", CONFIG)
        self.repo.write("web/ui/wiki/src/index.md")
        self.sha = self.repo.commit()

    def tearDown(self):
        self.repo.cleanup()

    def set_state(self, dir_, sha):
        self.repo.write(f"{dir_}/.code-wiki/state.json", wiki_state(sha))

    def test_root_is_missing_and_lists_candidates(self):
        combined, each = status.wikis_status(self.repo.root)
        self.assertEqual(combined["state"], "missing")
        self.assertEqual(combined["candidates"], ["web/api", "web/ui"])
        self.assertEqual(each, [{"dir": ".", "state": "missing"}])

    def test_no_candidates_when_dirs_are_given(self):
        combined, _ = status.wikis_status(self.repo.root, ["web/nope"])
        self.assertEqual(combined["state"], "missing")
        self.assertNotIn("candidates", combined)

    def test_fresh_from_state_in_subdir(self):
        self.set_state("web/api", self.sha)
        r = status.wiki_status(self.repo.root, "web/api")
        self.assertEqual((r["state"], r["basis"], r["source_roots"]), ("fresh", "state", ["src"]))

    def test_source_roots_are_rebased_onto_the_wiki_dir(self):
        self.set_state("web/api", self.sha)
        self.repo.write("web/ui/src/c.ts")      # the other sub-project
        self.repo.write("web/api/README.md")    # outside the api wiki's source_roots
        self.repo.commit()
        self.assertEqual(status.wiki_status(self.repo.root, "web/api")["state"], "fresh")
        self.repo.write("web/api/src/d.py")
        self.repo.commit()
        r = status.wiki_status(self.repo.root, "web/api")
        self.assertEqual((r["state"], r["sample"]), ("stale", ["web/api/src/d.py"]))

    def test_own_wiki_output_never_counts(self):
        self.set_state("web/api", self.sha)
        with mock.patch.dict(sys.modules, {"yaml": None}):  # whole wiki dir is the scope
            self.repo.write("web/api/wiki/src/other.md")
            self.repo.commit()
            self.assertEqual(status.wiki_status(self.repo.root, "web/api")["state"], "fresh")

    def test_inferred_from_the_subdir_wiki_commit(self):
        r = status.wiki_status(self.repo.root, "web/ui")
        self.assertEqual((r["state"], r["basis"], r["sha"]), ("fresh", "inferred", self.sha))

    def test_combined_is_the_worst(self):
        self.set_state("web/api", self.sha)
        self.set_state("web/ui", self.sha)
        self.repo.write("web/api/src/x.py")
        self.repo.write("web/ui/src/y.ts")
        self.repo.write("web/ui/src/z.ts")
        self.repo.commit()
        combined, each = status.wikis_status(self.repo.root, ["web/api", "web/ui"])
        self.assertEqual(combined, {"state": "stale", "changed": 3})
        self.assertEqual([w["dir"] for w in each], ["web/api", "web/ui"])
        combined, _ = status.wikis_status(self.repo.root, ["web/api", "web/nope"])
        self.assertEqual(combined["state"], "missing")
        self.assertIn("web/nope: missing", combined["reason"])

    def test_single_dir_combined_equals_its_status(self):
        self.set_state("web/api", self.sha)
        combined, each = status.wikis_status(self.repo.root, ["web/api"])
        self.assertEqual(combined, {k: v for k, v in each[0].items() if k != "dir"})

    def test_map_ignores_subdir_wiki_output(self):
        m = self.repo.write("docs/index.html", "<html></html>")
        self.repo.commit()
        status.record(self.repo.root, m, ["."])
        self.repo.write("web/api/wiki/src/new.md")
        self.repo.commit()
        self.assertEqual(status.map_status(self.repo.root, m)["state"], "stale")
        self.assertEqual(status.map_status(self.repo.root, m, ["web/api"])["state"], "fresh")

    def test_normalize(self):
        root = self.repo.root
        self.assertEqual(status.normalize_wiki_dirs(root, None), ["."])
        self.assertEqual(status.normalize_wiki_dirs(root, ["./web/api/", "web/api", str(root / "web/ui")]),
                         ["web/api", "web/ui"])
        with self.assertRaises(SystemExit):
            status.normalize_wiki_dirs(root, ["../elsewhere"])


class CliTest(unittest.TestCase):
    def test_check_prints_both(self):
        repo = Repo()
        try:
            repo.write("src/a.py")
            repo.commit()
            with mock.patch("builtins.print") as p:
                status.main(["check", "--root", str(repo.root), "--map", "docs/index.html"])
            out = json.loads(p.call_args[0][0])
            self.assertEqual(out["map"]["state"], "missing")
            self.assertEqual(out["wiki"]["state"], "missing")
            self.assertEqual(out["wikis"], [{"dir": ".", "state": "missing"}])
        finally:
            repo.cleanup()

    def test_check_with_wiki_dirs(self):
        repo = Repo()
        try:
            repo.write("pkg/src/a.py")
            repo.write("pkg/wiki/config.yaml", CONFIG)
            repo.commit()
            with mock.patch("builtins.print") as p:
                status.main(["check", "--root", str(repo.root), "--map", "docs/index.html",
                             "--wiki", "pkg"])
            out = json.loads(p.call_args[0][0])
            self.assertEqual(out["wiki"]["state"], "fresh")
            self.assertEqual([w["dir"] for w in out["wikis"]], ["pkg"])
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
