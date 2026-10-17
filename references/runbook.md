# Installation and execution runbook

## Load and verify

The skill lives at `~/.agents/skills/wasp-lit/`, with `SKILL.md` at the directory root. Use `/reload`, then `/skill:wasp-lit`. Do not rename the directory or reinstall `pi-subagents` as part of an ordinary run.

For shell commands, resolve the actual installed directory once:

```bash
SKILL="$HOME/.agents/skills/wasp-lit"
python3 "$SKILL/scripts/wasp.py" doctor
python3 -m unittest discover -s "$SKILL/tests" -v
```

Doctor checks paths and whether the installed agent matches the canonical rubric; it does not launch a model or make network requests. Check effective runtime capabilities with `subagent({action:"list",capabilities:true})` and `/subagents-doctor`.

The updated canonical screener includes direction targets and explicit finding fields. To refresh an existing user-agent copy, run locally:

```bash
mkdir -p "$HOME/.pi/agent/agents"
cp "$SKILL/agents/concept-screener.md" "$HOME/.pi/agent/agents/concept-screener.md"
```

Then `/reload`. Do not overwrite unrelated Pi settings or pin the model through this skill. An existing installed DeepSeek Flash configuration can remain unchanged.

## Initialize approved scope

Copy `templates/context.example.json` into the research project, fill every identity and scope field, then remove `_template`. Initialization deliberately rejects an unfilled template. Select concept IDs from the normalized resource. JSON configuration is required for the CLI; research notes use Markdown.

```bash
PROJECT="/absolute/path/to/research-project"
python3 "$SKILL/scripts/wasp.py" init "$PROJECT" --context "$PROJECT/approved-context.json"
python3 "$SKILL/scripts/wasp.py" plan-search "$PROJECT"
```

Read the generated `references/wasp/queries.json` before live collection. Context and ontology are frozen for this workspace. Concept `terms` retains the full interpretation vocabulary; optional `search_terms` selects the retrieval subset. If a concept has a subset, adding a term only to `terms` does not add a query alternative. Follow [keyword roles](keyword-roles.md) when changing the vocabulary, and use a new workspace for either kind of revision.

## Live collection

Read the installed `pubmed-database` skill and its relevant references first. Notify the user to check PubMed terms, NCBI policies and each paper's license, then record the notification:

```bash
python3 "$SKILL/scripts/wasp.py" acknowledge-license "$PROJECT"
```

Check credential presence without revealing values. If either required credential-check field is missing, ask the user to enter it locally with hidden terminal input. Do not run live calls until that setup is complete. The key registration page is https://www.ncbi.nlm.nih.gov/account/settings/; `USER_EMAIL` is the caller's own email address. Never ask for either value in chat.

```bash
RUN="user-chosen-run-id"
uv run --python 3.12 --with python-dotenv --with polite-http \
  python "$SKILL/scripts/wasp.py" collect "$PROJECT" --run-id "$RUN"
python3 "$SKILL/scripts/wasp.py" status "$PROJECT"
```

The coordinator dynamically imports the installed PubMed wrapper, so `uv` does not automatically apply the wrapper script's inline dependency metadata. Declare `python-dotenv` and `polite-http` on the `uv run` command. If their wheels are cached, add `--offline` to avoid dependency resolution over the network; the live retrieval command still makes PubMed requests. Resume by repeating the same run ID. To update sources, use a new run ID with `--refresh`. A PubMed wrapper at a nonstandard location can be passed through `--pubmed-wrapper`.

## Screening

```bash
python3 "$SKILL/scripts/wasp.py" jobs "$PROJECT" --run-id "$RUN"
```

Read `jobs-index.json`. The command creates packets and workflow scripts but launches no subagents. Follow `references/subagents.md` to execute an authorized wave asynchronously through the native `subagent` tool. Use runtime-provided output references and actual child run IDs.

Pass `--model` to declare an explicit model for every screening worker in the generated waves:

```bash
python3 "$SKILL/scripts/wasp.py" jobs "$PROJECT" --run-id "$RUN" --model "provider/model-id"
```

Without `--model` the workers use the configured subagent default. With it, each generated task carries that model, the subagents model-verification guard compares the child's observed model against it, and `jobs-index.json` records the value. Use it when a router or a session default would otherwise override the worker model, and record the resulting model change in the workspace. A failed worker is unresolved work; regenerate pending jobs and run a new authorized wave rather than importing a rejected response.

For each completed child:

```bash
python3 "$SKILL/scripts/wasp.py" evidence-validate "$PROJECT" \
  --job "/actual/job.json" --response "/actual/runtime/output.jsonl"
python3 "$SKILL/scripts/wasp.py" evidence-import "$PROJECT" \
  --job "/actual/job.json" --response "/actual/runtime/output.jsonl" \
  --runtime-run-id "actual-child-run-id"
```

Review scientific judgments before synthesis. Regenerate jobs to continue pending assessments. Do not mistake `needs_review` or a missing abstract for exclusion.

## Full text, follow-up and audit

