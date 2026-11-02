<p align="center"><img src="assets/wasp-lib.jpg" alt="wasp-lit badge" width="200"></p>

# wasp-lit

Post-GWAS literature analysis: after a GWAS (or similar study) nominates candidate genes, evaluate how plausibly each gene relates to the phenotype. It searches PubMed for each gene against the phenotype and a GeneCup-style keyword ontology, screens the abstracts with read-only subagents, adds curated GWAS Catalog associations, and keeps a persistent, PMID-linked corpus for later questions. For general literature reviews, use `honeybee-lit`.

Part of a four-skill research suite: `beaver-data` (analysis), `weaver-text` (editing support for author-written text), `honeybee-lit` (general literature reviews), and `wasp-lit` (post-GWAS candidate gene-phenotype literature analysis).

**Version `0.4.0`.** Adapted from [GeneCup](https://github.com/hakangunturkun/GeneCup).

## Why a wasp?

A paper wasp builds its nest one cell at a time and returns to extend the same structure. `wasp-lit` builds its corpus the same way: one record per PMID, added in durable layers that later runs reuse rather than rebuild.

## Reproducibility and standardization

- **Frozen scope.** Approved context, ontology, and exact queries are frozen per workspace. A vocabulary change requires a new workspace.
- **Fixed sampling rules.** Every ontology concept and a direct gene × phenotype query are searched. Caps are 200 abstracts for function-prioritized concepts and 30 for all others, applied per gene and concept to the newest records after full PMID enumeration.
- **Complete provenance.** Raw XML responses, query translations, all discovered PMIDs, timestamps, and checksums are saved before screening. Source responses are immutable.
- **Resumable runs.** Repeating a run ID resumes it; `--refresh` with a new run ID updates sources while keeping earlier responses.
- **Standard screening packets.** Each worker gets one gene × one concept, a fixed screener rubric, and read-only tools. Outputs are validated for PMIDs, counts, enums, record hashes, and quotation fidelity before import.
- **Hash-locked evidence.** Each assessment stores the record hash it was screened against, so old evidence resolves to the exact abstract it used.
- **Separate GWAS lane.** Curated GWAS Catalog associations are recorded for every eligible human gene, separate from PubMed screening.
- **Distinct failure states.** Missing abstracts, failed requests, and empty searches are recorded as different states. A failed search is never reported as zero evidence.

## What it does

1. Collect NCBI Gene and WikiGenes function context for each gene and prioritize concepts.
2. Freeze the context and query plan (`init`, `plan-search`).
3. Enumerate PMIDs and retrieve capped abstracts (`collect`).
4. Screen retrieved abstracts with Jev structured classification (`triage`, `triage-report`); generate bounded `concept-screener` subagent jobs (`jobs`) only if unresolved `needs_review` items remain or Jev is unavailable.
5. Run the GWAS Catalog lane (`phenotype-search`, `associations`) and retrieve accessible full texts within the run quota (`fulltext`).
6. Write a PMID-cited candidate-plausibility synthesis that keeps association, perturbation, mechanism, and species transfer distinct.
7. Reopen the saved sources in later conversations (`packet`, `status`).

Genes are never ranked by publication counts, and no numerical causal scores are produced.

## Package contents

```text
wasp-lit/
├── SKILL.md              # Agent instructions
├── README.md
├── LICENSE
├── assets/wasp-lib.jpg
├── agents/               # concept-screener subagent definition
├── references/           # Workflow, search, screening, full-text, corpus, and runbook guides
├── resources/            # Curated addiction keyword ontology (current and legacy)
├── scripts/              # wasp.py CLI, core library, PubMed, WikiGenes, GWAS Catalog, Jev triage, and OKF export helpers
├── templates/            # Context example, search record, concept domains, synthesis
├── synthesis_prompt.txt  # Candidate-gene synthesis prompt
├── addiction_ontology.json # Original GeneCup ontology (unchanged; checked by tests)
├── plan/                 # Ontology curation record
└── tests/                # Unit tests and fixtures
```

## Project workspace

Create one top-level folder per search named `wasp-lit-<gene>-<phenotype>/` (or `wasp-lit-<genes>-<phenotype>/`). Human-facing deliverables live at the top level as portable Markdown files, while all machine JSON/JSONL tables and immutable source responses live inside `corpus/` (existing legacy workspaces under `references/wasp/` remain supported):

```text
wasp-lit-<gene>-<phenotype>/
├── README.md                  # Run status, corpus counts, and guide to top-level Markdown files
├── synthesis.md               # Narrative candidate-gene plausibility synthesis
├── human-decisions.md         # Human-approved scope, concept caps, and manual overrides
├── ai-decisions.md            # AI concept-cap rationale, Jev triage summary, and subagent screening ledger
├── gene-function.md           # Baseline gene/protein biology (or gene-function/<GENE>.md for multi-gene runs)
├── gwas-associations.md       # Human-readable GWAS Catalog summary table
├── okf/                       # Google Open Knowledge Format concept documents for screened-in references
│   ├── index.md               # Progressive disclosure catalog of references passing screening
│   └── <PMID>.md              # Self-describing reference concept documents (YAML frontmatter + abstract + evidence)
└── corpus/                    # Machine state and immutable source cache
    ├── manifest.json, context.json, ontology.json, queries.json
    ├── overview.json, audit.json
    ├── articles.jsonl, membership.jsonl, evidence.jsonl, triage.jsonl, fulltexts.jsonl
    ├── human_decisions.jsonl, associations.jsonl, association_evidence.jsonl
    ├── gene-function/         # Raw JSON extracts from NCBI Gene, WikiGenes, UniProt, Ensembl, GTEx
    ├── runs/, jobs/, waves/, assessments/
    └── sources/
```

See [corpus and resume](references/corpus-and-resume.md).

## Companion skills

| Skill | Role |
|---|---|
| [`beaver-data`](https://github.com/chen42/beaver-data) | Approved statistical analysis, including quantitative evidence synthesis. |
| [`weaver-text`](https://github.com/chen42/weaver-text) | AI editing, review, and submission help for author-written manuscripts and grant proposals. |
| [`honeybee-lit`](https://github.com/chen42/honeybee-lit) | General literature reviews, from citation checks to narrative, scoping, and systematic reviews. |
| [`wasp-lit`](https://github.com/chen42/wasp-lit) | Post-GWAS literature analysis of candidate gene-phenotype relationships. |

Synthesis follows `weaver-text` citation and source-capture guidance.

## Installation

Clone the repository, unchanged, into a skills directory your agent harness scans:

```bash
# Shared cross-harness skills directory (Antigravity, Codex, OpenCode)
git clone https://github.com/chen42/wasp-lit.git ~/.agents/skills/wasp-lit

# Pi
git clone https://github.com/chen42/wasp-lit.git ~/.pi/agent/skills/wasp-lit

# Claude Code
git clone https://github.com/chen42/wasp-lit.git ~/.claude/skills/wasp-lit
```

In Pi, run `/reload` after cloning, or list the path under `"skills"` in `~/.pi/agent/settings.json`.

Requirements: Live retrieval requires the installed `pubmed-database` skill, NCBI credentials, and `uv`; screening uses `pi-subagents` in Pi or the host harness's native subagent tool (`jobs-index.json` and `evidence-record`). Optional Jev triage (`wasp.py triage`) runs directly in Python over HTTP or from saved captures. Offline commands need only the Python standard library.

Verify the installation from the skill directory:

```bash
cd ~/.agents/skills/wasp-lit  # or your install path
python3 scripts/wasp.py doctor
python3 -m unittest discover -s tests -v
```

Full commands are in the [runbook](references/runbook.md).

## License

[MIT](LICENSE)
