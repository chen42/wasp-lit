---
name: wasp-lit
description: Search PubMed for selected genes against a phenotype and GeneCup-style keyword ontologies; assess gene-to-phenotype evidence with read-only concept-screening subagents; retain complete PMID-linked abstracts and accessible full texts for follow-up questions; reopen or update a persistent literature corpus.
metadata:
  version: "0.4.0"
---

# wasp-lit

Build a persistent literature corpus, screen its sources, and answer questions from the saved evidence. The wasp's paper nest is the organizing model: build the corpus in durable layers and retain sources and screening decisions so a later conversation can revisit them. A synthesis is a derived view, never a replacement for an abstract or paper.

## Establish scope

Read [workflow](references/workflow.md) and [gene function context and concept prioritization](references/gene-function-context.md), and inspect the research workspace before starting. Name each workspace `wasp-lit-<gene>-<phenotype>/` (or `wasp-lit-<genes>-<phenotype>/` for multi-gene runs) so multiple searches can coexist without collision. Keep human-readable files at the top level in Markdown (`README.md`, `synthesis.md`, `human-decisions.md`, `ai-decisions.md`, `gene-function.md`, and `gwas-associations.md`), and store machine JSON/JSONL state under `corpus/`. Separate human decisions (`human-decisions.md`, updated via `wasp.py human-decision`) from AI coordinator, Jev triage, and subagent screening decisions (`ai-decisions.md`). For each gene, retrieve NCBI Gene and WikiGenes function context before prioritizing PubMed concepts; save raw function-only JSON extracts in `corpus/gene-function/` and write the human-readable baseline summary in `gene-function.md` (or `gene-function/<GENE>.md` when evaluating multiple genes). Ask for material missing inputs:

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

## Screening: Jev triage and fallback workers

The host parent owns query planning, retrieval, deduplication, corpus writes, validation, synthesis and conversation continuity.

Run `wasp.py triage` (Jev structured classification) as the primary abstract screening step. Under the default `raw` policy, Jev screens every retrieved `gene × concept × PMID` pair for `gene_identity`, `concept_addressed`, `species_in_scope`, and `decision` (`include`, `exclude`, or `needs_review`). Once Jev has screened the pairs, `include` and `exclude` decisions are settled directly in `corpus/triage.jsonl`, `overview.json`, and `ai-decisions.md`, and there is no need for LLM `concept-screener` subagents to re-screen them. Proceed directly to `wasp.py fulltext` and synthesis unless unresolved `needs_review` items remain.

Read [screening and synthesis](references/evidence-and-synthesis.md) and [subagent execution](references/subagents.md) only if `wasp.py jobs` generates pending packets (for example, when Jev flags an ambiguous gene homonym as `needs_review` or when `TYPESAFE_API_KEY` is unavailable). In Pi, read the installed `pi-subagents` skill; on other harnesses, use the host runtime's native subagent tool with the generated `jobs-index.json` or JSON wave plans.

When subagent screening is needed for unresolved packets, use `concept-screener`, fresh context, one gene and one concept per bounded packet. Preserve its read-only tools; do not pin a model in this skill. Group small packets into bounded workflow waves, not one worker per PMID. Require exact supporting quotations for subagent inclusions and preserve direction targets so expression changes are not mistaken for behavioral effects.

Persist worker outputs using runtime output bindings in Pi, or write and validate returned JSONL lines with `evidence-record` on harnesses that return worker responses in messages. Validate assigned versus returned PMIDs, summary counts, enums, record hashes and quotation fidelity before import. A worker failure is unresolved work, not exclusion.

## Synthesis and follow-up

Follow the relevant `weaver-text` source-capture, citation and literature-synthesis guidance. Retain excluded records for audit, an intentional exception to its usual irrelevant-abstract discard rule. Read original sources before making a claim. The main goal is to assess candidate-gene plausibility through direct and indirect evidence, including gene-gene-phenotype and gene-pathway-phenotype chains. Trace and qualify each intermediate step; pathway or network membership alone does not establish causality. Distinguish gene identity, association, perturbation, mechanism, expression, reviews, species transfer and phenotype relevance. Do not rank genes by publication counts or invent numerical causal scores.