```bash
uv run --python 3.12 --with python-dotenv --with polite-http \
  python "$SKILL/scripts/wasp.py" fulltext "$PROJECT" --run-id "$RUN"
python3 "$SKILL/scripts/wasp.py" packet "$PROJECT" --gene "USER_SELECTED_GENE" \
  --limit 10 --output "$PROJECT/new-follow-up-packet.json"
python3 "$SKILL/scripts/wasp.py" audit "$PROJECT"
```

Full-text acquisition prioritizes exact target-phenotype and target-drug concepts, then direct phenotype relevance in other concept domains, then indirect relevance. It orders by PubMed `pub_date` within each group and tries NCBI `efetch db=pmc` first, followed by Europe PMC and PMC BioC, under the run-wide quota. License, figure and supplement checks remain explicit. `packet` contains complete abstracts and references to retained full texts. Read section-aware slices of full text when answering, not just an earlier summary.

## Genetic association lane

Read [associations](../references/associations.md) first. The Catalog uses human HGNC symbols, so a non-human reference organism needs `--cross-species-transfer`, which marks every affected row.

The lane speaks the `gwas-mcp` MCP transport directly, so it needs no extra dependency and no `uv`. Resolve the trait, then page associations for every gene in the frozen context:

```bash
python3 "$SKILL/scripts/wasp.py" acknowledge-license "$PROJECT" --source gwas_catalog
python3 "$SKILL/scripts/wasp.py" phenotype-search "$PROJECT" --query "smoking initiation" --limit 5
python3 "$SKILL/scripts/wasp.py" associations "$PROJECT" \
  --run-id "$RUN-gwas" --phenotype "USER_VERIFIED_ID"
python3 "$SKILL/scripts/wasp.py" association-report "$PROJECT" \
  --run-id "$RUN-gwas" --output "$PROJECT/genetic-associations.json"
```

To run from previously saved MCP responses instead of a live call, pass `--capture` for each saved page:

```bash
python3 "$SKILL/scripts/wasp.py" phenotype-search "$PROJECT" --capture "$PROJECT/traits.json"
python3 "$SKILL/scripts/wasp.py" associations "$PROJECT" \
  --run-id "$RUN-gwas" --phenotype "USER_VERIFIED_ID" \
  --capture "$PROJECT/page-0.json" --capture "$PROJECT/page-1.json"
```

Confirm the trait name returned by `phenotype-search` before using its ID. A pair is `incomplete` when the returned pages do not cover the reported range; a gene with no capture is reported under `missing_groups`, never dropped. The Catalog lists a gene by variant position, so a reported gene is locus-level rather than causal, and a zero count is not an absence claim. `--output` must name a path that does not already exist.

## Offline smoke test

Use a temporary workspace outside the skill directory. No credential or license setup is needed for explicit fixtures, and fixture commands make no PubMed calls.

```bash
TEST_PROJECT=$(mktemp -d /tmp/wasp-lit-test.XXXXXX)
python3 "$SKILL/scripts/wasp.py" init "$TEST_PROJECT" \
  --context "$SKILL/tests/fixtures/context.json" --ontology "$SKILL/tests/fixtures/ontology.json"
python3 "$SKILL/scripts/wasp.py" collect "$TEST_PROJECT" --run-id synthetic-smoke \
  --fixture "$SKILL/tests/fixtures/retrieval.json"
python3 "$SKILL/scripts/wasp.py" jobs "$TEST_PROJECT" --run-id synthetic-smoke --wave-size 1
python3 "$SKILL/scripts/wasp.py" audit "$TEST_PROJECT"
```

A screening-worker smoke test uses the generated manifest and packet through the native subagent tool. Keep fixture results labeled synthetic. This test establishes execution and bookkeeping, not scientific validity or live PubMed completeness.

## Live pilot acceptance

Use user-selected genes, phenotype, reference organism and evidence-species scope. Search all ontology concepts by default; use function context to designate the concepts that receive the larger cap. Apply different concept scopes or caps only when explicitly requested. Verify count/ID reconciliation, complete original abstracts, worker completeness and quotations, full-text identity and access outcomes, and reopening sources in a fresh conversation. Report blocked access or incomplete strata without claiming success for those checks.

## Full text from explicit PMID lists

`wasp.py fulltext <workspace> --run-id <run> --pmids <comma-separated PMIDs>` tries the listed PMIDs in
order. By default, the target equals the list length; use `--target N` to stop after N successful retrievals or
reuses. This supports passing the full tier-1 candidate list for one category and taking its first two available
full texts, for example with `--target 2`. Run one command per category. Repeated explicit lists are recorded
separately in the same run, and resolved outcomes are reused across lists. The selection bypasses default
priority, decision and phenotype-relevance filters because the operator supplies the PMIDs. Every PMID must
already be in the run's retrieved records; unknown PMIDs and empty lists are refused.

A run cannot mix priority and explicit selection modes. Explicit lists and targets are recorded in the run state.
Explicit selection still records license and provenance per document and checks that the retrieved document
matches the PMID and carries an identity basis.
