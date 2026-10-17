---
name: wasp-lit
description: Search PubMed for selected genes against a phenotype and GeneCup-style keyword ontologies; assess gene-to-phenotype evidence with read-only concept-screening subagents; retain complete PMID-linked abstracts and accessible full texts for follow-up questions; reopen or update a persistent literature corpus.
metadata:
  version: "0.4.0"
---

# wasp-lit

Build a persistent literature corpus, screen its sources, and answer questions from the saved evidence. The wasp's paper nest is the organizing model: build the corpus in durable layers and retain sources and screening decisions so a later conversation can revisit them. A synthesis is a derived view, never a replacement for an abstract or paper.

## Establish scope

Read [workflow](references/workflow.md) and [gene function context and concept prioritization](references/gene-function-context.md), and inspect the research workspace before starting. For each gene, retrieve NCBI Gene and WikiGenes function context before prioritizing PubMed concepts; save function-only extracts in the project's `references/gene-function/`. Ask for material missing inputs:

- Genes with explicit reference organism and verified aliases or user-confirmed identities.
- Phenotype and agreed search vocabulary. Keep related behavioral endpoints distinct.
- Evidence-species scope, separate from the organism used for gene identity.
- Target phenotype and any user-required concepts or branches. After collecting gene function context, identify the high-priority concepts that merit the larger abstract cap. Search all 50 concepts in the bundled hierarchy plus the direct phenotype lane; it is a curated retrieval vocabulary, not a formal biomedical ontology. Its revision is documented in [ontology curation](plan/ontology-curation.md), and the unedited normalization is retained as `resources/addiction_ontology.legacy-v1.json`.
- A research workspace outside this skill directory.

Keep retrieval and interpretation vocabulary separate in the canonical JSON. Use optional `search_terms` in PubMed queries, falling back to all `terms` when absent. Pass the full `terms` list to screening and synthesis so reported subregions and assay details are retained without inferring them from a broad match. Read [keyword roles](references/keyword-roles.md) before editing either field; existing workspaces retain their frozen vocabulary.

Search every ontology concept and the independent direct gene × phenotype query. For each gene, assign a 200-abstract cap to concepts selected from its documented function summary and a 30-abstract cap to all other concepts, including the direct phenotype query, unless the user specifies otherwise. Obtain all matching PMIDs before applying each stratum's cap. Retrieve all records below the cap; otherwise retrieve the newest records by publication date. Keep the originally agreed full-text quota unchanged, shared across the run. Do not pool genes or concepts into one cap.

Always run the GWAS Catalog association lane for every eligible human gene and target phenotype, regardless of PubMed concept prioritization. Read [gene-phenotype associations](references/associations.md). Resolve the phenotype ID first, then report the gene's curated variant-trait associations separately from PubMed screening. GWAS and genetic association evidence comes from this lane, not from PubMed keyword screening. The lane is human: a nonhuman gene requires explicit cross-species-transfer approval. If trait resolution is blocked, record the reason rather than silently omitting the lane or reporting zero evidence.

Include preprints indexed in PubMed, labeled by publication type. Do not discover preprints from other services. Use the originally agreed full-text quota across the run, 10 by default, not per gene. Scope to screened-in records with direct or indirect phenotype relevance. Reviews can inform background but are not primary experimental evidence.

## Genetic association lane

The coordinator runs the GWAS Catalog association lane for every eligible gene-phenotype pair. It resolves each selected gene to a human HGNC symbol, then records, per gene and trait, the curated variant-trait associations: association count, strongest p-value, effect alleles, effect sizes, study accessions, PMIDs, and the capture provenance. Mapped genes are assigned by variant position, so a reported gene is locus-level and is not necessarily the causal gene. The Catalog reports association, not causal direction. Read [associations](references/associations.md) before reporting any of this as genetic evidence.

## Retrieval and sources

Use the installed `pubmed-database` skill. Read its prerequisites, credentials protocol, and applicable function references before live calls. Notify the user of PubMed/NCBI terms and paper-specific licensing. Never print credentials.

Read [search strategy](references/search-strategy.md) and [the PubMed extension](references/pubmed-extension.md). The bundled extension imports the installed wrapper and uses its shared rate-limited HTTP client. It does not replace that client or modify the installed skill. Run live commands through `uv`; ordinary offline corpus commands need only Python's standard library.

For human, mouse and rat WikiGenes gene-function context, use [the WikiGenes helper](references/wikigenes.md). Save only function-related sections and source provenance in the project references, separate from the PubMed corpus. The helper parses public HTML because no public gene-record REST interface is documented; it rate-limits and caches requests and does not infer orthology. WikiGenes and NCBI summaries inform concept prioritization and the brief gene-function statement, but do not establish phenotype causality.

Save complete abstracts, raw XML responses, query translations, all discovered PMIDs, query membership, timestamps and checksums before screening. Preserve hyphens, inline text and structured abstract sections. Missing abstracts, omitted records, failed requests and empty searches are different states.

Large searches require count-reconciled partitioning. Do not assume `retstart` can enumerate arbitrarily large PubMed result sets. If enumeration cannot reconcile all IDs, preserve the partial set and mark the stratum incomplete. Never report a failed search as zero evidence.

## Coordinator and workers

The host parent owns query planning, retrieval, deduplication, corpus writes, validation, synthesis and conversation continuity. Workers screen local sources only. Do not delegate retrieval or corpus writes.