Cite empirical claims with adjacent PMID links, for example `[PMID: verified-ID](https://pubmed.ncbi.nlm.nih.gov/verified-ID/)`. Use only IDs present in the corpus. Label preprints and state whether evidence came from an abstract or full text. DOI identity alone does not link a preprint to its published version. Publication notices require a separate documented check.

In all saved workspace Markdown files (`synthesis.md`, `human-decisions.md`, `ai-decisions.md`, `gene-function.md`, `gwas-associations.md`, and `README.md`), use standard portable Markdown:
- Never use `file://` URIs in saved `.md` files (even if the host chat UI uses `file://` in conversation messages); `markdown-it` and `markdown-preview.nvim` reject the `file:` scheme and leave raw bracketed text unrendered. Always link local workspace files using relative POSIX paths starting with `./` or `../`, such as `[NCBI Gene summary](./corpus/gene-function/CACNA1C-ncbi-gene.json)`.
- Use natural-language link text rather than filenames ending in `.md` (write `[AI decision and screening log](./ai-decisions.md)`, never `[ai-decisions.md](...)` or bare `ai-decisions.md` in prose), so Markdown `linkify` passes do not mistake `.md` for Moldova's top-level domain.
- Do not wrap gene symbols, protein names, anatomical terms, or ontology concept domains in inline-code backticks in narrative prose (write `CACNA1C`, `CaV1.2`, and "the nicotine and reward domains", not `` `CACNA1C` `` or `` `drug/nicotine` ``). Reserve backticks for literal SHA-256 hashes or run IDs in the provenance section. `wasp.py audit` verifies saved workspace `.md` files against `file://` URIs and `.md` linkify traps.

For focused candidate-gene evaluations, use the local [synthesis prompt](synthesis_prompt.txt) and [synthesis template](templates/synthesis.md). Briefly state gene function with links to the NCBI and WikiGenes function records, followed by a concise "Anatomical expression" section describing widespread versus restricted tissue or brain-region expression and reported cell types, with species-specific citations and enrichment distinguished from specificity. State when those details are not established by the available sources. Name the gene-function-prioritized concept domains and the other ontology concepts searched across both the Gene Arm (`Gene x Concept`) and the Phenotype Arm (`Phenotype x Concept`) when a two-arm bipartite search is executed, link the overlapping ontology concept reviews (`./okf/concepts/<slug>.md`), emerging topic reviews, and the unified [Open Knowledge Format index](./okf/index.md) inline in prose (do not duplicate the OKF concept summary table inside `synthesis.md`), and report the separate GWAS lane. State the most likely molecular mechanism or evidence-supported chain with citations, distinguishing observations from inferred links and plausibility from causality. Include conflicting and null findings where present.

In the `Limitations and Future Experimental Tests` section of `synthesis.md`, include two distinct tiers of experimental proposals grounded in the corpus:
- **Core Mechanistic and Circuit Validation Experiments**: Direct falsifiable tests of the canonical `Gene x Phenotype` convergence nodes (such as CRISPR prime editing of lead GWAS variants, circuit-specific manipulations in high-overlap brain regions, and longitudinal stage-dependent assays).
- **Exploratory Bipartite Hypotheses (High-Impact Mechanistic Bridges)**: Literature-based discovery (Swanson A-B-C bridging) across the bipartite graph that connects well-characterized molecular, cellular, or biophysical mechanisms from one arm to behavioral or circuit phenomena in the other arm that have never been tested together. Do not use numerical points (`1.`, `2.`, `3.`) for the hypotheses; present each hypothesis under an unnumbered `####` subheading followed by cohesive scientific prose. Mine two structural patterns in `corpus/okf_graph.json` and `okf/concepts/*.md`:
  - **Asymmetric Overlap Bridges**: Ontology concepts with `evidence_role: "overlap"` where both the Gene Arm and Phenotype Arm contain confirmed studies, but the specific molecular pathway or cell-type manipulation in the Gene Arm has never been crossed with the operant or behavioral readout in the Phenotype Arm.
  - **One-Sided Concept Bridges**: High-density `gene_only` or `phenotype_only` nodes where a specific molecular substrate, proteolytic cleavage event, channel property, or anatomical hub in one arm provides a direct mechanistic bridge to an unexplained phenotype in the other arm.
  Within each exploratory bipartite hypothesis paragraph, cover the bipartite premise citing specific Gene Arm PMIDs (`A -> B`) and Phenotype Arm PMIDs (`B -> C`), the mechanistic rationale explaining why the bridge is biologically plausible and high-impact, and the experimental design and falsifiable readouts specifying species, cell-type or circuit targeting, behavioral paradigm, and what outcome would falsify the hypothesis.

