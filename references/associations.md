# GWAS Catalog variant-trait associations

This lane records curated variant-trait associations from the GWAS Catalog, reached through the configured `gwas-mcp` Model Context Protocol server. It is separate from PubMed abstract screening. It does not replace it and does not depend on it. Run it for every eligible human gene and target phenotype, regardless of which PubMed concept tracks were selected. If trait resolution or the capture prevents the query, record the lane as blocked and state why.

## What this lane answers

- Which curated variant-trait associations does the Catalog record for a selected gene and trait?
- Which variants, effect alleles, effect sizes, studies, and PMIDs support them?
- How large and which ancestry does the supporting study report?

## The three MCP tools

| Tool | Use |
| --- | --- |
| `gwascatalog_get_traits` | Resolve a trait name to an ontology ID, or confirm an ID |
| `gwascatalog_get_associations` | Variant-trait associations for a gene, trait, accession, or rsID |
| `gwascatalog_get_studies` | Study sample size, ancestry, genotyping platform, summary-statistics availability |

Traits are referenced by ontology ID rather than free text, for example `EFO_0005670` for smoking initiation. Confirm the returned trait name before passing the ID to `associations`.

## Capture and provenance

The MCP tools are also callable directly from a model turn and are useful for interactive questions. The lane's reproducible path is the coordinator script, which speaks the same MCP transport itself:

```bash
python3 "$SKILL/scripts/wasp.py" phenotype-search "$PROJECT" --efo-id EFO_0005670
python3 "$SKILL/scripts/wasp.py" associations "$PROJECT" --run-id gwas-smk --phenotype EFO_0005670
```

Each response is saved verbatim as an immutable source with its request, timestamp and checksum before any row is trusted. `audit` re-reads every capture and compares each recorded association against it, so a tampered effect size or count is detectable.

`--endpoint` overrides the `mcp.json` URL, and `WASP_GWAS_MCP_URL` overrides both. Resolution order is explicit flag, environment variable, project `.pi/mcp.json`, then `~/.pi/agent/mcp.json`.

Offline callers can supply previously saved responses instead of a live call:

```bash
python3 "$SKILL/scripts/wasp.py" phenotype-search "$PROJECT" --capture saved-traits.json
python3 "$SKILL/scripts/wasp.py" associations "$PROJECT" --run-id gwas-smk \
  --phenotype EFO_0005670 --capture saved-page-0.json --capture saved-page-1.json
```

A saved response is a full MCP tool result, a bare envelope, or the parsed envelope text. Supplying saved captures makes no network call and is how the offline tests exercise the lane.

## Observed behavior of the server

Verified live on 2026-10-08 against `https://www.ebi.ac.uk/gwas/mcp`:

- **The page size maximum is 50.** A larger `size` is rejected with a validation error. The client clamps the request instead of failing.
- **Tool errors arrive inside the result.** A validation failure returns `isError` with the message in the text content, not a JSON-RPC error. The client raises it immediately rather than retrying a deterministic failure.
- **Pagination is explicit.** Every envelope reports `page`, `total_pages`, `total_results`, `truncated` and `has_next_page`, so a complete capture can be verified rather than assumed.
- **An empty result is a real answer.** A gene with no curated association returns zero rows with `total_pages` 0 and one empty page. This is recorded as a complete group with zero associations.

## Group completeness

Completeness is decided per gene-by-trait group, not per request. A group is complete only when the returned pages are exactly the reported range, no page is truncated, the last page reports no next page, the row count equals the reported total, and no `association_id` repeats. Any other state is recorded as `incomplete` with the specific reasons. A missing group for a gene in the frozen context is recorded as `missing_groups`, never dropped.

The page cap is a safety bound. Hitting it leaves the group incomplete rather than silently truncating.

## Evidence fields retained

Each association row keeps the verbatim Catalog fields: `association_id`, `accession_id`, `pubmed_id`, `first_author`, `p_value`, `beta`, `or_value`, `range`, `risk_frequency`, `reported_trait`, `efo_traits`, `mapped_genes`, `locations`, and `snp_effect_allele`. The pair table adds the per-group association count, the strongest p-value, the distinct PMIDs, accessions, effect alleles, and the capture paths behind them.

Unlike a gene-level association score, most of these fields map to specific variants and studies, so a reported effect allele can be cited directly.

## Limitations

- **Mapped genes are positional.** A gene is listed when a variant overlaps it, or when it is the nearest 5' or 3' gene. A reported gene is therefore locus-level and not necessarily the causal gene. CACNA1C spans roughly 700 kb, so an overlapping variant does not establish CACNA1C as causal at that locus.
- **Curated associations only.** The Catalog holds published variant-trait associations. It is not a summary-statistics repository, and a zero count is not evidence of no effect.
- **Association is not causal direction.** A `beta` or `or_value` describes the estimated effect of an allele on the trait, not whether activating or inhibiting the gene changes it.
- **Trait coverage varies.** A trait absent from the Catalog cannot be queried by ID. Search with `--query` first and confirm the matched name.
- **Ancestry is per study.** Reported sample size and ancestry come from `gwascatalog_get_studies`, not from the association row.
- **Publication notices and retractions are not checked.** Retained PMIDs are Catalog citations, not verified papers.
- **No phenotype-wide ranking.** This lane does not rank a gene against all genes for a trait. The Catalog has no equivalent endpoint, and ranking is not part of the synthesis.

## Scientific use

Use this lane to establish whether curated genetic association evidence is recorded for a gene-phenotype pair, and to name the variants, effect alleles, effect sizes and studies behind it. Report the association count, the strongest p-value, the effect alleles, the accessions, the PMIDs, and the study sample size and ancestry. Then use PubMed screening to read what individual studies actually reported, including null and contradictory findings.

Do not describe an association as a mechanism, do not convert a locus-level mapped gene into a causal gene, and do not merge an association measure with count-based or text-mining measures into a single causal score.
