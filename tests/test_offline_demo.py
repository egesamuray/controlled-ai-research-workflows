"""Deterministic tests for examples/offline_demo.py (OFFLINE DEMO, synthetic data only).

Run from the repository root:

    python3 -B -m unittest discover -s tests -v

Each test works in its own temporary directory under ``demo_runs/`` (ignored by
Git) and removes it afterwards. Nothing touches the network or runs commands.
"""
from __future__ import annotations

import contextlib
import getpass
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "offline_demo", REPO_ROOT / "examples" / "offline_demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

EXPECTED_FILES = {"config.json", "manifest.json", "terminal.json",
                  "artifacts/sequence.txt", "artifacts/summary.json"}


class BundleTestCase(unittest.TestCase):
    def setUp(self):
        base = REPO_ROOT / "demo_runs"
        base.mkdir(exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="unittest-", dir=base))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "root"      # output root used by create_bundle
        self.outside = self.tmp / "outside"  # stands in for "anywhere else"
        self.root.mkdir()
        self.outside.mkdir()

    def make(self, name="bundle", simulate="completed"):
        return demo.create_bundle(self.root / name, simulate=simulate, output_root=self.root)

    def assert_status(self, bundle, expected, fragment=None):
        status, reasons = demo.verify_bundle(bundle)
        self.assertEqual(status, expected, reasons)
        if fragment is not None:
            self.assertTrue(any(fragment in r for r in reasons), reasons)

    @staticmethod
    def edit_json(path, drop=(), **changes):
        data = json.loads(path.read_text())
        for key in drop:
            del data[key]
        data.update(changes)
        path.write_text(json.dumps(data))

    @staticmethod
    def run_cli(*argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return demo.main(list(argv))


class CreateTests(BundleTestCase):
    def test_creates_expected_files(self):
        bundle = self.make()
        files = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
        self.assertEqual(files, EXPECTED_FILES)

    def test_bundles_are_byte_identical(self):
        a, b = self.make("a"), self.make("b")
        for rel in EXPECTED_FILES:
            self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes(), rel)

    def test_refuses_existing_output(self):
        bundle = self.make()
        before = (bundle / "manifest.json").read_bytes()
        with self.assertRaises(demo.DemoError):
            self.make()
        self.assertEqual((bundle / "manifest.json").read_bytes(), before)
        self.assert_status(bundle, "VERIFIED")

    def test_refuses_output_outside_root(self):
        for out in (self.outside / "x", self.root / ".." / "x", self.root, self.root / ".."):
            with self.subTest(out=out), self.assertRaises(demo.DemoError):
                demo.create_bundle(out, output_root=self.root)
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertFalse((self.tmp / "x").exists())

    def test_refuses_nested_output(self):
        bundle = self.make()
        (self.root / "sub").mkdir()
        for out in (bundle / "artifacts" / "new", bundle / "new", self.root / "sub" / "x"):
            with self.subTest(out=out), self.assertRaises(demo.DemoError):
                demo.create_bundle(out, output_root=self.root)
        self.assert_status(bundle, "VERIFIED")

    def test_refuses_symlinked_parent_escape(self):
        (self.root / "link").symlink_to(self.outside, target_is_directory=True)
        (self.root / "loop").symlink_to(self.root / "loop")
        for out in (self.root / "link" / "x", self.root / "loop" / "x"):
            with self.subTest(out=out), self.assertRaises(demo.DemoError):
                demo.create_bundle(out, output_root=self.root)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_refuses_existing_symlink_as_bundle_path(self):
        (self.root / "dangling").symlink_to(self.outside / "target")
        with self.assertRaises(demo.DemoError):
            demo.create_bundle(self.root / "dangling", output_root=self.root)
        self.assertFalse((self.outside / "target").exists())

    def test_refuses_symlinked_output_root(self):
        link_root = self.tmp / "link-root"
        link_root.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(demo.DemoError):
            demo.create_bundle(link_root / "x", output_root=link_root)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_no_machine_information_in_bundle(self):
        bundle = self.make()
        private = [str(REPO_ROOT), str(Path.home()), getpass.getuser(), socket.gethostname()]
        private = [s for s in private if len(s) >= 5]
        for rel in EXPECTED_FILES:
            text = (bundle / rel).read_text()
            for value in private:
                self.assertNotIn(value, text, rel)

    def test_source_has_no_process_or_network_access(self):
        source = (REPO_ROOT / "examples" / "offline_demo.py").read_text()
        for token in ("subprocess", "socket", "urllib", "http", "os.system", "os.popen",
                      "os.exec", "os.environ", "getpass", "import platform", "eval(", "exec("):
            self.assertNotIn(token, source)


