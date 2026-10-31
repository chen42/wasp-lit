# Concept-screening subagents

## Roles and authority

The coordinator is the host parent. Workers are `concept-screener` agents with only read-only file inspection tools (`read`, `grep`, `find` and `ls` in Pi, or the host harness's equivalent read-only toolset); no retrieval, edits, shell, synthesis or child spawning. Model policy belongs in user/project settings, not this skill.

In Pi, use the maintained installed `pi-subagents` package, not version-specific links to Pi's example extension; read the installed `pi-subagents` skill and its execution/validation references before launching, and use `subagent({action:"list",capabilities:true})` to check the effective agent and tool boundary. On other harnesses (such as Antigravity, Claude Code, Codex, or OpenCode), define or invoke a read-only subagent using the canonical rubric in `agents/concept-screener.md` and dispatch tasks from `jobs-index.json` or the generated `.json` wave plans. Discovery alone does not prove a successful model launch.

## Model pinning and verification

For scientifically consequential abstract reading or synthesis, use the model tier approved for the task rather than inheriting an accidental default. First confirm the exact `provider/model-id` in `subagent({action:"models"})` or `/subagents-models`, then check authentication with `pi auth check --model provider/model-id --json`. A model appearing in the registry does not prove that its provider is authenticated. Do not ask the user to paste credentials into chat.

Use project-local `.pi/settings.json` to set the parent default and the screener override; use `modelScope.enforce` only when every child agent in the project should be restricted to that model. For a single run, set the exact `model` on each workflow task. Verify that the runtime used the requested model before accepting results. If a router changes the model, stop the wave; do not import its output. Keep router changes local to the research workspace.

```json
{
  "defaultProvider": "provider",
  "defaultModel": "model-id",
  "defaultThinkingLevel": "high",
  "subagents": {
    "agentOverrides": {
      "concept-screener": { "model": "provider/model-id", "thinking": "high" }
    }
  }
}
```

A model router can override the declared worker model at run time. When that happens the subagents model-verification guard rejects the child with `model_verification_failed` and withholds its output. Do not declare a `modelResponseAliases` mapping to paper over the mismatch. Either disable the router for the run, or declare the model the workers actually run on and record the change:

```bash
python3 "$SKILL/scripts/wasp.py" jobs "$PROJECT" --run-id "$RUN" --model "provider/model-id"
```

The guard compares provider and model ID with the thinking suffix stripped, so `provider/model-id` is sufficient. Every child in the wave then declares that model, and `jobs-index.json` records it.

To constrain all child agents, add `"modelScope": { "enforce": true, "allow": ["provider/model-id"] }` under `subagents`. For one session, Pi accepts `pi --model provider/model-id:high`; interactive `/model` and `/thinking` changes are recorded in that session. Do not change global settings for a project-specific model choice.

## Progress messages and logs

Before long screening or retrieval work, send a short user-visible status message naming the phase. During multi-wave work, report progress at phase or wave boundaries rather than spamming per abstract. Generated screening waves and retrieval progress logs use US Central Time (`America/Chicago`) with ISO-8601 offsets. Full-text outcomes preserve `attempted_at` in UTC and include `attempted_at_local` plus the timezone for each candidate. Keep credentials out of status messages and logs.

Keep `agents/concept-screener.md` canonical. The runbook gives a user-agent update command. Doctor detects a stale installed copy. Generated task prompts also explicitly point workers to the canonical rubric and job manifest.

## Jobs and waves

`scripts/wasp.py jobs` creates complete JSONL packets and immutable job manifests, one gene and one concept per job, for any record not already settled by Jev triage (`wasp.py triage`) or prior subagent assessments. Default packet size is at most 20 abstracts and 40,000 UTF-8 bytes. When `wasp.py triage` has been run under the default `raw` policy, pairs with `include` or `exclude` decisions are settled and skipped by `jobs`, so packets are generated only for remaining `needs_review` or unscreened pairs (returning `job_count: 0` when all pairs are settled). If `--policy never-hard-exclude` was explicitly used during triage, `jobs` retains all records and orders triage-included records into earlier packets. An oversized record needs a separate source-aware read.

The command writes both Pi JavaScript workflow scripts (`.js`, with explicit child `output` bindings and `outputMode:"file-only"`) and portable JSON wave plans (`.json`, listed under `wave_json_paths` in `jobs-index.json`). It does not invoke Pi or launch models. Default wave size is 64 jobs; the CLI permits at most 128. Each wave dispatches awaited groups of at most 6 workers by default, stopping further dispatch after a failed group. `--dispatch-size` changes group size separately from packet size and wave fan-out. Inspect configured group, cumulative run fan-out and session limits before launch; lower these sizes when necessary. Context batching is separate from scientific retrieval caps.

### Execution in Pi

For an authorized screening wave in Pi, use one top-level workflow call:

```javascript
subagent({
  workflow: "/absolute/path/from/jobs-index/to/wave.js",
  cwd: "/absolute/research/workspace",
  async: true,
  context: "fresh",
  globalConcurrencyLimit: 6
})
```

The workflow awaits each `runs.all` group, leaves child `async` unset so its results are awaited, and returns actual output references, path mappings and runtime IDs. Use fresh contexts. No host commands run inside the raw workflow sandbox. Bound concurrency to the user's configured capacity; 6 is an example, not an inferred installed setting.

Consume completed wave results before importing or synthesizing. Read the actual returned artifact path, not a guessed path from the task text. Validate each response with its job manifest, then import using the actual child runtime run ID. Runtime output persistence does not give a read-only worker corpus-write permission.

### Execution on other harnesses

On harnesses without `pi-subagents` (such as Antigravity, Claude Code, Codex, or OpenCode):

1. Read `corpus/jobs-index.json` or the portable wave file in `wave_json_paths`. Each entry in `jobs` provides `job_id`, `path` (the canonical `job.json`), `packet_path`, `expected_output_path`, `rubric_path`, and the exact `task` prompt.
2. Dispatch fresh-context, read-only subagents in bounded groups (up to `dispatch_size`, 6 by default) using the host harness's native subagent tool and the system prompt in `agents/concept-screener.md`.
3. When a subagent completes and returns its JSONL assessment lines, persist, validate, and import the output with `evidence-record`:

```bash
python3 "$SKILL/scripts/wasp.py" evidence-record "$PROJECT" \
  --job "/actual/job.json" --response "/path/to/worker-output.jsonl" \
  --runtime-run-id "actual-child-run-id"
```

Or pipe the worker's raw JSONL text on standard input with `--stdin`.

## Jev triage as primary abstract screening

`scripts/jev_classifier.py` and `wasp.py triage` provide a pure-Python structured classification step for `typesafe/jev-latest` (or saved classification captures) that does not depend on Pi's `codemode` `models.classify` binding. Under the default `raw` policy, Jev settles `include` and `exclude` decisions directly in `corpus/triage.jsonl`, `overview.json`, and `ai-decisions.md`, and `wasp.py fulltext` selects full-text candidates directly from Jev-included records. Do not run `concept-screener` LLM subagent waves over pairs already settled by Jev; use `concept-screener` only if `wasp.py jobs` reports pending `needs_review` or unscreened pairs (or if `--policy never-hard-exclude` was explicitly requested).

## Resume and failure

Accepted include/exclude assessments for the same gene, concept, record hash and rubric are reused. `needs_review` remains unresolved and can be reassigned. If a workflow exceeds its budget, regenerate only pending jobs and use a new authorized wave; do not raise limits silently.

Ordinary async completion wakes the parent. Continue independent parent work or yield; do not sleep/poll or call `bg_wait` merely to wait. Retain wave and child IDs for troubleshooting.

On launch, workflow, provider or child-tooling failure within the active harness protocol, stop the affected lane. Report the exact error, runtime ID, cwd and repository/ref state. Do not silently switch models or bypass validation checks. Keep the corpus and pending jobs intact. Use only an explicit same-protocol retry or ask the user about a change in execution mode.
