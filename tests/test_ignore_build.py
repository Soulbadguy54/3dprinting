"""Vercel docs-only deployment guard: fail open on code and unknown Git history."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ignore-docs-build.sh"


class IgnoreDocumentationBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.commit("src/App.tsx", "original", "initial application")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, text=True,
            capture_output=True, check=True,
        )

    def commit(self, path, content, message):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self.git("add", path)
        self.git("commit", "-qm", message)

    def check(self, previous=None):
        env = os.environ.copy()
        env.pop("VERCEL_GIT_PREVIOUS_SHA", None)
        if previous:
            env["VERCEL_GIT_PREVIOUS_SHA"] = previous
        return subprocess.run(
            ["bash", str(SCRIPT)], cwd=self.repo, env=env,
            text=True, capture_output=True,
        )

    def test_only_knowledge_files_skip_deployment(self):
        self.commit("AGENTS.md", "instructions", "document rules")
        self.commit("docs/PROJECT_CONTEXT.md", "updated", "document context")
        self.commit("CHANGELOG.md", "updated", "document history")
        self.assertEqual(self.check(previous=self.base).returncode, 0)

    def test_changed_app_always_builds_even_when_last_commit_is_docs(self):
        self.commit("src/App.tsx", "updated", "application change")
        self.commit("CHANGELOG.md", "updated", "document change")
        result = self.check(previous=self.base)
        self.assertEqual(result.returncode, 1)
        self.assertIn("src/App.tsx", result.stdout)

    def test_new_configuration_triggers_build(self):
        self.commit("vercel.json", "{}", "config change")
        self.assertEqual(self.check(previous=self.base).returncode, 1)

    def test_git_history_unavailable_triggers_build(self):
        self.commit("docs/DECISIONS.md", "new", "docs only")
        self.assertEqual(self.check(previous="a" * 40).returncode, 1)

    def test_first_commit_cannot_be_safely_skipped(self):
        self.assertEqual(self.check().returncode, 1)

    def test_single_docs_commit_without_previous_sha_skips(self):
        self.commit("docs/DECISIONS.md", "new", "docs only")
        self.assertEqual(self.check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
