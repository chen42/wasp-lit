# Ontology curation

Date: 2026-10-07
Scope: prompt-coverage vocabulary revised for LLM-assisted screening.
Supersedes the earlier static ontology quality audit (`ontology-quality-review.md`, kept with the design notes and not distributed with the skill) for anything it changes.

## Files

| File | Role | Status |
| --- | --- | --- |
| `../addiction_ontology.json` | Original supplied Python literal | Unchanged |
| `../resources/addiction_ontology.legacy-v1.json` | Normalized copy of the original vocabulary | Frozen reference |
| `../resources/addiction_ontology.json` | Curated retrieval vocabulary, now the `init` default | Active |

Hashes:

- Original literal: `b7338ed1d1f75aa1aaafd9c353ef8176f8df4b77e94cb38bbc7b11721aa42bcd`
- Legacy normalized: `fd12c3a4c1b16b1ac4d701c24c743d33ce5dad5d889f94e9eff6afedd0a0dd04`

The original vocabulary had 8 categories, 47 concepts, 363 term occurrences and 348 distinct terms. The active vocabulary now has 7 categories, 50 concepts, 611 full-vocabulary occurrences and 610 distinct terms. Its effective search subsets contain 402 occurrences and 401 distinct terms.

## Vocabulary revisions

- Curated revision 1: 7 categories, 48 concepts, 584 term occurrences and 583 distinct terms. Resource SHA256: `b20f314610c93d96b9ad9446400d4894af1adb6b92cedeef2852a169e96cac50`.
- Curated revision 2: completed the pending coverage additions from the earlier review. Added `addiction/habit` with habit, goal-directed behavior, outcome devaluation and contingency degradation terms; added `brain/bnst` with BNST and its full names; added cue reactivity, cue-induced craving and cue-induced drug seeking to `addiction/relapse`; completed the inhibitory postsynaptic current/potential expansions and several plural measurement forms in `function/neuroplasticity`. This added 26 term occurrences and two concepts without removing any existing term or concept. Resource SHA256: `e35a4e2d42970b786bfcd8de737309be1572c7c3e56e702fc1453bf4a5e85879`. `schema_version` remains 1 because the file structure did not change.

- Curated revision 3: separated retrieval from interpretation using optional `search_terms`. The user's `conditioned odor aversion` addition was preserved. Explicit subsets for 39 concepts omit 209 separate query alternatives while retaining every entry in `terms`; 11 concepts continue to search all their terms. Resource SHA256: `2cbe661227a7baf4b8133376b77866c279ca615e4d02cec5fd5b1256867f5502`. The optional field is backward-compatible within schema version 1. See [keyword roles](../references/keyword-roles.md) for the review rules, maintenance and limitations.

Habit and goal-directed behavior are related but distinct forms of action control. Their shared retrieval lane does not imply that they are synonyms. BNST has its own anatomical lane rather than being treated as an amygdala synonym. No additional method vocabulary or unrelated coverage candidates were added.

Research workspaces retain their frozen vocabulary and hash. This update does not alter existing corpora.

The old vocabulary was built to widen coverage on a web site. With LLM screening available, retrieval can favor phrases that are unambiguous and easy to screen, because off-target records now cost screening effort rather than being filtered by hand.

## Curation rules applied

1. An ambiguous or generic token is replaced by the explicit phrase naming the intended structure. Coverage of the abbreviation is given up when it collides with an unrelated expression of the same string.
2. Explicit singular and plural forms are retained rather than assuming equivalent retrieval for both forms.
3. Terms describing a different biological entity are moved to a correctly named concept instead of being deleted.
4. Categories that describe study design rather than biology are removed from the PubMed keyword lane.
5. Substance, treatment and mechanism terms stay together within the drug category, as requested.
6. Gene symbol collisions with anatomical or functional terms are left for the analysis step, as requested.

## Ambiguous terms replaced

