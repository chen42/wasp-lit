# Search strategy and coverage

## Queries and budgets

Use explicit Boolean `OR`, with literal title/abstract terms, for gene aliases and concept vocabulary. Save the exact query and PubMed translation. Preserve the concept identifiers and categories; do not treat the pipe-delimited legacy source strings as PubMed operators. The active resource is the curated vocabulary in `resources/addiction_ontology.json`, whose changes and rationale are in `plan/ontology-curation.md`; the legacy normalization is preserved for comparison. Multiword phrases can be restrictive, and every quoted term is matched literally, so inspect translations and quoted-phrase warnings before interpreting coverage. Logged vocabulary refinements require approval when they change scope.

For G genes and C ontology concepts, search all G × C concept queries and add G direct phenotype queries. Each high-priority, function-selected gene × concept stratum has a 200-abstract cap; other concepts and the direct phenotype query have a 30-abstract cap. For gene g with H_g high-priority concepts, the maximum selected memberships are `200 × H_g + 30 × (C − H_g + 1)`. Overlapping PMIDs reduce unique abstract retrievals, but not the per-stratum membership or screening workload. A membership is not an independent paper or study.

Both species identity and evidence-species scope are recorded. The initial code does not infer a PubMed species filter from that scope. Workers apply the agreed scope to reported species. Unknown species remain uncertain; the reference organism is not a substitute for the studied organism.

## Retrieval versus interpretation vocabulary

Use a concept's optional `search_terms` for its PubMed OR clause, falling back to `terms` only when that field is absent. Keep the complete `terms` list in the frozen concept, worker manifest and follow-up packet. A search subset must be nonempty and contain only entries from the same concept's full vocabulary. The direct gene-phenotype lane still uses the context's `phenotype_terms`.

The active vocabulary has 611 full term occurrences and 402 effective search occurrences. Specific phrases such as `accumbens core` remain available for interpretation although `accumbens` is the retained search alternative. Distinct abbreviations and variants remain in retrieval when they may occur without the broader phrase. Read [keyword roles](keyword-roles.md) for the curation rules and how to add terms.

The coordinator does not automatically reduce terms at runtime or migrate existing workspaces. Literal containment suggests redundant alternatives; it does not establish identical live PubMed results. Inspect query translations and phrase warnings before interpreting coverage. A broad retrieved concept does not establish a specific subtype in a paper.

## Enumerate all IDs separately

The installed wrapper's simple search returns only IDs. The bundled extension retains count, query translation, warnings and raw response. Abstract selection uses the first capped IDs from the original query in `pub_date` order, not the concatenated order of date partitions.

The extension conservatively keeps each ESearch request below 10,000 IDs. For a larger set:

1. Save the root count and its newest IDs.
2. Query the complement of the publication-date partition range, retaining undated or out-of-range records.
3. Recursively split publication-date ranges until each slice fits the ID window.
4. Union and deduplicate IDs. Electronic and print dates can make slices overlap.
5. Repeat the root count and reconcile the unique union with it.

Only reconciled sets receive `complete_count_reconciled`. Date partitioning, counts, and raw calls remain auditable. PubMed can change during retrieval; this is not a frozen database snapshot. A changed count, inconsistent union, oversized single day, oversized undated set or request-bound failure leaves explicit incomplete coverage. The initial enumeration request bound is 2,048 per query. Do not bypass the wrapper or silently switch retrieval methods.

All discovered IDs receive membership records, including IDs without retrieved abstracts. IDs outside a stratum's assigned cap remain unassessed for that concept, even if an abstract was retrieved through another concept. Record each query's own cap and priority status; do not report only a run-wide cap.

## Coverage is multidimensional

Track PMID enumeration, abstract selection, actual record retrieval, abstract availability, screening decisions and full-text access separately. An uncapped query can still have missing abstracts or unresolved screening. `scope_screening_complete` requires reconciled IDs, no cap, no missing records or abstracts, and settled assessments for every selected record.

A complete scoped search can support "no relevant evidence in the searched and screened set." It cannot establish "no published evidence" without qualification. Zero relevant records in a capped set is not an absence result. A failed API call is not zero hits.

PubMed-only preprints remain separate PMID records. Preserve publication types and explicit relationships. Do not assume that equal or unequal DOIs establish whether a preprint and a journal article report the same study.

## Publication-date convention

Use PubMed's publication-date sort, not its Most Recent/indexing sort. PubMed sorts records with multiple publication dates by their earliest publication date and handles incomplete dates internally. Preserve the supplied date components rather than inventing a precise date. The controlling help excerpt is saved in `sources/2026-10-07_pubmed_help_excerpt.md`.
