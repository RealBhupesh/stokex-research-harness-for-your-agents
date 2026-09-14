import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def shipped_files():
    ignored_parts = {".git", ".worktrees", "__pycache__"}
    return {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in ignored_parts for part in path.relative_to(ROOT).parts)
        and path.suffix != ".pyc"
    }


class ManifestTests(unittest.TestCase):
    def test_manifest_is_exact_and_versioned(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "3.0.0")
        self.assertEqual(set(manifest["files"]), shipped_files())

    def test_required_v3_files_exist(self):
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
        }
        self.assertTrue(required <= shipped_files())


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