| Concept | Removed | Replacement | Reason |
| --- | --- | --- | --- |
| addiction/aversion | `CTA` | `conditioned taste aversion`, `taste aversion` | CTA also means computed tomography angiography |
| addiction/reward | `CPP`, `ICSS` | `conditioned place preference`, `intracranial self stimulation` | CPP also means cerebral perfusion pressure |
| addiction/relapse | `seeking` | `drug seeking` | Bare seeking is not drug-specific |
| brain/accumbens | `core`, `shell`, `acbc`, `acbs`, `NacSh` | `accumbens core`, `accumbens shell`, `nucleus accumbens core`, `nucleus accumbens shell`, `core of the nucleus accumbens`, `shell of the nucleus accumbens`, `NAc`, `NAcC`, `NAcSh`, `Nacc` | Core and shell are ordinary words and were matching unrelated phrases |
| brain/amygdala | `amy`, `bla`, `cea`, `cna` | `basolateral amygdala`, `central amygdala`, `central nucleus of the amygdala`, `medial amygdala`, `medial nucleus of the amygdala`, `basomedial amygdala`, `cortical amygdala`, `lateral amygdala` | BLA also means beta-lactamase; CEA also means carcinoembryonic antigen |
| brain/cortex | `cortex`, `cerebral`, `prl`, `pfc`, `vmpfc` | `cerebral cortex`, `prefrontal cortex`, `PFC`, `vmPFC`, `prelimbic cortex`, `anterior cingulate cortex`, `insular cortex`, `orbitofrontal cortex` | Cortex alone matches kidney and adrenal cortex; PRL encodes prolactin |
| brain/habenula | `lhb`, `mhb` | `lateral habenula`, `medial habenula`, `LHb`, `MHb` | Abbreviations retained together with their expanded names |
| brain/hippocampus | `hip`, `hipp`, `dhpc`, `vhipp`, `vhpc` | `hippocampus`, `hippocampal`, `dorsal hippocampus`, `ventral hippocampus` | HIP is also a gene symbol and hip is a joint |
| brain/hypothalamus | none removed | `lateral hypothalamic area`, `arcuate nucleus`, `ventromedial hypothalamus`, `dorsomedial hypothalamus`, `paraventricular nucleus of the hypothalamus` | Nuclei were unnamed or ambiguous |
| brain/striatum | `basal ganglia`, `globus pallidus`, `GPI`, `STR` | Moved to `brain/basal ganglia` and `brain/pallidum`; striatum keeps `striatum`, `striatal`, `caudate`, `putamen`, `neostriatum`, `dorsal striatum`, `ventral striatum` | Globus pallidus is not striatum; GPI also means glucose-6-phosphate isomerase; STR also means short tandem repeat |
| brain/VTA | `limbic`, `mesolimbic`, `mesoaccumbal`, `mesoaccumbens`, `midbrain`, `pvta`, `vta` | `ventral tegmental area`, `VTA`, `anterior|posterior ventral tegmental area`, plus the new `brain/mesolimbic pathway`, `brain/limbic system` and `brain/midbrain` | Circuit and region names are not VTA synonyms |
| function/neuroplasticity | `IPSC`, `IPSP`, `epsc`, `epsp`, `mIPSC`, `plasticity` | `excitatory postsynaptic current|potential`, `miniature excitatory|inhibitory postsynaptic current`, `synaptic plasticity`, `structural plasticity` | IPSC collides with induced pluripotent stem cells; bare plasticity is not defined |
| function/neurotransmission | `5 ht` | `5-HT` | Punctuation-normalized abbreviation |
| function/signalling | `binding` | `receptor binding`, `binding affinity`, `binding site` | Bare binding matched unrelated molecular contexts |
| psychiatric/impulsivity | `5 choice task`, `5 CSRTT`, `delay task`, `delay exposure`, `delay intolerance` | `five choice serial reaction time task`, `delay discounting`, `intertemporal choice`, `response inhibition`, `stop signal task`, `go no-go task` | Task labels rather than measured constructs |
| function/transcription | whole concept | `function/expression` | Ribosomes concern translation, not transcription |

## Corrected biological relationships

- Globus pallidus, substantia nigra and subthalamic nucleus no longer sit under striatum. They are in `brain/pallidum` and `brain/basal ganglia`.
- Mesolimbic, mesoaccumbal and mesocorticolimbic terms are circuit names, so they moved from `brain/VTA` to `brain/mesolimbic pathway`.
- `limbic` and `midbrain` are broad regions, so they moved from `brain/VTA` to their own concepts.
- `function/transcription` became `function/expression`, covering transcription, translation, epigenetic marks and mRNA.
- Inhibitory and excitatory postsynaptic currents and potentials are written out instead of using IPSC/IPSP abbreviations. These remain measurement terms within the neuroplasticity retrieval lane; the flat keyword list does not distinguish measurements from demonstrated plasticity. Screening must make that distinction.
- Bare `plasticity` was replaced by `synaptic plasticity` and `structural plasticity`.

