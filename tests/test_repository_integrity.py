import json
import pathlib
import re
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _is_runtime_output(path):
    relative_parts = path.relative_to(ROOT).parts
    return (
        path.suffix in {".sqlite", ".sqlite3", ".db"}
        or (path.name.startswith("evidence-packet-") and path.suffix == ".json")
        or "stockex-output" in relative_parts
    )


def shipped_files():
    ignored_parts = {".git", ".worktrees", ".superpowers", "__pycache__"}
    return {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in ignored_parts for part in path.relative_to(ROOT).parts)
        and path.suffix != ".pyc"
        and not _is_runtime_output(path)
    }


class ManifestTests(unittest.TestCase):
    def test_manifest_is_exact_and_versioned(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "4.0.0-dev1")
        self.assertEqual(manifest["files"], sorted(set(manifest["files"])))
        self.assertEqual(set(manifest["files"]), shipped_files())

    def test_required_v4_files_exist(self):
        required = {
            "scripts/market_intelligence.py",
            "scripts/decision_packet.py",
            "scripts/forecasting.py",
            "scripts/portfolio_execution.py",
            "scripts/calibration.py",
            "schema/decision-packet.schema.json",
            "skills/india-equity-market-intelligence/SKILL.md",
            "skills/india-equity-evidence-room/SKILL.md",
            "skills/india-equity-variant-perception/SKILL.md",
            "skills/india-equity-investment-committee/SKILL.md",
            "skills/india-equity-thesis-monitor/SKILL.md",
            "stockex/__init__.py",
            "stockex/cli.py",
            "stockex/store/__init__.py",
            "stockex/store/database.py",
            "stockex/store/importer.py",
            "stockex/store/records.py",
            "stockex/store/schema.py",
            "tests/test_store_cli.py",
            "tests/test_store_database.py",
            "tests/test_store_queries.py",
            "tests/test_store_records.py",
            "tests/test_store_schema.py",
            "docs/superpowers/plans/2026-09-15-point-in-time-data-foundation.md",
            "docs/superpowers/specs/2026-09-15-point-in-time-data-foundation-design.md",
        }
        self.assertTrue(required <= shipped_files())

    def test_runtime_outputs_are_ignored(self):
        ignored = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertTrue(
            {
                "*.sqlite",
                "*.sqlite3",
                "*.db",
                "evidence-packet-*.json",
                "stockex-output/",
                ".superpowers/",
            } <= ignored
        )

    def test_shipped_files_excludes_runtime_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="runtime-output-test-") as temporary:
            temporary_root = pathlib.Path(temporary)
            runtime_files = [
                temporary_root / "research.sqlite",
                temporary_root / "research.sqlite3",
                temporary_root / "research.db",
                temporary_root / "evidence-packet-test.json",
                temporary_root / "stockex-output" / "results.json",
            ]
            for runtime_file in runtime_files:
                runtime_file.parent.mkdir(parents=True, exist_ok=True)
                runtime_file.touch()
            retained_file = temporary_root / "keep.txt"
            retained_file.touch()

            shipped = shipped_files()

        self.assertTrue(retained_file.relative_to(ROOT).as_posix() in shipped)
        self.assertTrue(
            all(runtime_file.relative_to(ROOT).as_posix() not in shipped for runtime_file in runtime_files)
        )


class MarkdownIntegrityTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        missing = []
        for document in ROOT.rglob("*.md"):
            if any(part in {".git", ".worktrees"} for part in document.relative_to(ROOT).parts):
                continue
            for target in pattern.findall(document.read_text(encoding="utf-8")):
                clean = target.split("#", 1)[0].strip()
                if not clean or clean.startswith(("http://", "https://", "mailto:", "sandbox:")):
                    continue
                if not (document.parent / clean).resolve().exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {clean}")
        self.assertEqual(missing, [])

    def test_every_skill_has_name_and_description(self):
        failures = []
        skill_files = [ROOT / "SKILL.md", *sorted((ROOT / "skills").glob("*/SKILL.md"))]
        for skill_file in skill_files:
            text = skill_file.read_text(encoding="utf-8")
            if not text.startswith("---\n") or "\nname:" not in text or "\ndescription:" not in text:
                failures.append(skill_file.relative_to(ROOT).as_posix())
        self.assertEqual(failures, [])
        self.assertEqual(len(skill_files), 12)


if __name__ == "__main__":
    unittest.main()
