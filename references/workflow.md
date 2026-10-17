# Workflow

## Start or resume

Inspect the existing project before creating files. Research data belong outside the installed skill directory. Keep the original GeneCup `addiction_ontology.json` unchanged; tests verify its hash. Use the local [synthesis prompt](../synthesis_prompt.txt) for candidate-gene evaluations. Use the curated `resources/addiction_ontology.json`, with stable category/name IDs and literal terms; `resources/addiction_ontology.legacy-v1.json` preserves the unedited normalization for comparison.

Confirm genes, phenotype, reference organism, evidence-species scope and any user-required concepts. Before prioritizing concepts or freezing the search plan, obtain gene-function context from NCBI Gene and WikiGenes for each gene and relevant taxon. Save only function information plus minimal identity and provenance in `references/gene-function/`; see [gene function context and concept prioritization](gene-function-context.md). Use the documented functions to identify the concepts that merit the larger abstract cap and record those rationales in `references/selected-concept-domains.md`. Search all ontology concepts, not only the prioritized set.

Do not silently add aliases, synonyms, species filters or open-access filters. Function context informs cap prioritization but does not expand search vocabulary or establish phenotype causality. Identity can come from user confirmation or an authoritative gene resource with provenance. An ordinary-word alias needs contextual disambiguation even when its identity was verified. Preserve user-required concepts and the direct phenotype query for every gene.

Freeze function sources, concept priorities, context and ontology before collection. A changed research question or identity scope requires a separate workspace in this version. A new retrieval run can update sources within the same scope.

## Search and retrieve

Plan one direct gene × phenotype query for every gene and a query for every ontology concept. Each gene-function-prioritized concept receives a 200-abstract cap; all other concepts and the direct phenotype query receive a 30-abstract cap. Each gene × concept stratum has its own cap. Contextual queries do not require the phenotype, so they can capture relevant biology beyond the phenotype literature. Independently run the GWAS Catalog gene-trait association lane for every eligible human gene and target phenotype, and report it separately from PubMed screening. A blocked GWAS lane must have a recorded reason.

Enumerate all matching PMIDs independently of the abstract cap. Preserve exact queries, translations, warnings, counts and membership. Select abstracts in PubMed `pub_date` order. Deduplicate PMIDs only after selection, keeping each stratum's membership and selection flag.

Fetch selected records in batches. Preserve raw XML and the complete parsed abstract. Reconcile omitted records once, then mark unresolved records missing. Resume the same run ID to continue unfinished retrieval without repeating completed searches. Use a new run ID and `--refresh` to fetch a new PubMed response; the canonical article row updates only if the parsed record changes.

## Screen

Generate bounded packets, with one gene and one concept per job. Every available selected abstract is assigned; missing abstracts remain explicitly unscreened. Packet boundaries limit context size without truncating sources. Generated workflow waves contain at most 64 jobs by default, dispatched in awaited groups of 6. These limits are independent of API request and abstract-packet batching.

The host parent explicitly launches the workflow through `pi-subagents`. Workers read sources, return JSONL assessments, and never edit the corpus. Import only outputs that pass source-version, PMID-completeness, summary and quotation checks. Review scientific interpretation separately; deterministic validation cannot establish that a quotation supports a finding.

## Retrieve full text and synthesize

After screening and unresolved-item review, use the originally agreed full-text quota for the run (10 by default) across included records with direct or indirect phenotype relevance. Prioritize the exact target-phenotype and target-drug concept domains first, then records with direct phenotype relevance in other domains, then indirect relevance; use PubMed `pub_date` order within each group. Do not multiply the quota by concepts or cap tiers. Reuse checked local full texts. Do not turn transient access failures into paywall claims or silently skip an unresolved higher-priority candidate. Try PMC efetch before Europe PMC and BioC. Operational timestamps use America/Chicago; preserve UTC in machine provenance.

Write a dated synthesis using the sources and a concise coverage statement. Include a brief gene-function description with links to the saved NCBI and WikiGenes function records. Immediately follow with a brief "Anatomical expression" section on tissue/brain-region distribution and reported cell types, distinguishing enrichment from specificity and citing species-specific sources. State when distribution or specificity is not established. Name the gene-function-prioritized concept domains and the other ontology concepts searched, and state the separate GWAS result or blocker. Keep primary findings separate from reviews and interpretation. State the most likely molecular mechanism or evidence-supported chain with citations for each empirical link, while distinguishing measured findings from inferred steps and plausibility from causality. Include conflicting and null findings. Do not add a generic limitations section; place specific caveats next to the claims they qualify. Report what remains unassessed, capped or unavailable in a concise coverage statement.

## Return later

Read `context.json`, `overview.json` and relevant packets. Reopen the cited sources rather than relying on a previous summary or chat context. Save material follow-up questions and answers with their PMID, record hash, source-response reference and evidence IDs.
