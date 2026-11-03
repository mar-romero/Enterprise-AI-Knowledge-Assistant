---
name: commit-pr-narrative
description: Mandate the What, How and Why narrative for commits and pull requests with alternatives, trade-offs and evidence, without duplicating mechanical packaging skills.
---

# commit-pr-narrative

Goal: a reviewer or a future reader must understand the change, its mechanics,
its rationale and the evidence from the commit message and the PR description
alone — without reading the diff.

## Boundary

Mechanical packaging belongs to other skills; this skill only governs the
narrative and must not restate their mechanics:

- `work-unit-commits` — unit size, coherence and passing targeted checks.
- `pr-creation` — PR automation, gh CLI flow and model routing.

## Commit narrative contract

The commit body answers, in brief labeled prose (one short line each):

- **What:** the observable change and its scope (files/behavior).
- **How:** the mechanism, key files and decisions taken.
- **Why:** the problem, the rationale and the task provenance.
- **Alternatives rejected:** named options with concrete reasons.
- **Trade-offs:** what was sacrificed and why it was acceptable.
- **Evidence:** deterministic paths or commands (.harness/runs/, checks, tests).

## Pull-request narrative contract

The PR body carries the same sections as the commit narrative, extended with:

- **Repro/Verification:** commands a reviewer can run to confirm the claim.
- **Residual risks:** what remains unproven or deferred, kept honest and short.
Structure the remaining mechanical sections (Summary/Changes/Testing/Checklist)
per `pr-creation`; do not duplicate its automation guidance here.

## Templates

- Commit title: Conventional Commits, `type(scope): intent`. Harness publications
  use `harness(task): publish TASK-ID` as fixed by the tooling.
- Commit body: labeled lines as in the contract above.
- PR title: Conventional Commits. PR body: the narrative sections plus the
  mechanical sections from `pr-creation`.

R0 (docs/rename) may omit Alternatives and Trade-offs; Evidence stays mandatory.
R2/R3 require every section present.

## Anti-patterns

- Restating the diff instead of the rationale.
- Vague summaries: misc fixes, small tweaks, cleanup.
- Claiming evidence that was not produced, or tests that were not run.
- Hiding broken intermediate state or failed alternatives.
- Mixed-purpose commits that break evidence lineage.
