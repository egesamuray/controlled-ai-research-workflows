#!/usr/bin/env python3
"""OFFLINE DEMO: create and verify a synthetic run bundle.

All output is synthetic. The script does not run jobs, contact a cluster or
scheduler, call a model, execute commands, or record machine information.

``verify`` exits 0 only if the manifest is well formed, every listed artifact
matches its size and SHA-256 hash, no unlisted files or symlinks are present,
and a well-formed COMPLETED terminal record is bound to the manifest. A missing
terminal record is UNKNOWN, never success. This is an integrity check against
the bundle's own manifest, not proof of authorship or scientific correctness,
and not a defense against files being modified while they are verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path

DEMO_LABEL = "OFFLINE DEMO - synthetic data, no real execution"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "demo_runs"
MANIFEST, TERMINAL, CONFIG = "manifest.json", "terminal.json", "config.json"
MANIFEST_SCHEMA = "offline-demo.manifest.v1"
TERMINAL_SCHEMA = "offline-demo.terminal.v1"
MANIFEST_KEYS = {"schema", "label", "run_id", "artifacts"}
ENTRY_KEYS = {"path", "bytes", "sha256"}
TERMINAL_KEYS = {"schema", "synthetic", "label", "run_id", "state", "exit_code",
                 "started_at", "ended_at", "manifest_sha256"}
SIMULATIONS = ("completed", "failed", "missing-terminal")
RUN_ID = "offline-demo-001"
# Fixed placeholders so bundles are byte-for-byte reproducible; not real times.
SYNTHETIC_START, SYNTHETIC_END = "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:05+00:00"
MAX_BYTES = 1 << 20  # every demo file is tiny; refuse anything larger
MAX_ENTRIES = 64
PATH_RE = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class DemoError(Exception):
    """An operation was refused, e.g. an unsafe or existing output location."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def synthetic_artifacts(seed: int, length: int) -> dict[str, bytes]:
    """Integer-only pseudo-random data (an LCG), so hashes are platform independent."""
    state, values = seed, []
    for _ in range(length):
        state = (1103515245 * state + 12345) % 2**31
        values.append(state % 1000)
    summary = {"count": length, "sum": sum(values), "min": min(values), "max": max(values)}
    return {
        "artifacts/sequence.txt": "".join(f"{v}\n" for v in values).encode("ascii"),
        "artifacts/summary.json": canonical_json(summary),
    }


