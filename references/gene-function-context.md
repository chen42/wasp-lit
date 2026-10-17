# Gene function context and concept prioritization

Obtain gene-function context before prioritizing literature-search concepts. This context informs search design and a brief synthesis statement; it is not evidence that the gene affects the target phenotype.

## Resolve and retrieve function sources

For each gene and reference organism:

1. Resolve the gene to an unambiguous NCBI Gene record for the stated organism. Use the installed `ncbi-sequence-fetch` skill's generic NCBI `search` command with the `gene` database and both symbol and organism qualifiers. Inspect candidate records; do not select among ambiguous hits by rank alone.
2. Retrieve the selected record with the installed `pubmed-database` skill's `fetch_database_summary` function for database `gene`. Retain only the returned functional `summary` paragraph plus the minimum identity/provenance fields needed to verify symbol, Gene ID, organism, record URL, query, retrieval date, and source checksum. Do not copy unrelated aliases, genomic coordinates, expression, disease, or phenotype fields into the function-context note.
3. Run `scripts/wikigenes.py` for the selected symbol. For the default human, mouse and rat scope, retain only exact-symbol records returned for Homo sapiens, Mus musculus and Rattus norvegicus. If an ortholog's species-specific symbol differs, resolve it independently from NCBI Gene and query that symbol separately. Do not infer orthology or gene identity from similar symbols.
4. Save function-only extracts under `references/gene-function/`, separated by source and taxon, with source URL/record ID, retrieval date, raw-source checksum/cache path, and relevant source sections. Keep raw temporary API responses outside this reference section; do not store whole NCBI metadata records here. For WikiGenes, include only clearly function-related sections such as molecular/biological context, regulatory relationships, pathways, or interactions. If no suitable section exists, record that rather than filling the gap with unrelated disease text.

Example WikiGenes command:

```bash
python3 "$SKILL/scripts/wikigenes.py" CACNA1C \
  --species human,mouse,rat \
  --output "$PROJECT/references/gene-function/CACNA1C-wikigenes.json"
```

For NCBI Gene ID resolution, use the `search` command documented by `ncbi-sequence-fetch`, for example:

```bash
NCBI="$HOME/.agents/skills/ncbi_sequence_fetch/scripts/ncbi_fetch.py"
PUBMED="$HOME/.agents/skills/pubmed_database/scripts/pubmed_api.py"
uv run "$NCBI" search '"CACNA1C"[Gene Name] AND "Homo sapiens"[Organism]' \
  --database gene --retmax 20 --output "$TMP/ncbi-gene-search.json"
uv run "$PUBMED" "$TMP/ncbi-gene-summary.json" \
  fetch_database_summary gene "$VERIFIED_NCBI_GENE_ID"
```

Inspect returned Gene IDs, official symbols, and organisms before choosing a record. From the summary response, copy only `uid`, `name`, `description`, `organism`, and functional `summary` into the persistent gene-function extract; record the query, NCBI Gene URL, retrieval date, and SHA-256 of the raw response. Keep raw API output in a temporary directory outside the references folder. Read both skills' prerequisites and terms notices before live retrieval. Never expose credentials.

WikiGenes content is collaborative and may contain mislinked or outdated statements. Preserve its source wording and citations, and verify substantive claims against cited primary papers before using them as mechanistic evidence. The NCBI Gene summary is a compact functional overview, not a phenotype-specific evidence assessment. Neither source should be used to infer causality for the research phenotype.

## Prioritize concepts from function and phenotype

After saving function context, create `references/selected-concept-domains.md` before search planning. For each gene, identify the high-priority concept IDs that merit the larger cap, with a short rationale tied to documented function and phenotype; note plausible intermediates or tissues. Search every ontology concept and preserve the direct phenotype query for every gene. Assign up to 200 abstracts per gene × high-priority concept and up to 30 per other gene × concept, including the direct phenotype query, unless the user specifies different caps. Function may prioritize concepts involving brain regions, cell types, neurotransmission, signalling, expression, neuroplasticity, reward, stress, or related drugs, but these are examples, not an automatic mapping. Keep species, assay and tissue specificity explicit. Do not add unapproved aliases or silently expand literal search terms; record proposed vocabulary additions for approval.

Always run the GWAS Catalog gene-trait association lane for each eligible human gene and target phenotype, independently of PubMed concept prioritization. Resolve and verify the phenotype ontology ID first, run `associations`, and report the curated variant-trait associations with their effect alleles, studies, PMIDs, and sample size. This is association evidence, not causal direction or mechanism, and a mapped gene is locus-level rather than causal. If the trait cannot be resolved or the capture is blocked, record the GWAS lane as blocked with the reason rather than silently omitting it or reporting zero evidence.

In the synthesis, state the gene's function in one or two brief sentences with links to the saved NCBI and WikiGenes records. List the prioritized concept domains and other ontology concepts searched, and the separate GWAS result/status. The function sources inform why concepts were prioritized; phenotype claims must still be supported by the empirical literature and GWAS evidence described in the corresponding source records.