`addiction/reward`, `addiction/relapse` and `addiction/intoxication` still combine related constructs. The audit recommended splitting them. They were kept as retrieval lanes because the structure was not part of this revision, and screening assigns `concept_support` and `direction_target` per abstract.

## Coverage terms added

- Singular and plural forms for every cell type, for example `neuron` and `neurons`, `astrocyte` and `astrocytes`, and all 41 plural neuron labels. `cell/neuron` now has 83 terms.
- Missing singulars elsewhere: `opioid`, `opiate`, `opiates`, `cannabinoid`, `benzodiazepines`, `neuropeptide`, `smoker`, `neurotransmitter`, `catecholamine`, `posttraumatic stress disorder`.
- Stress biology: `acute stress`, `chronic stress`, `chronic unpredictable stress`, `chronic mild stress`, `restraint stress`, `social defeat stress`, `early life stress`, `maternal separation`, `footshock`, `corticosterone`, `cortisol`, `glucocorticoid`, `HPA axis`, `hypothalamic pituitary adrenal axis`, `stress reactivity`, `stress resilience`, `stress susceptibility`.
- Neurotransmission: `norepinephrine`, `noradrenaline`, `noradrenergic`, `catecholamines`, `dopamine transporter`, `serotonin transporter`, `neurotransmitter release`.
- Plasticity: `dendritic spine`, `dendritic spines`, `spine density`.
- Reward and aversion: `conditioned place aversion`, `place aversion`, `brain stimulation reward`, `progressive ratio`, `drug reward`, `reward seeking`.
- Relapse: `cue-induced reinstatement`, `drug-primed reinstatement`, `drug-induced reinstatement`, `stress-induced reinstatement`, `incubation of drug craving`.
- Nicotine and tobacco: `cigarette`, `cigarettes`, `e-cigarette`, `electronic cigarette`, `vaping`, `smokeless tobacco`, `nicotine dependence`.
- Psychiatric: `psychosis`, `anxiety-like`, `elevated plus maze`, `autism spectrum disorder`, `mania`, `antidepressant`, `obsessive compulsive disorder`, `compulsivity`, `intertemporal choice`, `response inhibition`.
- Substance use: `substance use disorder`, `substance use disorders`, `drug dependence`, `alcohol use disorder`, `alcohol drinking`, `crack cocaine`.

Bare `bipolar` was added back to `psychiatric/bipolar` for coverage. Titles and abstracts that use the adjective usually concern the disorder, and screening can reject the remainder.

## GWAS

The four GWAS concepts were removed. Their terms described traits, disorders and substances rather than study design, and `GWAS/nicotine` included `chronic obstructive`. Two unique terms were kept elsewhere: `drug dependence` moved to `addiction/addiction`, and `chronic obstructive` was dropped as not a synonym for nicotine.

Gene-trait association evidence is collected separately through the GWAS Catalog MCP lane, described in [associations](../references/associations.md). A keyword match does not establish GWAS evidence, a causal gene or an effect direction. A curated Catalog association is a reported effect estimate for one variant, not a gene-level causal claim.

## Effect on retrieval

The default search includes all 50 ontology concepts plus one direct phenotype query per gene. For gene g with H_g function-prioritized concepts, the maximum selected memberships are `200 × H_g + 30 × (50 − H_g + 1)`. With five genes there are 255 queries; the membership ceiling depends on each gene's documented function and selected high-priority concepts. Overlapping PMIDs make unique record counts smaller than membership counts.

Vocabulary changes can affect specificity and recall in both directions. Full phrases may retrieve records that abbreviations miss, including papers that never used the abbreviation. The search subsets omit phrases only when the reviewed lexical check identifies a retained same-concept anchor; identical PubMed coverage has not been verified. Dropping a colliding abbreviation can miss records that used only that abbreviation, such as `IPSC` for the postsynaptic current. Every query length still needs inspection of the PubMed translation and any quoted-phrase warnings before a pilot is interpreted.

## Verification and remaining work

`normalize_ontology` loads the curated file, concept IDs are unique and `or_query` accepts every term. The original literal still contains 47 concepts and 348 distinct terms, so the existing preservation test continues to pass unchanged.

Not established: retrieval precision or recall, behavior of each quoted phrase in PubMed, and whether the added broad concepts improve or dilute phenotype-relevant screening. A pilot should compare legacy and curated vocabularies on known relevant, null and near-miss papers before the counts are treated as coverage.
