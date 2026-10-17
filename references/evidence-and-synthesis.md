# Screening and synthesis

## Assessment contract

A job specifies gene identity, phenotype, evidence-species scope, concept, assigned PMIDs, record hashes, query coverage and cap status. A worker returns one JSON object for each assigned PMID, in order, then one summary object. Use `agents/concept-screener.md` as the canonical rubric.

Use the full concept `terms` as interpretation vocabulary, not just the optional retrieval subset `search_terms`. Worker manifests and follow-up packets retain the full list from the frozen scope. Preserve reported specificity in `finding`, `tissue_or_cell` and `model`, with supporting source text. An unspecified accumbens location cannot become core or shell, and an unspecified aversion assay cannot become conditioned odor aversion, because those phrases appear in the vocabulary. Related terms are not necessarily synonyms. See [keyword roles](keyword-roles.md).

Gene identity is confirmed, ambiguous or absent. Ambiguous identity requires `needs_review`; a symbol's co-occurrence with a keyword is not gene-concept evidence. Concept support and phenotype relevance are separate classifications. A contextual paper can study the gene and concept without directly studying the phenotype.

Direction means the direction of a stated measured variable. Record that variable in `direction_target`. Do not conflate expression, signaling, intake, motivation, withdrawal or reinstatement. An explicit null result is `none`, not missing evidence. Several opposing outcomes require a finding description rather than a misleading single direction.

Species, model and tissue/cell type stay null unless reported in the abstract. Do not fill them from gene-reference metadata or prior knowledge. Reviews remain background, not primary experiments. GWAS trait keywords do not establish GWAS design or a causal gene assignment.

Inclusion requires an exact supporting abstract quotation. Keep punctuation, hyphens and Unicode characters unchanged. Do not paraphrase or normalize a quotation. The importer stores offsets, the source record hash, rubric checksum, context checksum and runtime run ID. It rejects omitted, duplicate or reordered PMIDs, invalid fields, changed packets, inconsistent counts and mismatched quotations.

Deterministic validation establishes source fidelity and bookkeeping, not scientific support. The parent must review whether a quotation supports the finding and whether study design warrants the interpretation. Pilot checks should cover ambiguous symbols, incidental mentions, null findings, conflicting outcomes and reviews.

## Scientific synthesis

Use the local [synthesis prompt](../synthesis_prompt.txt) and [output template](../templates/synthesis.md).

Read `weaver-text` Modules 03, 04's literature-synthesis and claim-to-evidence guidance, 05's citation guidance, and 08's source capture when synthesis is requested. Apply them to the research question without creating manuscript-production scaffolding.

Use direct, neutral prose. The main goal is to assess candidate-gene plausibility through direct evidence and indirect chains, not merely report whether a direct gene-phenotype association exists. Trace gene-gene-phenotype and gene-pathway-phenotype links across intermediate steps. For each link, identify its evidence type, model, tissue and limitations; mark inferential or unsupported steps rather than treating a connected pathway as proof of causality. Keep empirical findings separate from interpretation. Qualify species transfer, observational associations and variant-to-gene uncertainty. Do not infer necessity, sufficiency or mechanism from a partial effect or association.

Before screening, obtain function summaries from NCBI Gene and relevant WikiGenes records for each gene and taxon. Save function-only source extracts with identity and provenance under `references/gene-function/`; use them to prioritize concepts for the 200-abstract cap, not as evidence for a phenotype association. Search all ontology concepts, applying a 30-abstract cap to non-prioritized concepts and the direct phenotype query unless the user specifies otherwise. In the synthesis, briefly summarize gene function with links to those records and name the prioritized concept domains and other concepts searched. The direct phenotype query remains required, and the GWAS Catalog association lane must always be run for eligible human gene-trait pairs, reported with its variants, effect alleles, studies and PMIDs, or a blocker explained.

Each empirical claim needs an adjacent verified PMID link and an appropriate source passage. Evidence IDs point to exact PubMed record hashes and saved source responses. An abstract and full text are sources for one paper, not independent studies; cross-concept membership and repeated screening are not replication. Preserve contrary and null findings. Use reviews for context and primary studies for specific experiments. Check publication notices separately when needed and record the source, date and limits of that check.

Immediately after the main gene-function description, add a brief "Anatomical expression" section of two or three sentences. Describe whether expression is widespread or restricted across tissues and relevant brain regions, and identify reported neuronal, glial or other cell types. Distinguish enrichment from cell-type specificity and RNA from protein evidence; cite the sources and identify the species. Do not infer restricted expression from limited sampling or targeted manipulation. State when the available sources do not establish distribution or specificity.

For focused candidate-gene evaluations, state the most likely molecular mechanism or evidence-supported chain with citations for each empirical link. Distinguish measured findings from inferred steps and plausibility from causality. Include conflicting and null findings where present. Do not use a generic limitations section; place specific caveats beside the evidence they qualify. Keep scope and search methods concise, devote most words to evidence, do not state the conclusion in the opening, and end with a balanced candidate-plausibility assessment. When the user sets a word limit, treat it as a hard limit. The default maximum is 800 words excluding citations unless the user requests otherwise. Report retrieval caps or missing records briefly, and never treat them as scientific exclusions.
