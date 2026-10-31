# Human Decisions and Approved Scope

This file records scope parameters, concept-cap approvals, and manual overrides approved by the human user. Automated subagent screening and Jev triage classifications are logged separately in the [AI decision and screening log](./ai-decisions.md).

## Approved Scope and Search Parameters

- **Target Genes**:
  - **[GENE]** (NCBI Gene ID: [ID]; aliases: [aliases]; identity source: [source])
- **Phenotype**: [target phenotype]
- **Direct Phenotype Terms**: [terms]
- **Reference Organism**: [reference organism]
- **Evidence Species**: [evidence species]
- **High-Priority Abstract Cap**: [200] newest papers per gene-concept query
- **Broad-Scan Abstract Cap**: [30]
- **Full-Text Retrieval Quota**: [10]
- **Frozen Context Record**: [frozen context JSON](./corpus/context.json)

## Approved High-Priority Concepts

- [concept_id] (cap 200)

## Human Approval and Override Ledger

Machine provenance table: [human decisions JSONL](./corpus/human_decisions.jsonl)

| Timestamp | Stage | Decision | Rationale | PMIDs |
| --- | --- | --- | --- | --- |
| [ISO-8601] | scope_approval | Approved initial scope for [GENE] against [phenotype] | [rationale] | none |

## Human Notes

<!-- HUMAN-NOTES-START -->
Add manual review notes or scope clarifications here.
<!-- HUMAN-NOTES-END -->
