# AI Coordinator and Subagent Screening Decisions

This file records decisions made by the AI coordinator, Jev pre-screening classifier, and read-only concept-screening subagents. Scope approvals and overrides made by the human user are logged separately in the [human decision log](./human-decisions.md).

## AI Concept-Domain Prioritization Rationale

<!-- AI-RATIONALE-START -->
### [Gene symbol] ([reference organism])

| Concept ID | Function/phenotype rationale | Search vocabulary status |
| --- | --- | --- |
| [ontology concept ID] | [brief rationale tied to source-backed function and phenotype] | [frozen terms or approved supplemental query] |
<!-- AI-RATIONALE-END -->

<!-- AI-LEDGER-START -->
## Planned Query Distribution

- **Direct Gene-Phenotype Queries**: [count]
- **High-Priority Concept Queries**: [count] (cap 200)
- **Broad-Scan Concept Queries**: [count] (cap 30)
- **Machine Query Plan**: [planned queries JSON](./corpus/queries.json)

## Jev Triage Classifications

[Auto-generated summary of Jev pre-screening classifications when triage is run]

## Stratum Retrieval and Screening Coverage

| Run ID | Gene | Concept | Total Hits | Selected | Cap Reached | Included | Needs Review | Excluded | Unassessed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Subagent Abstract Screening Ledger

Machine evidence table: [assessed evidence JSONL](./corpus/evidence.jsonl)

### Included Records (0)

| PMID | Gene | Concept | Species | Design | Direction | Target | Finding | Verbatim Quotation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

### Records Flagged for Review (0)

| PMID | Gene | Concept | Gene Identity | Concept Support | Finding | Reason |
| --- | --- | --- | --- | --- | --- | --- |

### Excluded Records (0)

| PMID | Gene | Concept | Gene Identity | Concept Support | Exclusion Reason |
| --- | --- | --- | --- | --- | --- |
<!-- AI-LEDGER-END -->