def _new_bundle_dir(out: Path, output_root: Path) -> Path:
    """Create a fresh, empty directory strictly inside ``output_root``."""
    if output_root.is_symlink():
        raise DemoError(f"output root must not be a symlink: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    root = output_root.resolve(strict=True)
    if out.name in ("", ".", ".."):
        raise DemoError(f"invalid bundle directory name: {out}")
    try:
        parent = out.parent.resolve(strict=True)  # follows symlinked parents
    except OSError:
        raise DemoError(f"parent directory does not exist: {out.parent}") from None
    if parent != root and root not in parent.parents:
        raise DemoError(f"output must be inside {output_root}: {out}")
    target = parent / out.name
    try:
        target.mkdir()  # fails if anything, including a symlink, already exists
    except FileExistsError:
        raise DemoError(f"refusing to overwrite existing path: {out}") from None
    return target


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(exist_ok=True)
    with open(path, "xb") as handle:  # exclusive create: never overwrite
        handle.write(data)


def create_bundle(out: Path | str, *, simulate: str = "completed",
                  output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    """Write a new synthetic bundle; the terminal record is written last."""
    if simulate not in SIMULATIONS:
        raise DemoError(f"unknown simulation {simulate!r}")
    bundle = _new_bundle_dir(Path(out), Path(output_root))
    config = {"label": DEMO_LABEL, "run_id": RUN_ID, "seed": 7, "length": 16}
    files = {CONFIG: canonical_json(config),
             **synthetic_artifacts(config["seed"], config["length"])}
    for rel, data in files.items():
        _write_new(bundle / rel, data)
    manifest_bytes = canonical_json({
        "schema": MANIFEST_SCHEMA, "label": DEMO_LABEL, "run_id": RUN_ID,
        "artifacts": [{"path": rel, "bytes": len(data), "sha256": sha256_hex(data)}
                      for rel, data in sorted(files.items())],
    })
    _write_new(bundle / MANIFEST, manifest_bytes)
    if simulate != "missing-terminal":
        failed = simulate == "failed"
        _write_new(bundle / TERMINAL, canonical_json({
            "schema": TERMINAL_SCHEMA, "synthetic": True, "label": DEMO_LABEL,
            "run_id": RUN_ID, "state": "FAILED" if failed else "COMPLETED",
            "exit_code": 1 if failed else 0, "started_at": SYNTHETIC_START,
            "ended_at": SYNTHETIC_END, "manifest_sha256": sha256_hex(manifest_bytes),
        }))
    return bundle


def _read_regular(bundle: Path, rel: str) -> bytes:
    """Read ``bundle/rel``, refusing symlinks at every path component."""
    current, mode = bundle, 0
    for part in rel.split("/"):
        current = current / part
        mode = os.lstat(current).st_mode  # FileNotFoundError if absent
        if stat.S_ISLNK(mode):
            raise ValueError(f"symlink not allowed: {rel}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"not a regular file: {rel}")
    fd = os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"file exceeds {MAX_BYTES} bytes: {rel}")
    return data


def _path_problem(rel: object) -> str | None:
    if not isinstance(rel, str) or not PATH_RE.fullmatch(rel):
        return f"invalid or absolute artifact path: {rel!r}"
    if any(part in (".", "..") for part in rel.split("/")):
        return f"path traversal or dot segment in artifact path: {rel!r}"
    if rel in (MANIFEST, TERMINAL):
        return f"reserved file listed as artifact: {rel!r}"
    return None


def _manifest_problems(manifest: object) -> list[str]:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        return [f"manifest must have exactly the fields {sorted(MANIFEST_KEYS)}"]
    problems = []
    if manifest["schema"] != MANIFEST_SCHEMA:
        problems.append("unknown manifest schema")
    if manifest["label"] != DEMO_LABEL:
        problems.append("manifest is not labeled as an offline demo")
    if not isinstance(manifest["run_id"], str) or not RUN_ID_RE.fullmatch(manifest["run_id"]):
        problems.append("invalid run_id")
    entries = manifest["artifacts"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        return problems + [f"artifacts must be a list of 1..{MAX_ENTRIES} entries"]
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            problems.append(f"artifact entry {i} must have exactly {sorted(ENTRY_KEYS)}")
            continue
        issue = _path_problem(entry["path"])
        if issue or entry["path"] in seen:
            problems.append(issue or f"duplicate artifact path: {entry['path']!r}")
            continue
        seen.add(entry["path"])
        if type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= MAX_BYTES:
            problems.append(f"invalid size for {entry['path']!r}")
        if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
            problems.append(f"invalid sha256 for {entry['path']!r}")
    if CONFIG not in seen:
        problems.append(f"{CONFIG} must be listed in the manifest")
    return problems


def _terminal_check(bundle: Path, run_id: str,
                    manifest_bytes: bytes) -> tuple[str | None, list[str]]:
    """Return (state, problems); state is None when absent or invalid."""
    try:
        record = json.loads(_read_regular(bundle, TERMINAL))
    except FileNotFoundError:
        return None, []
    except (OSError, ValueError) as exc:  # includes invalid JSON / encoding
        return None, [f"terminal record unreadable or not JSON: {exc}"]
    if not isinstance(record, dict) or set(record) != TERMINAL_KEYS:
        return None, ["terminal record has missing or unexpected fields"]
    problems = []
    if record["schema"] != TERMINAL_SCHEMA or record["label"] != DEMO_LABEL:
        problems.append("terminal record schema/label mismatch")
    if record["synthetic"] is not True:
        problems.append("terminal record must be explicitly marked synthetic")
    if record["run_id"] != run_id:
        problems.append("terminal run_id does not match manifest")
    if record["manifest_sha256"] != sha256_hex(manifest_bytes):
        problems.append("terminal record is not bound to this manifest")
    state, code = record["state"], record["exit_code"]
    if state not in ("COMPLETED", "FAILED"):
        problems.append(f"unknown terminal state: {state!r}")
    if type(code) is not int or not 0 <= code <= 255:
        problems.append("exit_code must be an integer in [0, 255]")
    elif (state == "COMPLETED") != (code == 0):
        problems.append(f"inconsistent terminal record: state={state!r}, exit_code={code}")
    try:
        start, end = (datetime.fromisoformat(record[k]) for k in ("started_at", "ended_at"))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            problems.append("timestamps must be timezone-aware with ended_at >= started_at")
    except (TypeError, ValueError):
        problems.append("invalid timestamps")
    return (None if problems else state), problems


def _unexpected_entries(bundle: Path, expected: set[str]) -> list[str]:
    problems = []
    for dirpath, dirnames, filenames in os.walk(bundle):  # does not follow symlinks
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            rel = path.relative_to(bundle).as_posix()
            if path.is_symlink():
                problems.append(f"symlink not allowed: {rel}")
            elif name in filenames and rel not in expected:
                problems.append(f"unlisted file: {rel}")
    return problems


def verify_bundle(bundle: Path | str) -> tuple[str, list[str]]:
    """Return (status, reasons); status is VERIFIED, FAILED, UNKNOWN or INVALID."""
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        return "INVALID", [f"not a bundle directory: {bundle}"]
    try:
        manifest_bytes = _read_regular(bundle, MANIFEST)
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError) as exc:
        return "INVALID", [f"manifest unreadable or not JSON: {exc}"]
    problems = _manifest_problems(manifest)
    if problems:
        return "INVALID", problems
    for entry in manifest["artifacts"]:
        try:
            data = _read_regular(bundle, entry["path"])
        except FileNotFoundError:
            problems.append(f"missing artifact: {entry['path']}")
            continue
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read artifact {entry['path']}: {exc}")
            continue
        if len(data) != entry["bytes"] or sha256_hex(data) != entry["sha256"]:
            problems.append(f"size/hash mismatch: {entry['path']}")
    expected = {entry["path"] for entry in manifest["artifacts"]} | {MANIFEST, TERMINAL}
    problems += _unexpected_entries(bundle, expected)
    state, terminal_problems = _terminal_check(bundle, manifest["run_id"], manifest_bytes)
    problems = list(dict.fromkeys(problems + terminal_problems))  # de-duplicate, keep order
    if problems:
        return "INVALID", problems
    if state is None:
        return "UNKNOWN", ["terminal record missing: missing terminal evidence is not success"]
    if state == "FAILED":
        return "FAILED", ["terminal record reports FAILED with a nonzero exit code"]
    return "VERIFIED", []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{DEMO_LABEL}. Create or verify a synthetic run bundle.",
        epilog="Exit codes: 0 created/VERIFIED, 1 not verified, 2 refused or usage error.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="write a new synthetic bundle under demo_runs/")
    create.add_argument("--out", required=True, type=Path,
                        help="new bundle directory inside demo_runs/ (must not exist)")
    create.add_argument("--simulate", choices=SIMULATIONS, default="completed",
                        help="synthetic terminal outcome to record (default: completed)")
    verify = sub.add_parser("verify", help="verify a bundle; exits 0 only if VERIFIED")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)

    if args.command == "create":
        try:
            create_bundle(args.out, simulate=args.simulate)
        except (DemoError, OSError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"[{DEMO_LABEL}] created {args.out} (simulate={args.simulate})")
        return 0
    status, reasons = verify_bundle(args.bundle)
    print(f"[{DEMO_LABEL}] {status}: {args.bundle}")
    for reason in reasons:
        print(f"  - {reason}")
    if status == "VERIFIED":
        print("  integrity and terminal record match this bundle's own manifest; "
              "this is not proof of authenticity or scientific correctness")
    return 0 if status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
