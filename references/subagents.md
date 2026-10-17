# Concept-screening subagents

## Roles and authority

Use the maintained installed `pi-subagents` package, not version-specific links to Pi's example extension. The coordinator is the host parent. Workers are `concept-screener` agents with only `read`, `grep`, `find` and `ls`; no retrieval, edits, shell, synthesis or child spawning. Model policy belongs in user/project settings, not this skill.

Read the installed `pi-subagents` skill and its execution/validation references before launching. Use `subagent({action:"list",capabilities:true})` to check the effective agent and tool boundary. Discovery alone does not prove a successful model launch.

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

`scripts/wasp.py jobs` creates complete JSONL packets and immutable job manifests, one gene and one concept per job. Default packet size is at most 20 abstracts and 40,000 UTF-8 bytes. No lexical prefilter automatically excludes records. An oversized record needs a separate source-aware read.

The command writes ordinary JavaScript workflow scripts with explicit child `output` bindings and `outputMode:"file-only"`. It does not invoke Pi or launch models. Default wave size is 64 jobs; the CLI permits at most 128. Each wave dispatches awaited groups of at most 6 workers by default, stopping further dispatch after a failed group. `--dispatch-size` changes group size separately from packet size and wave fan-out. Inspect configured group, cumulative run fan-out and session limits before launch; lower these sizes when necessary. Context batching is separate from scientific retrieval caps.

For an authorized screening wave, use one top-level workflow call:

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

## Resume and failure

Accepted include/exclude assessments for the same gene, concept, record hash and rubric are reused. `needs_review` remains unresolved and can be reassigned. If a workflow exceeds its budget, regenerate only pending jobs and use a new authorized wave; do not raise limits silently.

Ordinary async completion wakes the parent. Continue independent parent work or yield; do not sleep/poll or call `bg_wait` merely to wait. Retain wave and child IDs for troubleshooting.

On launch, workflow, provider or child-tooling failure, stop the affected lane. Report the exact error, runtime ID, cwd and repository/ref state. Do not silently switch models or fall back to an external CLI/foreground protocol. Keep the corpus and pending jobs intact. Use only an explicit same-protocol retry or ask the user about a change in execution mode.
