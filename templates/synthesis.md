# Candidate-gene plausibility assessment

Date: [date]<br>
Workspace/run: [workspace and run ID]<br>
Model: [LLM model name]

## Summary

[A concise summary (under 800 words) synthesizing candidate gene plausibility, direct empirical evidence status, key neurobiological mechanisms, cross-substance findings, and human genetic associations. Support empirical statements with verified PMID links.]

## Gene function and concept domains

[Briefly summarize gene function with relative links to the [baseline gene function summary](./gene-function.md) and raw records under `./corpus/gene-function/`, for example `[NCBI Gene summary](./corpus/gene-function/GENE-ncbi-gene.json)` and `[WikiGenes extract](./corpus/gene-function/GENE-wikigenes.json)`. Link to the [User decision log](./user-decisions.md) and [AI decision and screening log](./ai-decisions.md) for scope and concept-cap details. Never use `file://` URIs or `.md` filenames as link labels, and do not wrap gene symbols, protein names, or concept domains in backticks in narrative prose. Name the gene-function-prioritized concept domains that received 200 abstracts in natural language, the other ontology concepts searched with 30 abstracts each, and the direct phenotype query cap. State the GWAS Catalog association result for each eligible human gene-trait pair with a link to the [GWAS association summary](./gwas-associations.md), including effect alleles, studies and PMIDs, or the specific blocker.]

## Anatomical expression

[In two or three sentences, describe widespread versus restricted tissue/brain-region expression and reported neuronal, glial or other cell types. Distinguish enrichment from cell-type specificity and RNA from protein evidence; identify the species and cite sources. Do not infer restriction from limited sampling or targeted manipulation. State when distribution or specificity is not established.]

## Scope

[Briefly state phenotype, reference organism, evidence-species scope, PubMed coverage, full-text coverage, and any material access or cap limitation. Keep process detail short.]

## Literature evidence

[Trace direct and indirect gene-gene-phenotype or gene-pathway-phenotype chains. For each edge, name the study/model, relevant tissue or cell type, evidence type, phenotype, result, and uncertainty. Cite empirical claims with verified PMID links and source snapshots. Separate primary experiments, human association, computational network results, reviews, and functional-context summaries. Include conflicting and null findings where present. Place each material caveat next to the finding it qualifies.]

## Plausible molecular and circuit mechanisms

[State plausible molecular and circuit mechanisms, including both well-supported chains and looser, exploratory connections grounded in the literature. Highlight knowledge gaps and experimental uncertainties.]

## Scoped conclusion

[At the end, give a balanced assessment of candidate-gene plausibility, the strongest intermediate evidence chain, unsupported or weak links, and the next uncertainty. Do not infer causality from co-occurrence, pathway membership, or association alone.]

## Reviewed literature and evidence sources

[PMIDs, record hashes, relative source snapshot links, evidence IDs, and abstract or full-text level. Include relative `./` or `../` links to the saved NCBI Gene and WikiGenes function-only records, with descriptive link labels rather than bare `.md` filenames.]