Read [screening and synthesis](references/evidence-and-synthesis.md), [subagent execution](references/subagents.md), and the installed `pi-subagents` skill before launching workers. This skill's screening stage authorizes concept-screening delegation when the user requests its literature workflow. It does not authorize unrelated coding or review delegation.

Use `concept-screener`, fresh context, one gene and one concept per bounded packet. Check effective agent capabilities before execution. Preserve its read-only tools; do not pin a model in this skill. Group small packets into bounded workflow waves, not one worker per PMID. Parent launch authority and runtime fan-out limits still apply.

Read every assigned complete abstract. Lexical matching can annotate or prioritize records, but cannot silently exclude them from scientific screening. Keep null, conflicting and ambiguous evidence. Unknown experimental details stay unknown. Require exact supporting quotations for inclusion and preserve direction targets so expression changes are not mistaken for behavioral effects.

Persist worker outputs using runtime output bindings. Validate assigned versus returned PMIDs, summary counts, enums, record hashes and quotation fidelity before import. A worker failure is unresolved work, not exclusion. Scientific interpretation still needs parent review.

## Synthesis and follow-up

Follow the relevant `weaver-text` source-capture, citation and literature-synthesis guidance. Retain excluded records for audit, an intentional exception to its usual irrelevant-abstract discard rule. Read original sources before making a claim. The main goal is to assess candidate-gene plausibility through direct and indirect evidence, including gene-gene-phenotype and gene-pathway-phenotype chains. Trace and qualify each intermediate step; pathway or network membership alone does not establish causality. Distinguish gene identity, association, perturbation, mechanism, expression, reviews, species transfer and phenotype relevance. Do not rank genes by publication counts or invent numerical causal scores.

Cite empirical claims with adjacent PMID links, for example `[PMID: verified-ID](https://pubmed.ncbi.nlm.nih.gov/verified-ID/)`. Use only IDs present in the corpus. Label preprints and state whether evidence came from an abstract or full text. DOI identity alone does not link a preprint to its published version. Publication notices require a separate documented check.

For focused candidate-gene evaluations, use the local [synthesis prompt](synthesis_prompt.txt) and briefly state gene function with links to the NCBI and WikiGenes function records. Immediately follow with a brief "Anatomical expression" section: widespread versus restricted tissue/brain-region expression and reported cell types, with species-specific citations and enrichment distinguished from specificity. State when those details are not established by the available sources. Name the gene-function-prioritized concept domains and the other ontology concepts searched, and report the separate GWAS lane. State the most likely molecular mechanism or evidence-supported chain with citations, distinguishing observations from inferred links and plausibility from causality. Include conflicting and null findings where present. Do not add a generic limitations section; place specific caveats alongside the claims they qualify. Keep scope and search methods concise, devote most of the word budget to literature evidence, do not put the conclusion in the opening, and end with a balanced candidate-plausibility assessment. Follow any user-specified word limit as a hard limit; default to at most 800 words excluding citations unless asked otherwise. Complete PMID enumeration does not establish complete abstract screening, and even a fully screened scoped set cannot establish universal absence of published evidence.

For later conversations, read context, overview and a question-specific packet, then reopen its abstracts or full texts. Read [corpus and resume](references/corpus-and-resume.md). Save dated questions, syntheses and evidence references in research notes. Do not promise automatic chat memory.

## Commands and verification

Resolve script paths relative to this skill directory. The [runbook](references/runbook.md) gives full commands and the agent-install procedure.

- `init`, `plan-search`: freeze approved context, ontology and exact queries.
- `collect`: enumerate PMIDs and retrieve capped abstracts, resumably.
- `jobs`: generate complete worker packets and workflow scripts; it launches nothing.
- `evidence-validate`, `evidence-import`: validate and retain screening output with its actual runtime run ID.
- `packet`, `status`: reopen sources and coverage without a new search.
- `fulltext`: retain accessible BioC texts with verified identity, respecting the run quota.
- `acknowledge-license --source`: record the PubMed or GWAS Catalog terms notification.
- `phenotype-search`: resolve a trait name, ID, or saved MCP capture to an ontology ID.
- `associations`: page the GWAS Catalog over MCP and retain gene-trait associations for a run.
- `association-report`: report the retained associations for a run with their variants, studies and PMIDs.
- `audit`: check source integrity, membership, record hashes and quotations.
- `scripts/wikigenes.py`: retrieve function-related WikiGenes sections for human, mouse and rat; see `references/wikigenes.md` and `references/gene-function-context.md`.

Run `python3 -m unittest discover -s tests -v` for offline validation. Synthetic tests are not literature evidence. Live pilot acceptance requires user-selected genes, phenotype and species scope, reconciled PMIDs, validated worker outputs, accessible full text where available, and a fresh-session source-reopening check.

Current boundaries: one live R5 retrieval succeeded through NCBI PMC `efetch db=pmc` as the first route (PMID 35590255); this does not establish general route availability. Full text then falls back to Europe PMC JATS and PMC BioC. Selection prioritizes the target phenotype and drug domains, then direct and indirect phenotype relevance, with PubMed publication-date order within each group. An oversized undated set, overloaded publication day, or unreconciled count stops complete-enumeration claims. See [full text](references/full-text.md) for access and selection rules. The association lane is human-only, returns curated Catalog associations rather than direction, and cannot rank a gene against all genes for a trait.
