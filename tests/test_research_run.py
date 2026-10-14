import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from stockex.cli import main
from stockex.research_run import run_research, verify_research_bundle


FIXTURE = Path(__file__).parent / "fixtures" / "research-synthesis.json"


class ResearchRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "input.json"
        self.source.write_bytes(FIXTURE.read_bytes())
        self.output = self.root / "bundle"

    def test_supplied_example_is_frozen_and_deterministically_replayed(self):
        result = run_research(self.source, self.output)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["synthetic_example"])
        self.assertTrue(verify_research_bundle(self.output)["valid"])
        self.source.write_text("changed caller file")
        self.assertTrue(verify_research_bundle(self.output)["valid"])

    def test_missing_specialist_writes_inspectable_blocked_bundle(self):
        supplied = json.loads(self.source.read_text())
        supplied["reports"].pop()
        self.source.write_text(json.dumps(supplied))
        result = run_research(self.source, self.output)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["decision"]["ic_action"], "RETURN_FOR_WORK")
        self.assertTrue(verify_research_bundle(self.output)["valid"])

    def test_changed_result_is_detected_by_hash_and_replay(self):
        run_research(self.source, self.output)
        path = self.output / "result.json"
        data = json.loads(path.read_text())
        data["valid"] = False
        path.write_text(json.dumps(data))
        self.assertFalse(verify_research_bundle(self.output)["valid"])
        # Recomputing a file checksum cannot hide a result inconsistent with inputs.
        import hashlib
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["result.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        self.assertIn("REPLAY_MISMATCH", [item["code"] for item in verify_research_bundle(self.output)["errors"]])

    def test_existing_bundle_is_never_overwritten(self):
        run_research(self.source, self.output)
        original = (self.output / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            run_research(self.source, self.output)
        self.assertEqual((self.output / "manifest.json").read_bytes(), original)

    def test_manifest_cannot_escape_artifact_directory(self):
        run_research(self.source, self.output)
        path = self.output / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["../private"] = "invalid"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            verify_research_bundle(self.output)

    def test_boolean_manifest_version_and_symlinked_manifest_are_rejected(self):
        run_research(self.source, self.output)
        path = self.output / "manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        manifest["bundle_version"] = True
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            verify_research_bundle(self.output)
        path.unlink()
        target = self.root / "other-manifest.json"
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            verify_research_bundle(self.output)

    def test_hash_valid_malformed_frozen_input_returns_controlled_validation_error(self):
        import hashlib
        run_research(self.source, self.output)
        path = self.output / "input.json"
        path.write_text("[]")
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["input.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "missing required"):
            verify_research_bundle(self.output)

    def test_cli_uses_exit_three_for_blocked_research_and_zero_for_bundle_integrity(self):
        supplied = json.loads(self.source.read_text())
        supplied["reports"] = []
        self.source.write_text(json.dumps(supplied))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["research-synthesize", str(self.source), "--out", str(self.output)]), 3)
            self.assertEqual(main(["research-verify", str(self.output)]), 0)

    def test_conflicting_input_modes_rejected_before_artifact_creation(self):
        supplied = json.loads(self.source.read_text())
        supplied["evidence"] = {}
        self.source.write_text(json.dumps(supplied))
        with self.assertRaises(ValueError):
            run_research(self.source, self.output)
        self.assertFalse(self.output.exists())
