# Search terms and interpretation vocabulary

## One source, two roles

The canonical vocabulary is `resources/addiction_ontology.json`. Each concept has:

- `terms`: the complete vocabulary for screening and interpretation. Entries can be synonyms, anatomical subregions, cell types, assays or related constructs; they are not necessarily interchangeable.
- Optional `search_terms`: the explicit subset included in the PubMed query. It must be a nonempty list drawn from that concept's `terms`.

If `search_terms` is absent, the coordinator searches all `terms`, as before. An empty or invalid subset is an error, not a request to fall back silently. The direct gene-phenotype lane continues to use the approved context's `phenotype_terms`.

The active resource uses explicit subsets for 39 concepts. The other 11 concepts use all their terms. It retains 611 term occurrences, including the user-added `conditioned odor aversion`, and 610 distinct terms. The effective search vocabulary contains 402 occurrences and 401 distinct terms. Thus 209 entries remain available for interpretation without being separate query alternatives. No concept or full-vocabulary term was removed.

## Example

The accumbens concept searches its broader words and distinct abbreviations while retaining core/shell phrases for interpretation:

```json
{
  "category": "brain",
  "id": "brain/accumbens",
  "name": "accumbens",
  "search_terms": ["accumbal", "accumbens", "AcbC", "AcbS", "NAc", "NAcC", "NAcSh"],
  "terms": [
    "accumbal",
    "accumbens",
    "accumbens core",
    "accumbens shell",
    "AcbC",
    "AcbS",
    "core of the nucleus accumbens",
    "NAc",
    "NAcC",
    "NAcSh",
    "Nacc",
    "nucleus accumbens",
    "nucleus accumbens core",
    "nucleus accumbens shell",
    "shell of the nucleus accumbens"
  ]
}
```

`Nacc` remains in the full vocabulary but is omitted from the search subset because its case-insensitive spelling matches retained `NAcC`. This is a retrieval equivalence, not a claim that the anatomical meanings of those abbreviations are identical.

The aversion query uses `aversion` and `aversive`. Conditioned odor, taste and place aversion remain distinct assay descriptions in `terms`. Searching a general aversion term does not establish which assay a paper used.

## How the subsets were selected

Within each concept, a case-insensitive containment check proposed longer phrases that included a shorter retained term. Word boundaries prevented removal based on a fragment inside another word. Hyphen boundaries were treated conservatively: `e-cigarette` was retained alongside `cigarette`, and `anxiety-like` alongside `anxiety`. Singular and plural forms were not collapsed. Spelling variants, distinct abbreviations and separate drug names were retained unless the same-concept containment check supplied a retained anchor.

The parent reviewed those proposals before writing explicit subsets. The query compiler does not repeat this reduction at runtime. For example, `neuron` does not remove `interneuron`, and `amphetamine` does not remove `methamphetamine`. Terms are never removed because a related term appears in another concept.

This is a lexical reduction, not proof of identical PubMed result sets. Quoted phrases, translation rules and phrase-index warnings can affect retrieval. Inspect saved query translations and compare relevant known papers before claiming unchanged coverage. The existing broad terms and newest-abstract caps remain; shorter queries do not solve their selection bias.

## Screening and follow-up

Worker manifests carry the full concept, including both fields when a subset is specified. The canonical screener uses `terms` to recognize reported details and records them in `finding`, `tissue_or_cell` and `model` when supported by the abstract. It must not infer a subtype from the vocabulary alone.

Follow-up packets include a `concepts` list drawn from the workspace's frozen query plan, filtered by the requested gene and concept when supplied. Synthesis therefore has the same full vocabulary used for screening, not just the shortened query terms. Read the original sources and retain reported specificity with supporting passages; a vocabulary entry is not evidence.

## Maintenance and existing workspaces

When adding a keyword:

1. Add it to the concept's `terms` if it is useful for interpretation.
2. If the concept has `search_terms`, add it there too only if it should be a separate retrieval alternative. A new abbreviation, spelling variant or independent drug name may require this.
3. If the concept lacks `search_terms`, new `terms` entries automatically enter its queries. Add an explicit subset if some entries should be interpretation-only.
4. Revalidate the vocabulary and inspect the generated queries before live retrieval.

Both fields and the exact query plan are frozen in each research workspace. Existing workspaces are not migrated or reduced automatically. Changing either field for an initialized workspace requires a separate workspace, even when the resulting query text would be unchanged. The optional field is backward-compatible within schema version 1; the original literal and normalized legacy resource remain unchanged.

The canonical screener rubric also records the two roles. Job manifests retain its checksum. Refresh an installed worker copy using the [runbook](runbook.md) before production screening; do not overwrite old job manifests or imported assessments.
