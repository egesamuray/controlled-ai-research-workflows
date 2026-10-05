# Controlled AI-Assisted Research Workflows

> **Work in progress.** Public documentation and a minimal offline reference
> example. This repository does not install or reconfigure coding agents,
> connect to a cluster, or submit research jobs. Operational integrations are
> not included in this public preview.

Coding agents are useful for scientific software, but they make a few old
problems in research computing easier to hit. This repository describes a
verification-first way of working with them. It is based on a private workflow
I use for research code and cluster experiments. It also includes one small
piece you can run: an offline integrity check for a synthetic run bundle.

## The problem

- **Uncontrolled edits.** Several agents or sessions change the same checkout,
  or a change drifts beyond what the task asked for.
- **Weak verification.** An agent's report that something works is accepted in
  place of a check that could have failed.
- **Ambiguous run completion.** A batch job disappears from the queue and is
  assumed to have succeeded.
- **Missing provenance.** A result cannot be traced to the source revision and
  configuration that produced it, or its files changed after the run.

## Approach

1. **Explicit task scope.** Objective, allowed paths, non-goals, invariants,
   verification plan and stop conditions are written down before work starts.
2. **One active writer.** Exactly one agent or person edits a checkout at a time.
3. **Separate review.** A different reviewer inspects the result read-only and
   reports findings with evidence. A failed or missing review is not approval.
4. **Deterministic checks.** Acceptance is decided by commands that can fail,
   run on the final revision, not by anyone's summary.
5. **Source and configuration traceability.** A run is tied to a clean, specific
   commit and a recorded, resolved configuration.
6. **Terminal evidence and artifact integrity.** A run counts as successful only
   with an explicit, well-formed terminal record. Its outputs are checked
   against a manifest of SHA-256 hashes.

[docs/architecture.md](docs/architecture.md) walks through the sequence.

## What is in this repository

| Capability | Status here | Evidence |
|---|---|---|
| Artifact manifest with relative paths, sizes and SHA-256 hashes | Implemented in the offline demo | [`examples/offline_demo.py`](examples/offline_demo.py), [`tests/test_offline_demo.py`](tests/test_offline_demo.py) |
| Rejecting modified, missing, unlisted or symlinked artifacts, and absolute or `..` manifest paths | Implemented in the offline demo | same |
| Missing terminal record reported as `UNKNOWN`, never success; failed, malformed or inconsistent records rejected | Implemented in the offline demo | same |
| Terminal record bound to the manifest by its SHA-256 hash | Implemented in the offline demo | same |
| Refusing to overwrite an existing path or to write anywhere except a new directory directly inside `demo_runs/` | Implemented in the offline demo | same |
| Task, review and handoff records | Templates only; nothing enforces them | [`templates/`](templates/) |
| Single writer, read-only review, deterministic gates | Documented process | [`docs/architecture.md`](docs/architecture.md) |
| Commit-pinned job submission, run-scoped provenance records, hash-verified retrieval from a cluster | Part of a private workflow; not released | [`docs/verification-and-release-scope.md`](docs/verification-and-release-scope.md#private-workflow-and-this-preview) |
| Agent orchestration, scheduler integration, remote Git synchronization | Not included | — |

## Run the offline example

Python 3 standard library only: no third-party packages, network, GPU,
scheduler or API keys. Tested locally with Python 3.14; CI uses the GitHub
runner's preinstalled Python 3. Run from the repository root:

```bash
python3 -B examples/offline_demo.py --help
python3 -B examples/offline_demo.py create --out demo_runs/run-001
python3 -B examples/offline_demo.py verify demo_runs/run-001
```

```text
[OFFLINE DEMO - synthetic data, no real execution] created demo_runs/run-001 (simulate=completed)
[OFFLINE DEMO - synthetic data, no real execution] VERIFIED: demo_runs/run-001
  integrity and terminal record match this bundle's own manifest; this is not proof of authenticity or scientific correctness
```

A bundle holds `config.json`, two small deterministic artifacts under
`artifacts/`, `manifest.json`, and a synthetic `terminal.json` that is written
last.

These cases must not verify; each exits with status 1:

```bash
# No terminal record: UNKNOWN
python3 -B examples/offline_demo.py create --out demo_runs/run-002 --simulate missing-terminal
python3 -B examples/offline_demo.py verify demo_runs/run-002

# Terminal record reports failure: FAILED
python3 -B examples/offline_demo.py create --out demo_runs/run-003 --simulate failed
python3 -B examples/offline_demo.py verify demo_runs/run-003

# Modified artifact: INVALID
echo 999 >> demo_runs/run-001/artifacts/sequence.txt
python3 -B examples/offline_demo.py verify demo_runs/run-001
```

`create` refuses, with exit status 2, any `--out` that already exists or is
not directly inside `demo_runs/`. The script writes only there, and Git ignores
that directory.

Unit tests:

```bash
python3 -B -m unittest discover -s tests -v
```

## Limitations

- **Integrity, not authenticity.** The demo checks files against the bundle's
  own manifest. Anyone who can edit a bundle can also write a new, consistent
  manifest and terminal record. Nothing is signed.
- **A hash match is not correctness.** It shows the bytes have not changed since
  the manifest was written. It does not show that the computation was right or
  ran where the record says.
- **Synthetic only.** There is no real job, scheduler, agent or cluster. The
  terminal record and its timestamps are fixed placeholders.
- **Not a sandbox.** Verification refuses symlinks and paths that leave the
  bundle, but does not defend against files being changed while it runs.
- **Templates are not enforcement.** They structure the records; they do not
  stop anyone from skipping them.

[docs/verification-and-release-scope.md](docs/verification-and-release-scope.md)
lists the tests run on this revision and what remains private or planned.

## Layout

```text
AGENTS.md, CLAUDE.md                    rules for coding agents working on this repository
docs/architecture.md                    workflow stages; what is documented vs. demonstrated
docs/verification-and-release-scope.md  tests run, guarantees and non-guarantees, release boundary
templates/                              task, review and handoff templates
examples/offline_demo.py                offline bundle create/verify example (standard library only)
tests/test_offline_demo.py              unittest suite for the example
.github/workflows/ci.yml                CPU-only CI on a GitHub-hosted runner
```

No license has been chosen yet.