class VerifyTests(BundleTestCase):
    def test_valid_bundle_verifies(self):
        bundle = self.make()
        self.assertEqual(demo.verify_bundle(bundle), ("VERIFIED", []))

    def test_cli_exit_codes(self):
        out = REPO_ROOT / "demo_runs" / f"{self.tmp.name}-cli"  # direct child of demo_runs/
        self.addCleanup(shutil.rmtree, out, True)
        self.assertEqual(self.run_cli("create", "--out", str(out)), 0)
        self.assertEqual(self.run_cli("create", "--out", str(out)), 2)
        self.assertEqual(self.run_cli("create", "--out", str(self.tmp / "nested")), 2)
        escape = REPO_ROOT / "demo_runs" / ".." / f"{self.tmp.name}-escape"
        self.addCleanup(lambda: escape.is_dir() and shutil.rmtree(escape))  # only if a bug wrote it
        self.assertEqual(self.run_cli("create", "--out", str(escape)), 2)
        self.assertFalse(escape.exists())
        self.assertEqual(self.run_cli("verify", str(out)), 0)
        (out / "artifacts" / "sequence.txt").write_text("tampered\n")
        self.assertEqual(self.run_cli("verify", str(out)), 1)
        self.assertEqual(self.run_cli("verify", str(self.outside / "nope")), 1)

    def test_tampered_artifact_same_size(self):
        bundle = self.make()
        path = bundle / "artifacts" / "sequence.txt"
        data = bytearray(path.read_bytes())
        data[0] = ord("9") if data[0] != ord("9") else ord("8")
        path.write_bytes(bytes(data))
        self.assert_status(bundle, "INVALID", "size/hash mismatch")

    def test_rehashed_manifest_breaks_terminal_binding(self):
        bundle = self.make()
        (bundle / "artifacts" / "sequence.txt").write_text("1\n")
        manifest = json.loads((bundle / "manifest.json").read_text())
        for entry in manifest["artifacts"]:
            if entry["path"] == "artifacts/sequence.txt":
                entry.update(bytes=2, sha256=demo.sha256_hex(b"1\n"))
        (bundle / "manifest.json").write_bytes(demo.canonical_json(manifest))
        self.assert_status(bundle, "INVALID", "not bound to this manifest")

    def test_missing_artifact(self):
        bundle = self.make()
        (bundle / "artifacts" / "summary.json").unlink()
        self.assert_status(bundle, "INVALID", "missing artifact")

    def test_missing_manifest(self):
        bundle = self.make()
        (bundle / "manifest.json").unlink()
        self.assert_status(bundle, "INVALID", "manifest unreadable")

    def test_deeply_nested_json_is_invalid(self):
        for name in ("manifest.json", "terminal.json"):
            with self.subTest(name):
                bundle = self.make(name)
                depth = 524_000  # deep enough to exhaust the parser, still under 1 MiB
                (bundle / name).write_text("[" * depth + "]" * depth)
                self.assert_status(bundle, "INVALID", "not JSON")

    def test_rejects_duplicate_json_keys(self):
        # Python's json keeps the last duplicate; other parsers may keep the first.
        cases = {
            "terminal": ("terminal.json", '"exit_code": 0,', '"exit_code": 1,\n  "exit_code": 0,'),
            "manifest": ("manifest.json", '"run_id": "offline-demo-001",',
                         '"run_id": "other-run",\n  "run_id": "offline-demo-001",'),
            "manifest-entry": ("manifest.json", '"bytes": 63,', '"bytes": 1,\n      "bytes": 63,'),
        }
        for label, (name, old, new) in cases.items():
            with self.subTest(label):
                bundle = self.make(label)
                text = (bundle / name).read_text()
                self.assertEqual(text.count(old), 1)
                (bundle / name).write_text(text.replace(old, new))
                self.assert_status(bundle, "INVALID", "duplicate JSON key")

    def test_missing_terminal_is_unknown_not_success(self):
        bundle = self.make(simulate="missing-terminal")
        self.assert_status(bundle, "UNKNOWN", "not success")
        self.assertEqual(self.run_cli("verify", str(bundle)), 1)

    def test_failed_terminal_is_rejected(self):
        bundle = self.make(simulate="failed")
        self.assert_status(bundle, "FAILED")
        self.assertEqual(self.run_cli("verify", str(bundle)), 1)

    def test_malformed_terminal_record(self):
        fields = "missing or unexpected fields"
        cases = {
            "not json": (lambda p: p.write_text("COMPLETED"), "not JSON"),
            "json list": (lambda p: p.write_text("[]"), fields),
            "missing field": (lambda p: self.edit_json(p, drop=["exit_code"]), fields),
            "extra field": (lambda p: self.edit_json(p, unexpected="x"), fields),
            "wrong schema": (lambda p: self.edit_json(p, schema="other.v1"), "schema/label"),
            "wrong label": (lambda p: self.edit_json(p, label="real run"), "schema/label"),
            "string exit code": (lambda p: self.edit_json(p, exit_code="0"), "exit_code must"),
            "boolean exit code": (lambda p: self.edit_json(p, exit_code=False), "exit_code must"),
            "exit code 256": (lambda p: self.edit_json(p, exit_code=256), "exit_code must"),
            "not synthetic": (lambda p: self.edit_json(p, synthetic=False), "marked synthetic"),
            "unknown state": (lambda p: self.edit_json(p, state="SUCCESS"), "unknown terminal state"),
            "bad timestamp": (lambda p: self.edit_json(p, ended_at="later"), "invalid timestamps"),
            "naive timestamps": (lambda p: self.edit_json(
                p, started_at="2000-01-01T00:00:00", ended_at="2000-01-01T00:00:05"),
                "timezone-aware"),
        }
        for name, (corrupt, fragment) in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                corrupt(bundle / "terminal.json")
                self.assert_status(bundle, "INVALID", fragment)

    def test_inconsistent_terminal_record(self):
        cases = {
            "completed with nonzero exit": ({"exit_code": 3}, "inconsistent"),
            "failed with zero exit": ({"state": "FAILED"}, "inconsistent"),
            "ends before it starts": ({"ended_at": "1999-12-31T23:59:59+00:00"}, "timestamps"),
            "different run": ({"run_id": "other-run"}, "run_id"),
            "different manifest": ({"manifest_sha256": "0" * 64}, "not bound"),
        }
        for name, (changes, fragment) in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                self.edit_json(bundle / "terminal.json", **changes)
                self.assert_status(bundle, "INVALID", fragment)

    def test_rejects_absolute_and_traversing_manifest_paths(self):
        secret = self.outside / "secret.txt"
        secret.write_text("outside\n")
        bad_paths = ["/etc/passwd", "../outside.txt", "../../outside/secret.txt",
                     "artifacts/../config.json", "./config.json", "artifacts//sequence.txt",
                     "artifacts/", "C:/x", "artifacts\\x", "", "manifest.json", "terminal.json"]
        for bad in bad_paths:
            with self.subTest(path=bad):
                bundle = self.make(f"b{bad_paths.index(bad)}")
                manifest = json.loads((bundle / "manifest.json").read_text())
                manifest["artifacts"].append(
                    {"path": bad, "bytes": 8, "sha256": demo.sha256_hex(b"outside\n")})
                (bundle / "manifest.json").write_bytes(demo.canonical_json(manifest))
                status, reasons = demo.verify_bundle(bundle)
                self.assertEqual(status, "INVALID")
                self.assertTrue(any("artifact path" in r or "reserved" in r for r in reasons),
                                reasons)

    def test_rejects_malformed_manifest(self):
        def entry(**kw):
            return {"path": "artifacts/summary.json", "bytes": 1, "sha256": "a" * 64, **kw}
        exact = "must have exactly"
        cases = {
            "wrong schema": (lambda m: m.update(schema="other.v1"), "unknown manifest schema"),
            "wrong label": (lambda m: m.update(label="real run"), "not labeled"),
            "invalid run_id": (lambda m: m.update(run_id="bad id!"), "invalid run_id"),
            "extra top-level key": (lambda m: m.update(note="x"), exact),
            "duplicate path": (lambda m: m["artifacts"].append(dict(m["artifacts"][0])),
                               "duplicate artifact path"),
            "missing sha256": (lambda m: m["artifacts"].append({"path": "x", "bytes": 1}), exact),
            "extra field": (lambda m: m["artifacts"].append(entry(path="y", note="x")), exact),
            "negative size": (lambda m: m["artifacts"].append(entry(path="y", bytes=-1)),
                              "invalid size"),
            "boolean size": (lambda m: m["artifacts"].append(entry(path="y", bytes=True)),
                             "invalid size"),
            "uppercase hash": (lambda m: m["artifacts"].append(entry(path="y", sha256="A" * 64)),
                               "invalid sha256"),
            "empty list": (lambda m: m["artifacts"].clear(), "artifacts must be a list"),
            "config not listed": (lambda m: m["artifacts"].remove(
                next(e for e in m["artifacts"] if e["path"] == "config.json")),
                "config.json must be listed"),
        }
        for name, (mutate, fragment) in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                manifest = json.loads((bundle / "manifest.json").read_text())
                mutate(manifest)
                (bundle / "manifest.json").write_bytes(demo.canonical_json(manifest))
                self.assert_status(bundle, "INVALID", fragment)

    def test_rejects_symlinks_inside_bundle(self):
        def link_file(bundle, rel):
            target = self.outside / rel.replace("/", "_")
            shutil.copyfile(bundle / rel, target)  # identical bytes, so only the link differs
            (bundle / rel).unlink()
            (bundle / rel).symlink_to(target)

        def link_dir(bundle, rel):
            target = self.outside / f"{bundle.name}-dir"
            shutil.move(str(bundle / rel), str(target))
            (bundle / rel).symlink_to(target, target_is_directory=True)

        cases = {"artifact": lambda b: link_file(b, "artifacts/summary.json"),
                 "terminal": lambda b: link_file(b, "terminal.json"),
                 "manifest": lambda b: link_file(b, "manifest.json"),
                 "artifact dir": lambda b: link_dir(b, "artifacts"),
                 "unlisted dir": lambda b: (b / "extra").symlink_to(
                     self.outside, target_is_directory=True)}
        for name, replace in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                replace(bundle)
                status, reasons = demo.verify_bundle(bundle)
                self.assertEqual(status, "INVALID", reasons)
                self.assertTrue(any("symlink" in r for r in reasons), reasons)

    def test_rejects_symlinked_bundle_path(self):
        bundle = self.make()
        link = self.tmp / "bundle-link"
        link.symlink_to(bundle, target_is_directory=True)
        self.assert_status(link, "INVALID", "not a bundle directory")

    @unittest.skipIf(not hasattr(os, "geteuid") or os.geteuid() == 0,
                     "needs a non-root POSIX user for permission checks")
    def test_reports_unlistable_directory(self):
        bundle = self.make()
        hidden = bundle / "hidden"
        hidden.mkdir()
        (hidden / "unlisted.txt").write_text("x\n")
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)  # runs before the directory is removed
        self.assert_status(bundle, "INVALID", "cannot list directory")

    def test_rejects_unlisted_file(self):
        bundle = self.make()
        (bundle / "artifacts" / "extra.txt").write_text("not in manifest\n")
        self.assert_status(bundle, "INVALID", "unlisted file")


if __name__ == "__main__":
    unittest.main()
