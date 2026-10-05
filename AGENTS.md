# Instructions for coding agents

These rules apply to this repository only.

- Work inside this repository. Do not read or change other repositories, global
  configuration, credentials or agent settings.
- Keep the example offline and dependency-free: Python standard library only.
  No network calls, subprocesses, schedulers, clusters, model APIs or
  credentials.
- Example code writes only under `demo_runs/`, which Git ignores. Never commit
  generated bundles.
- Keep claims honest. Call something implemented only if code and tests in this
  repository demonstrate it. Templates are templates. Do not describe private
  systems beyond what `docs/verification-and-release-scope.md` already says.
- Do not add private paths, hostnames, account names, job IDs, logs,
  screenshots or unreleased research results.
- One writer per checkout. Reviewers are read-only and report findings with
  evidence.
- Run the tests before and after a change. After changing the example, also run
  the README quickstart.

  ```bash
  python3 -B -m unittest discover -s tests -v
  ```

- Report the commands you ran and their results. Report a skipped or failing
  check as skipped or failing.
