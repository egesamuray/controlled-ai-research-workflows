# Task: <short title>

<!-- Template. Fill it in before work starts. It records the scope; it does not enforce it. -->

**Writer:** <one agent or person>
**Reviewer:** <a different agent or person, read-only>
**Repository and base revision:** <repository>@<commit> (working tree clean: yes/no)

## Objective

<What should be true when the task is done, in one or two sentences.>

## Allowed paths

- <paths the writer may create or modify>

## Non-goals

- <related things this task must not change>

## Invariants

<Properties that must hold before and after the change: public interfaces, data
formats, numerical conventions such as shapes, units and normalization, and
files that must not change.>

## Verification plan

| Check | Command | Expected result |
|---|---|---|
| | | |

## Stop conditions

Stop and report instead of continuing if:

- a needed change falls outside the allowed paths;
- a check fails for a reason that is not understood;
- <task-specific limits: time, number of attempts, cost>.

## Acceptance criteria

- [ ] Every command in the verification plan passes on the final revision.
- [ ] Review completed, with findings addressed or recorded with a reason.
- [ ] Handoff written (see `handoff.md`).
- [ ] <task-specific criterion>