Follow any user-specified word limit as a hard limit; default to at most 1,000 words for the executive summary (`## Summary`) unless asked otherwise. Complete PMID enumeration does not establish complete abstract screening, and even a fully screened scoped set cannot establish universal absence of published evidence.

For later conversations, read context, overview and a question-specific packet, then reopen its abstracts or full texts. Read [corpus and resume](references/corpus-and-resume.md). Save dated questions, syntheses and evidence references in research notes. Do not promise automatic chat memory.

## Commands and verification

Resolve script paths relative to this skill directory. The [runbook](references/runbook.md) gives full commands and the agent-install procedure.

- `init`, `plan-search`: freeze approved context, ontology and exact queries in `corpus/`, and render `README.md`, `human-decisions.md`, and `ai-decisions.md` at the workspace root.
- `human-decision`: record a user-approved scope change, concept-cap approval, or manual screening override in `corpus/human_decisions.jsonl` and refresh `human-decisions.md`.
- `collect`: enumerate PMIDs and retrieve capped abstracts, resumably.
- `triage`, `triage-report`: Jev structured classification to screen all retrieved `gene × concept × PMID` pairs under the default `raw` policy (`include`, `exclude`, `needs_review`), updating `overview.json` and `ai-decisions.md`.
- `jobs`: generate worker packets, portable JSON wave plans, and Pi workflow scripts only for unscreened or `needs_review` pairs not already settled by Jev; it launches nothing.
- `evidence-validate`, `evidence-import`, `evidence-record`: validate and retain screening output with its actual runtime run ID, automatically refreshing the subagent screening ledger in `ai-decisions.md`.
- `packet`, `status`: reopen sources and coverage without a new search.
- `fulltext`: retain accessible BioC texts with verified identity, respecting the run quota.
- `acknowledge-license --source`: record the PubMed or GWAS Catalog terms notification.
- `phenotype-search`: resolve a trait name, ID, or saved MCP capture to an ontology ID.
- `associations`: page the GWAS Catalog over MCP, retain gene-trait associations in `corpus/`, and render `gwas-associations.md`.
- `association-report`: report the retained associations for a run with their variants, studies and PMIDs.
- `okf`, `export-okf`: after user confirmation (`--confirm`), export strictly confirmed `include` references (subagent or human override) into a two-tier Google Open Knowledge Format network under `okf/` (`okf/concepts/<slug>.md` for Ontology Concept and Emerging Topic Mini-Reviews, `okf/<PMID>.md` for Atomic Reference Notes, `okf/index.md` catalog, and `corpus/okf_graph.json` for the Cytoscape.js HTML tab `okf.html`).
- `okf-topic`: record a custom Emerging Topic Mini-Review (`category: emerging`, colored `#ff79c6` in the Cytoscape graph) for themes emerging outside the fixed ontology.
- `audit`: check source integrity, membership, record hashes, quotations, and Markdown portability.
- `scripts/wikigenes.py`: retrieve function-related WikiGenes sections for human, mouse and rat; see `references/wikigenes.md` and `references/gene-function-context.md`.

Run `python3 -m unittest discover -s tests -v` for offline validation. Synthetic tests are not literature evidence. Live pilot acceptance requires user-selected genes, phenotype and species scope, reconciled PMIDs, validated worker outputs, accessible full text where available, and a fresh-session source-reopening check.

Current boundaries: one live R5 retrieval succeeded through NCBI PMC `efetch db=pmc` as the first route (PMID 35590255); this does not establish general route availability. Full text then falls back to Europe PMC JATS and PMC BioC. Selection prioritizes the target phenotype and drug domains, then direct and indirect phenotype relevance, with PubMed publication-date order within each group. An oversized undated set, overloaded publication day, or unreconciled count stops complete-enumeration claims. See [full text](references/full-text.md) for access and selection rules. The association lane is human-only, returns curated Catalog associations rather than direction, and cannot rank a gene against all genes for a trait.
