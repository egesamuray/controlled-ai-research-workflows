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

    def test_refuses_symlinked_parent_escape(self):
        (self.root / "link").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(demo.DemoError):
            demo.create_bundle(self.root / "link" / "x", output_root=self.root)
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
        out = self.tmp / "cli-bundle"  # inside the default demo_runs/ root
        self.assertEqual(self.run_cli("create", "--out", str(out)), 0)
        self.assertEqual(self.run_cli("create", "--out", str(out)), 2)
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

    def test_missing_terminal_is_unknown_not_success(self):
        bundle = self.make(simulate="missing-terminal")
        self.assert_status(bundle, "UNKNOWN", "not success")
        self.assertEqual(self.run_cli("verify", str(bundle)), 1)

    def test_failed_terminal_is_rejected(self):
        bundle = self.make(simulate="failed")
        self.assert_status(bundle, "FAILED")
        self.assertEqual(self.run_cli("verify", str(bundle)), 1)

    def test_malformed_terminal_record(self):
        cases = {
            "not json": lambda p: p.write_text("COMPLETED"),
            "json list": lambda p: p.write_text("[]"),
            "missing field": lambda p: self.edit_json(p, drop=["exit_code"]),
            "extra field": lambda p: self.edit_json(p, unexpected="x"),
            "string exit code": lambda p: self.edit_json(p, exit_code="0"),
            "boolean exit code": lambda p: self.edit_json(p, exit_code=False),
            "out of range exit code": lambda p: self.edit_json(p, exit_code=256),
            "not synthetic": lambda p: self.edit_json(p, synthetic=False),
            "unknown state": lambda p: self.edit_json(p, state="SUCCESS"),
            "bad timestamp": lambda p: self.edit_json(p, ended_at="later"),
            "naive timestamps": lambda p: self.edit_json(
                p, started_at="2000-01-01T00:00:00", ended_at="2000-01-01T00:00:05"),
        }
        for name, corrupt in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                corrupt(bundle / "terminal.json")
                self.assert_status(bundle, "INVALID")

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

    def test_rejects_malformed_manifest_entries(self):
        def entry(**kw):
            return {"path": "artifacts/summary.json", "bytes": 1, "sha256": "a" * 64, **kw}
        cases = {
            "duplicate path": lambda a: a.append(dict(a[0])),
            "missing sha256": lambda a: a.append({"path": "x", "bytes": 1}),
            "extra field": lambda a: a.append(entry(path="y", note="x")),
            "negative size": lambda a: a.append(entry(path="y", bytes=-1)),
            "boolean size": lambda a: a.append(entry(path="y", bytes=True)),
            "uppercase hash": lambda a: a.append(entry(path="y", sha256="A" * 64)),
            "empty list": lambda a: a.clear(),
            "config not listed": lambda a: a.remove(
                next(e for e in a if e["path"] == "config.json")),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                bundle = self.make(name.replace(" ", "-"))
                manifest = json.loads((bundle / "manifest.json").read_text())
                mutate(manifest["artifacts"])
                (bundle / "manifest.json").write_bytes(demo.canonical_json(manifest))
                self.assert_status(bundle, "INVALID")

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
                 "artifact dir": lambda b: link_dir(b, "artifacts")}
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

    def test_rejects_unlisted_file(self):
        bundle = self.make()
        (bundle / "artifacts" / "extra.txt").write_text("not in manifest\n")
        self.assert_status(bundle, "INVALID", "unlisted file")


if __name__ == "__main__":
    unittest.main()
