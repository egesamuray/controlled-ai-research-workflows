# Verification and release scope

## What the offline example verifies

For a bundle created by `examples/offline_demo.py`, `verify` checks that:

- `manifest.json` has exactly the expected fields, schema and demo label, and
  between 1 and 64 entries;
- each entry has a safe relative path, a size and a lowercase SHA-256 hex
  digest. No path appears twice, and `config.json` is listed;
- each listed file is a regular file with no symlink in any path component, and
  its size and hash match the manifest;
- the bundle contains no unlisted files and no symlinks;
- `terminal.json`, if present, has exactly the expected fields and is marked
  synthetic. It must name the same run and store the manifest's SHA-256 hash.
  Its state must be known, with a consistent exit code, and its timestamps must
  be timezone-aware and in order.

`create` refuses to write outside `demo_runs/`, including through symlinked
parent directories. It refuses any existing path, including a symlink, and
creates each file exclusively.

## What it does not verify

- Who created the bundle. There are no signatures or keys.
- That a computation was correct, or that the artifacts mean anything
  scientifically.
- That the terminal record reflects a real execution. It is synthetic by
  construction.
- Any source revision, environment or hardware. The demo records none.
- Safety under concurrent modification. There is a window between checking a
  path and reading it.
- Large files. Each file is capped at 1 MiB.

## Tests run on this revision

Run locally before the initial publication on 2026-10-05, on macOS (Darwin
25.6, arm64) with Python 3.14.7:

| Command | Result |
|---|---|
| `python3 -B examples/offline_demo.py --help` | exit 0 |
| `create --out demo_runs/run-001`, then `verify` | `VERIFIED`, exit 0 |
| `create` again with the same `--out` | refused, exit 2 |
| `create --out ../escape` | refused, exit 2 |
| `create --simulate missing-terminal`, then `verify` | `UNKNOWN`, exit 1 |
| `create --simulate failed`, then `verify` | `FAILED`, exit 1 |
| append to `artifacts/sequence.txt`, then `verify` | `INVALID`, exit 1 |
| `python3 -B -m unittest discover -s tests -v` | 24 tests, OK |

The unit tests cover:

- a valid bundle, and byte-identical output from repeated runs;
- same-size tampering, and a manifest re-hashed after tampering (caught by the
  terminal record's binding to the manifest);
- a missing artifact, manifest or terminal record;
- failed, malformed and inconsistent terminal records;
- absolute, traversing and reserved manifest paths, and malformed entries;
- symlinked artifacts, directories, manifest, terminal record and bundle path;
- unlisted files;
- output collisions, escapes and symlinked output locations;
- absence of the repository path, home directory, user name and host name from
  the output;
- CLI exit codes.

The GitHub Actions workflow runs the quickstart and the unit tests on a
GitHub-hosted Ubuntu runner with its preinstalled Python. This document does
not record a CI result. For the outcome on a given commit, see the repository's
Actions tab.

## Integrity, authenticity and scientific correctness

These are three different questions.

- **Integrity:** have the bytes changed since the manifest was written? A
  SHA-256 match answers this, provided the manifest itself can be trusted.
- **Authenticity:** who wrote the manifest and the terminal record, and did the
  run happen as recorded? Answering this takes evidence from outside the
  bundle, such as a signature, an access-controlled record, or a hash obtained
  independently. The demo has none of these. Anyone who can edit a bundle can
  write a new manifest and terminal record that agree with each other.
- **Scientific correctness:** did the computation do what it should? This
  depends on the method, tests derived from the mathematics, validation data
  and review. No file hash speaks to it.

A SHA-256 match therefore does not prove trusted execution or correctness. A
hash identifies content. A buggy program writes its wrong output just as
reproducibly as a correct one. A hash taken after a run says nothing about the
machine, code or inputs that produced the content, unless separate evidence
binds them.

## Why source and configuration records are not a reproducibility guarantee

Recording the commit, dirty state and resolved configuration makes a run
traceable. Repeating it also needs:

- an equivalent software environment and dependency versions;
- the same input data;
- the same seeds and random-number behavior;
- comparable hardware and numerics, including GPU nondeterminism, library
  kernels and floating-point reduction order;
- any external services the run used.

A record covers only what it captured, and an accurate record does not make a
run repeatable bit for bit. Provenance records are a necessary starting point
for diagnosing failures and planning reruns. They do not prove a rerun will
agree.

## Private workflow and this preview

This repository accompanies a description of a private workflow that connects
coding agents to scientific development and cluster execution. The private
workflow is not released. The table below shows what each part of the
description rests on and what this repository contains.

| Part | Basis for the description | Released here |
|---|---|---|
| Single writer, independent read-only review, deterministic verification gates | Private instruction and review-policy files | Templates and documentation only |
| Commit-pinned job submission through one gateway | Private instruction files; the submission code was not reviewed for this write-up | No |
| Run-scoped provenance record of source commit and dirty state | Private gateway code, read for this write-up | No; the demo uses a synthetic config with no source-revision field |
| Terminal-status classification in which missing evidence is never success | Private gateway code, read for this write-up | A simplified offline subset in the demo |
| Hash-verified artifact retrieval with manifest path validation | Private gateway code, read for this write-up | A simplified offline subset in the demo |

The private files were read, not copied. Everything in this repository was
written fresh for it. An instruction or policy file shows intended behavior, not
that the behavior is enforced in every case. This example was written for the
public preview and does not show how the private workflow was used in the past.

Not released: the private gateway and its configuration, agent and plugin
configuration, internal instructions, run logs, job records, and research code,
data and results.

## Roadmap

Possible next steps, in no particular order and without commitment:

- Optional manifest signing in the demo, to show integrity and authenticity as
  separate checks.
- A source-revision field that is filled only when a clean, verifiable commit is
  available, with tests for the dirty and unknown cases.
- An offline example of terminal-status classification against a mocked
  scheduler.
- Sanitized parts of the private tooling, if ownership and licensing allow.
