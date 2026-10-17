# Corpus and resume

## Workspace files

The coordinator writes `references/wasp/` in the user's research project:

- `manifest.json`, `context.json`, `ontology.json`, `queries.json`: frozen scope and query plan.
- `runs/<run-id>.json`: resumable searches, all PMIDs, selected IDs, record hashes and full-text outcomes.
- `membership.jsonl`: gene/query/concept membership for every discovered PMID, with abstract-selection flags.
- `articles.jsonl`: the single canonical parsed PubMed record per PMID, including its abstract and source-response reference.
- `sources/<run-id>/`: immutable wrapper responses, including original fetch payloads/XML, errors and assessment imports. These preserve retrieval provenance and permit recovery of an earlier record if PubMed later changes it.
- `sources.jsonl`: source paths, timestamps, hashes, requests and license status.
- `jobs/<job-id>/`: immutable job manifest and complete abstract packet.
- `waves/`, `jobs-index.json`: host-executed screening workflow scripts and dispatch inventory.
- `evidence.jsonl`, `assessment_imports.jsonl`: validated assessments and runtime provenance.
- `fulltexts.jsonl`: source references and licenses for retained full texts.
- `overview.json`, `audit.json`: derived coverage and integrity views.

Full-text sources stay with the immutable response snapshots. This version does not promise PDFs, publisher figures or supplementary files. Keep dated syntheses and follow-up questions in the project's existing notes directory; `references/notes/` is the default when none exists.

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
