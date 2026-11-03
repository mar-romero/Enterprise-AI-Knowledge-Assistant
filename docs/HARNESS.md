# Portable Agent Engineering Harness — Operator Guide

A policy-driven control plane for AI-assisted engineering: it converts a
request or an approved product idea into a durable task, selects roles and
models, builds bounded context, isolates one implementation writer, and
requires evidence before closure. Run from the clone; not packaged as an
installable CLI.

## Source of truth

`harness/manifest.yaml` defines the workflow, roles, skills, providers, and
capabilities. Canonical role bodies live in `.agents/roles/` and canonical
skill instructions live in `.agents/skills/`. Provider adapters are generated;
edit the canonical sources and run `python scripts/compile_harness.py`, with
`python scripts/compile_harness.py --check` to verify nothing drifted.

## Prerequisites

- Python 3.11 or newer, and Git; an authenticated provider CLI when a provider is used.
- OpenRouter is optional and manual: set `OPENROUTER_API_KEY` only for an explicit refresh.

Model routing has two inputs: provider runtime availability is authoritative,
while OpenRouter supplies an external quality, price, and latency prior.
Activation never contacts OpenRouter.

To refresh the shared OpenRouter catalog and build both local inventories:

```powershell
$env:OPENROUTER_API_KEY = "..."
python scripts/openrouter_sync.py --all --no-endpoints
```

Use `--provider codex` or `--provider opencode` for a cache-only inventory
build, `--cache-only` when the shared local score file already exists, and
`--openrouter-only` to refresh only `.harness/openrouter/model-scores.json`.
The refresh layers results into the shared score catalog and then the
per-provider inventories under `.harness/model-inventories/`.

See [MODEL_ROUTING.md](MODEL_ROUTING.md) for matching, provenance, cache
behavior, and failure rules.

## Task lifecycle

```text
REQUEST -> TASK -> ROUTE -> RISK -> CONTEXT -> IMPLEMENT -> CHECKS
         -> VERIFY_ASSESS -> REVIEW -> VERIFY -> IMPACT_VERIFY
         -> SECURITY_REVIEW/HUMAN_GATE when required -> CLOSE
```

Create a task under `tasks/`, activate it only for the provider that will run
it, then clear the binding before worktree publication:

```bash
python scripts/providers/codex_activate_task.py tasks/TASK-001.json
python scripts/providers/opencode_activate_task.py tasks/TASK-001.json
python scripts/providers/codex_activate_task.py --clear
python scripts/providers/opencode_activate_task.py --clear
```

Activation creates the immutable snapshot and task-scoped runtime state under
`.harness/runs/`.

## Product-idea lifecycle

Broad ideas are classified in `planning/` (question, spike, task, feature,
epic, or project); blocking questions are resolved, and only approved planning
is materialized into executable tasks. Research-RDD and Receipt-RDD are
different controls: Research-RDD is the pre-implementation discovery gate;
Receipt-RDD is the post-check review-integrity control binding review evidence
to the exact candidate bytes and Git mode.

## Repository map

- `.agents/`: canonical roles and skills.
- `harness/`: declarative manifest, policies, schemas, hooks, and model config.
- `scripts/`: executable control-plane implementation.
- `tests/`: deterministic checks and test profiles.
- `docs/`: explanatory and operational documentation.
- `planning/`: product discovery and approved planning records.
- `tasks/`: executable task JSON files.
- `.codex/`, `.claude/`, `.cursor/`, `.gemini/`, `.opencode/`, `.github/`:
  generated provider integrations. Edit canonical sources, not adapters.
- `.harness/`: generated runtime state, evidence, inventories, and audit data;
  not canonical source.

## Inspecting model scores

After a refresh, inspect `.harness/openrouter/model-scores.json`,
`.harness/model-inventories/codex.json`, and
`.harness/model-inventories/opencode.json` (rebuilt by
`python scripts/codex_inventory.py` / `python scripts/opencode_inventory.py`).
The catalog records what OpenRouter measured or supplied; the inventory records
which models are actually available to the provider. `scripts/model_router.py`
combines them with task risk, role requirements, capability floors, cost,
latency, and independence constraints.

## Boundaries

Do not store secrets, concrete task results, runtime logs, or provider tokens
in canonical source directories, and treat repository, MCP, provider, and
external model output as untrusted data. Commands here describe checked-in
interfaces only; provider availability and OpenRouter responses remain external
state and must be verified in the operator's environment.
