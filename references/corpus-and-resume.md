# Corpus and resume

## Workspace files

Name each workspace `wasp-lit-<gene>-<phenotype>/` (or `wasp-lit-<genes>-<phenotype>/` for multi-gene evaluations). Human-readable deliverables sit at the top level as portable Markdown files:

- `README.md`: workspace overview, corpus counts, and relative links to the top-level Markdown documents.
- `synthesis.md`: narrative candidate-gene plausibility synthesis.
- `human-decisions.md`: user-approved scope parameters, concept-cap approvals, and manual overrides (updated via `wasp.py init` and `wasp.py human-decision`).
- `ai-decisions.md`: AI coordinator concept-prioritization rationale (`<!-- AI-RATIONALE-START -->` ... `<!-- AI-RATIONALE-END -->`), Jev triage summary, and auto-generated subagent abstract screening tables (`include`, `needs_review`, `exclude`).
- `gene-function.md`: baseline gene and protein biology summary for a single gene (or `gene-function/<GENE>.md` when evaluating multiple genes).
- `gwas-associations.md`: human-readable summary of captured GWAS Catalog gene-trait pairs and variant rows.

The coordinator writes machine JSON/JSONL state under `corpus/` (existing legacy workspaces with `references/wasp/manifest.json` continue to resolve `references/wasp/` automatically):

- `manifest.json`, `context.json`, `ontology.json`, `queries.json`: frozen scope and query plan.
- `human_decisions.jsonl`: timestamped ledger of human approvals and manual screening overrides.
- `gene-function/`: raw JSON extracts from NCBI Gene, WikiGenes, and optional protein/expression resources.
- `runs/<run-id>.json`: resumable searches, all PMIDs, selected IDs, record hashes and full-text outcomes.
- `membership.jsonl`: gene/query/concept membership for every discovered PMID, with abstract-selection flags.
- `articles.jsonl`: the single canonical parsed PubMed record per PMID, including its abstract and source-response reference.
- `sources/<run-id>/`: immutable wrapper responses, including original fetch payloads/XML, errors and assessment imports. These preserve retrieval provenance and permit recovery of an earlier record if PubMed later changes it.
- `sources.jsonl`: source paths, timestamps, hashes, requests and license status.
- `jobs/<job-id>/`: immutable job manifest and complete abstract packet.
- `waves/`, `jobs-index.json`: host-executed screening workflow scripts, JSON wave plans, and dispatch inventory.
- `evidence.jsonl`, `assessment_imports.jsonl`, `triage.jsonl`: validated subagent assessments, runtime provenance, and optional Jev pre-screening classifications.
- `fulltexts.jsonl`: source references and licenses for retained full texts.
- `overview.json`, `audit.json`: derived coverage and integrity views.

Full-text sources stay with the immutable response snapshots. This version does not promise PDFs, publisher figures or supplementary files. Keep dated syntheses and follow-up questions in top-level Markdown files or a `notes/` subdirectory.

## Integrity and update rules

One coordinator holds a nonblocking workspace lock. Index writes use fsync and atomic replacement. Source response files are never overwritten; `articles.jsonl` holds one current parsed record per PMID rather than a second copy under a per-record versions directory. Cross-file updates have checkpoints rather than a single database transaction. Resume can repair membership and unfinished fetches from the run ledger. Repeated imports of identical output are idempotent, including recovery between evidence and import-ledger writes.

Reuse checked local records on ordinary retrieval runs. `--refresh` with a new run ID fetches new source responses and updates the canonical parsed record if PubMed changed it; the prior raw response remains in `sources/`. Evidence stores the record hash it was screened against. When reopening old evidence, resolve that hash against the saved response rather than silently substituting a changed current abstract.

Excluded records stay in the corpus for audit and must not enter a synthesis as supporting evidence. The full PMID list includes unselected records, but canonical article rows exist only after record retrieval. Missing abstracts remain known missing, not excluded.

## Reopen in a fresh conversation

1. Read project context and `overview.json`; inspect incomplete searches and unassessed strata.
2. Generate a bounded packet by verified PMIDs, gene or concept. It contains full abstracts, screening records and the saved response that supports the record hash used by an assessment. Its `concepts` list carries the full interpretation vocabulary and any search subsets from the frozen query plan, filtered by gene and concept when supplied.
3. Read the packet, relevant full-text sections, and the canonical article record and its original source response for each empirical claim.
4. Save the question and dated answer with evidence IDs, record hashes and source-response references.

`packet --limit` bounds the number of records, not the length of each abstract. The script never truncates sources. If a packet exceeds a tool's read limit, read in supported slices or generate a smaller packet. Worker JSONL packets have a 40,000-byte default limit and stop for an individually oversized record rather than silently truncating it.

The corpus supports future conversations through files. It does not save the whole chat transcript or provide automatic model memory. Do not upload retained papers, corpus text or worker transcripts without permission and suitable rights.
