"""Export screened literature references and focused concept mini-reviews into Google Open Knowledge Format (OKF).

Conforms to the Google Cloud Open Knowledge Format specification:
https://github.com/GoogleCloudPlatform/open-knowledge-format

Architecture:
1. Strict inclusion: Only references confirmed 'include' by concept-screener subagents
   (in corpus/evidence.jsonl) or explicit human override (in corpus/human_decisions.jsonl).
2. Two-tier knowledge network under `okf/`:
   - Tier 1: Focused Concept Mini-Reviews (`okf/concepts/<category>--<slug>.md`, type: Concept)
     for each active ontology concept and for Emerging Topics (`category: emerging`) that arise
     from cross-domain synthesis or explicit topic definitions.
   - Tier 2: Atomic Reference Notes (`okf/<PMID>.md`, type: Reference) with bibliographic
     YAML frontmatter, structured screening assessments, verbatim quotations, and backlinks
     to Concept Mini-Reviews and related references.
   - Progressive Disclosure Catalog (`okf/index.md`, type: Index) organized by the top-level
     ontology categories plus the Emerging Topics category.
   - Cytoscape graph specification (`corpus/okf_graph.json`) for interactive Obsidian-style
     visualization and side-panel note inspection in the HTML report.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import datetime
import json
from pathlib import Path
import re
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


CATEGORY_ORDER = [
    "phenotype",
    "drug",
    "addiction",
    "brain",
    "function",
    "cell",
    "stress",
    "psychiatric",
    "emerging",
]

CATEGORY_TITLES = {
    "phenotype": "Phenotype Lane (Direct Association)",
    "drug": "Substances and Pharmacological Agents",
    "addiction": "Addiction and Operant Behavior",
    "brain": "Neuroanatomy and Neural Circuitry",
    "function": "Channel Biophysics and Signaling Pathways",
    "cell": "Cellular Populations and Subtypes",
    "stress": "Stress and Neuroendocrine Reactivity",
    "psychiatric": "Psychiatric and Behavioral Comorbidities",
    "emerging": "Emerging Topics and Cross-Domain Themes",
}

CATEGORY_COLORS = {
    "phenotype": "#ebcb8b",
    "drug": "#88c0d0",
    "addiction": "#bf616a",
    "brain": "#b48ead",
    "function": "#a3be8c",
    "cell": "#d08770",
    "stress": "#5e81ac",
    "psychiatric": "#8fbcbb",
    "emerging": "#ff79c6",
    "gene": "#ffffff",
    "pmid": "#81a1c1",
}


def _format_yaml_scalar(val: Any) -> str:
    """Safely format a scalar value for YAML without external dependencies."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if not s:
        return '""'
    needs_quotes = (
        "\n" in s
        or ":" in s
        or "#" in s
        or s.strip() != s
        or s.startswith(("-", "[", "{", "*", "&", "!", "?", "%", "@", "`", '"', "'"))
        or s.lower() in ("true", "false", "yes", "no", "null", "none")
    )
    if needs_quotes:
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _dump_yaml_custom(data: Any, indent_level: int = 0) -> list[str]:
    """Pure-Python YAML serialization fallback for dictionaries and lists."""
    lines: list[str] = []
    prefix = "  " * indent_level

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                if not v:
                    lines.append(f"{prefix}{k}: {{}}")
                else:
                    lines.append(f"{prefix}{k}:")
                    lines.extend(_dump_yaml_custom(v, indent_level + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{prefix}{k}: []")
                else:
                    lines.append(f"{prefix}{k}:")
                    for item in v:
                        if isinstance(item, (dict, list)):
                            sub_lines = _dump_yaml_custom(item, indent_level + 2)
                            if sub_lines:
                                first = sub_lines[0].lstrip()
                                lines.append(f"{prefix}  - {first}")
                                lines.extend(sub_lines[1:])
                        else:
                            lines.append(f"{prefix}  - {_format_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{k}: {_format_yaml_scalar(v)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                sub_lines = _dump_yaml_custom(item, indent_level + 1)
                if sub_lines:
                    first = sub_lines[0].lstrip()
                    lines.append(f"{prefix}- {first}")
                    lines.extend(sub_lines[1:])
            else:
                lines.append(f"{prefix}- {_format_yaml_scalar(item)}")
    return lines


def to_yaml_frontmatter(metadata: dict[str, Any]) -> str:
    """Format dictionary into valid YAML frontmatter delimited by ---."""
    if yaml is not None:
        try:
            dumped = yaml.safe_dump(
                metadata,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
            return f"---\n{dumped}---\n"
        except Exception:
            pass
    lines = ["---"]
    lines.extend(_dump_yaml_custom(metadata, indent_level=0))
    lines.append("---")
    return "\n".join(lines) + "\n"


def _clean_text_for_cell(text: Any) -> str:
    """Clean string for use inside Markdown tables without raw pipes or newlines."""
    if text is None:
        return "none"
    s = str(text).replace("|", "\\|").replace("\n", " ").strip()
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", s) or "none"


def _sanitize_prose(text: str) -> str:
    """Ensure no em dashes or en dashes appear in generated prose."""
    return text.replace("\u2014", "-").replace("\u2013", "-")


def _clean_finding_text(text: Any, concept_id: str = "") -> str:
    """Strip structured-abstract headers and boilerplate disclaimers from extracted findings."""
    if text is None:
        return ""
    s = _sanitize_prose(str(text).strip())
    if not s:
        return ""
    # Strip leading structured abstract section headers (e.g. OBJECTIVE:, BACKGROUND AND OBJECTIVES:, RESULTS:)
    s = re.sub(
        r"^(?:BACKGROUND\s+AND\s+OBJECTIVES?|OBJECTIVES?|BACKGROUND|INTRODUCTION|AIMS?|PURPOSE|METHODS?|RESULTS?|CONCLUSIONS?|SIGNIFICANCE|IMPORTANCE|FINDINGS?)\s*:\s*",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()
    cid_lower = str(concept_id or "").strip().lower()
    if cid_lower != "drug/nicotine":
        s = re.sub(r";\s*[^;]*\b(?:nicotine|tobacco)\b[^.]*\.?$", ".", s, flags=re.IGNORECASE)
        s = re.sub(
            r",?\s*(?:and\s+|or\s+)?(?:without|with\s+no)\s+[^,;.]*\b(?:nicotine|tobacco)\b[^.]*\.?$",
            ".",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\s+(?:and|or)\s+(?:studying|assessing|testing|evaluating|examining|reporting|no)\s+nicotine\s+self-administration(?:\s+\w+)?\.?$",
            ".",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r",\s*(?:while|although|whereas|though|unrelated\s+to)\s+[^,;.]*\b(?:nicotine|tobacco)\b[^.]*\.?$",
            ".",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\.\s*No\s+[^.]*\b(?:nicotine|tobacco)\b[^.]*\.?$", ".", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*\([^)]*\b(?:nicotine|tobacco)\b[^)]*\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r";\s*background\s+review\s+only[^.]*\.?$", ".", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _classify_study_design(
    raw_design: str,
    finding: str,
    model: str = "",
    tissue: str = "",
    species_list: list[str] | None = None,
) -> str:
    """Classify study design with granular human study subtypes instead of lumping all human studies into GWAS."""
    rd = str(raw_design or "").strip().lower()
    blob = f"{finding} {model} {tissue}".lower()
    sp = species_list or []
    is_human = "human" in sp or rd in ("human_association", "gwas_locus")

    if rd == "review" or re.search(r"^(?:review|perspective|overview)\b", blob):
        return "review"

    if is_human:
        has_gwas = bool(
            rd == "gwas_locus"
            or re.search(
                r"\b(gwas|genome-wide\s+association|phewas|exwas|twas|transcriptome-wide\s+association|mendelian\s+randomization|genomic\s+sem|polygenic\s+risk|prs)\b",
                blob,
            )
        )
        has_genetic_variant = bool(
            re.search(
                r"\b(rs\d+|polymorphism|snp|risk\s+allele|minor\s+allele|genotype|genotyped|haplotype|vntr|epistasis|missense|nonsense|c\.\d+|p\.[a-z]+\d+|timothy\s+syndrome|heterozygous|de\s+novo|rare\s+deleterious\s+variants|susceptibility\s+loci|introns?\s+\d+)\b",
                blob,
            )
        )
        has_neuroimaging = bool(
            re.search(
                r"\b(fmri|structural\s+mri|\bmri\b|bold|dti|diffusion\s+tensor|pet\b|meg\b|eeg\b|cortical\s+thickness|cortical\s+surface|gray\s+matter|grey\s+matter|white\s+matter|amygdala\s+volume|globus\s+pallidus.*volume|functional\s+connectivity)\b",
                blob,
            )
        )
        has_clinical_trial_or_intervention = bool(
            re.search(
                r"\b(clinical\s+trial|randomized|placebo|double-blind|deep\s+brain\s+stimulation|gpi-dbs|\bdbs\b|lithium\s+response|antidepressant\s+response)\b",
                blob,
            )
        )
        has_epigenetic_or_tissue_omics = bool(
            re.search(
                r"\b(dna\s+methylation|methylation|methylome|cpg|ewas|hypomethylat\w+|hypermethylat\w+|eccdna|extrachromosomal\s+circular\s+dna|postmortem|placenta\w*|liver\s+tissue|cirrhosis|biopsy|tcga|rna-seq|transcriptom\w+|gene\s+set\s+enrichment|gsea|ipsc|pluripotent\s+stem\s+cell|organoid|surgically\s+resected)\b",
                blob,
            )
        )

        if has_gwas:
            return "human_gwas_polygenic"
        if has_genetic_variant and has_neuroimaging:
            return "human_imaging_genetics"
        if has_genetic_variant:
            return "human_candidate_variant"
        if has_clinical_trial_or_intervention:
            return "human_clinical_intervention"
        if has_epigenetic_or_tissue_omics:
            return "human_tissue_epigenetics_transcriptomics"
        if has_neuroimaging:
            return "human_clinical_neuroimaging"
        return "human_observational_cohort"

    if not rd or rd in ("unspecified", "unclear"):
        return "experimental_study"
    return rd


SPECIES_PRIORITY = [
    "human",
    "rat",
    "mouse",
    "macaque",
    "zebrafish",
]


def parse_canonical_species(raw: Any) -> list[str]:
    """Parse a raw species string into canonical lowercase common names (human, rat, mouse, macaque, zebrafish)."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        for item in raw:
            for sp in parse_canonical_species(item):
                if sp not in out:
                    out.append(sp)
        return out
    s = str(raw).strip().lower()
    if not s or s in ("none", "n/a", "unspecified", "not recorded", "null", "unknown"):
        return []
    found: list[str] = []
    if re.search(r"\b(homo\s+sapiens|humans?)\b", s):
        found.append("human")
    if re.search(r"\b(rattus\s+norvegicus|rats?)\b", s):
        found.append("rat")
    if re.search(r"\b(mus\s+musculus|mice|mouse)\b", s):
        found.append("mouse")
    if re.search(r"\b(macaca(\s+mulatta)?|macaques?|rhesus(\s+macaques?|\s+monkeys?)?|non-?human\s+primates?)\b", s):
        found.append("macaque")
    if re.search(r"\b(danio\s+rerio|zebrafish)\b", s):
        found.append("zebrafish")
    if not any(x in found for x in ("rat", "mouse")) and re.search(r"\brodents?\b", s):
        found.extend(["rat", "mouse"])
    if "macaque" not in found and "human" not in found and re.search(r"\bprimates?\b", s):
        found.append("macaque")
    return found


def summarize_species_counts(assessments: list[dict[str, Any]]) -> dict[str, int]:
    """Count distinct PMIDs per canonical species across a list of assessments."""
    sp_to_pmids: dict[str, set[str]] = defaultdict(set)
    for a in assessments:
        pmid = str(a.get("pmid") or "").strip()
        if not pmid:
            continue
        for sp in parse_canonical_species(a.get("species")):
            sp_to_pmids[sp].add(pmid)
    ordered: dict[str, int] = {}
    for sp in SPECIES_PRIORITY:
        if sp in sp_to_pmids and len(sp_to_pmids[sp]) > 0:
            ordered[sp] = len(sp_to_pmids[sp])
    for sp in sorted(sp_to_pmids.keys()):
        if sp not in ordered and len(sp_to_pmids[sp]) > 0:
            ordered[sp] = len(sp_to_pmids[sp])
    return ordered


def format_species_counts(assessments: list[dict[str, Any]]) -> str:
    """Format canonical species counts as 'human (2), rat (1), mouse (1)' for tables and summaries."""
    counts = summarize_species_counts(assessments)
    if not counts:
        return "unspecified"
    return ", ".join(f"{sp} ({cnt})" for sp, cnt in counts.items() if cnt > 0)



def concept_id_to_slug(concept_id: str) -> str:
    """Convert a concept_id like 'drug/nicotine' or 'emerging/calcium_plasticity' to a safe filename slug."""
    cleaned = re.sub(r"[^A-Za-z0-9/_-]+", "-", str(concept_id).strip()).strip("-/")
    if "/" in cleaned:
        parts = [p for p in cleaned.split("/") if p]
        return "--".join(parts).lower()
    return f"concept--{cleaned.lower()}" if cleaned else "concept--general"


def parse_concept_category_and_name(concept_id: str) -> tuple[str, str]:
    """Return (category, short_name) for a concept_id."""
    cid = str(concept_id or "").strip()
    if "/" in cid:
        cat, name = cid.split("/", 1)
        cat_lower = cat.lower().strip()
        if cat_lower not in CATEGORY_TITLES:
            return "emerging", name.strip() or cid
        return cat_lower, name.strip()
    if cid.lower() in ("phenotype", "direct"):
        return "phenotype", "direct"
    if cid.lower() in CATEGORY_TITLES:
        return cid.lower(), "general"
    return "emerging", cid or "emerging-topic"


def is_okf_confirmed(store: Any) -> bool:
    """Check whether human confirmation has been recorded for OKF generation."""
    for hd in store.table("human_decisions"):
        stage = str(hd.get("stage") or "").strip().lower()
        dec = str(hd.get("decision") or "").strip().lower()
        if stage in ("okf", "okf_export", "open_knowledge_format"):
            if any(tok in dec for tok in ("approve", "confirm", "include", "yes", "enable", "generate")):
                return True
    return False


def get_screened_in_records(store: Any) -> dict[str, list[dict[str, Any]]]:
    """Identify all PMIDs strictly confirmed 'include' by subagent screening or human override.

    Unverified raw Jev triage classifications are excluded unless confirmed by
    subagent evidence records or human adjudication.
    """
    evidence_rows = store.table("evidence")

    # Map (gene, concept_id, pmid, source_version) -> latest subagent assessment
    latest_map: dict[tuple, dict[str, Any]] = {}
    for item in evidence_rows:
        key = (
            item.get("gene", ""),
            item.get("concept_id", ""),
            str(item.get("pmid", "")),
            item.get("source_version"),
        )
        latest_map[key] = item

    # Group assessments for records where subagent decision is strictly 'include'
    included_by_pmid: dict[str, list[dict[str, Any]]] = {}
    for (_gene, _concept_id, pmid, _version), assessment in latest_map.items():
        if assessment.get("decision") == "include":
            included_by_pmid.setdefault(pmid, []).append(assessment)

    # Apply manual human overrides (inclusions or exclusions)
    context_genes = []
    if (store.base / "context.json").exists():
        try:
            from wasp_core import load
            ctx = load(store.base / "context.json")
            context_genes = [g["symbol"] for g in ctx.get("genes", []) if isinstance(g, dict) and g.get("symbol")]
        except Exception:
            pass
    default_gene = context_genes[0] if context_genes else "TargetGene"

    for hd in store.table("human_decisions"):
        stage = str(hd.get("stage") or "").strip().lower()
        dec = str(hd.get("decision") or "").strip().lower()
        if stage in ("screening_override", "screening_adjudication") or "pmid" in stage:
            if "exclude" in dec:
                for pmid_val in hd.get("pmids") or []:
                    pmid_str = str(pmid_val).strip()
                    included_by_pmid.pop(pmid_str, None)
            elif "include" in dec:
                for pmid_val in hd.get("pmids") or []:
                    pmid_str = str(pmid_val).strip()
                    if pmid_str and pmid_str not in included_by_pmid:
                        included_by_pmid[pmid_str] = [{
                            "pmid": pmid_str,
                            "gene": default_gene,
                            "concept_id": "phenotype/direct",
                            "decision": "include",
                            "species": "human",
                            "study_design": "Human adjudication override",
                            "direction": None,
                            "direction_target": None,
                            "finding": hd.get("rationale") or hd.get("decision", "Included by human adjudication."),
                            "quotation": None,
                            "reason": hd.get("rationale"),
                        }]

    return included_by_pmid


def record_emerging_topic(
    store: Any,
    topic_id: str,
    title: str,
    pmids: list[str],
    narrative: str,
    direction: str | None = None,
    species: list[str] | None = None,
) -> dict[str, Any]:
    """Record or update an emerging topic mini-review definition in corpus/emerging_topics.json."""
    topics_path = store.base / "emerging_topics.json"
    topics: list[dict[str, Any]] = []
    if topics_path.exists():
        try:
            topics = json.loads(topics_path.read_text(encoding="utf-8"))
            if not isinstance(topics, list):
                topics = []
        except Exception:
            topics = []

    clean_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", topic_id.replace("emerging/", "").strip()).strip("-").lower()
    full_id = f"emerging/{clean_slug}"
    clean_pmids = [str(p).strip() for p in pmids if str(p).strip()]

    entry = {
        "concept_id": full_id,
        "slug": f"emerging--{clean_slug}",
        "category": "emerging",
        "title": _sanitize_prose(title.strip()),
        "pmids": clean_pmids,
        "narrative": _sanitize_prose(narrative.strip()),
        "direction": direction,
        "species": species or [],
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    topics = [t for t in topics if t.get("concept_id") != full_id]
    topics.append(entry)
    topics_path.write_text(json.dumps(topics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry


def _discover_emerging_topics(
    store: Any,
    included_by_pmid: dict[str, list[dict[str, Any]]],
    articles_by_pmid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Load explicit emerging topics and auto-discover off-ontology higher-order emergent themes from screened evidence."""
    topics_by_id: dict[str, dict[str, Any]] = {}

    # 1. Load explicit agent/user-defined emerging topics from corpus/emerging_topics.json
    topics_path = store.base / "emerging_topics.json"
    if topics_path.exists():
        try:
            raw_list = json.loads(topics_path.read_text(encoding="utf-8"))
            if isinstance(raw_list, list):
                for item in raw_list:
                    cid = item.get("concept_id") or f"emerging/{item.get('id', 'topic')}"
                    if not cid.startswith("emerging/"):
                        cid = f"emerging/{cid}"
                    valid_pmids = [str(p) for p in (item.get("pmids") or []) if str(p) in included_by_pmid]
                    if not valid_pmids and included_by_pmid:
                        valid_pmids = [str(p) for p in (item.get("pmids") or [])]
                    topics_by_id[cid] = {
                        "concept_id": cid,
                        "slug": concept_id_to_slug(cid),
                        "category": "emerging",
                        "name": cid.split("/", 1)[-1],
                        "title": _sanitize_prose(item.get("title") or cid.split("/", 1)[-1].replace("-", " ").title()),
                        "pmids": sorted(set(valid_pmids), key=lambda x: int(x) if x.isdigit() else x),
                        "narrative": _sanitize_prose(item.get("narrative") or ""),
                        "is_emerging": True,
                        "source": "authored",
                    }
        except Exception:
            pass

    if not included_by_pmid:
        return list(topics_by_id.values())

    # 2. Check if any evidence assessments already used a non-standard category or 'emerging/...'
    for pmid, assessments in included_by_pmid.items():
        for a in assessments:
            cid = str(a.get("concept_id") or "")
            cat, short_name = parse_concept_category_and_name(cid)
            if cat == "emerging":
                norm_cid = f"emerging/{short_name}"
                if norm_cid not in topics_by_id:
                    topics_by_id[norm_cid] = {
                        "concept_id": norm_cid,
                        "slug": concept_id_to_slug(norm_cid),
                        "category": "emerging",
                        "name": short_name,
                        "title": short_name.replace("_", " ").replace("-", " ").title(),
                        "pmids": [],
                        "narrative": "",
                        "is_emerging": True,
                        "source": "screening",
                    }
                if pmid not in topics_by_id[norm_cid]["pmids"]:
                    topics_by_id[norm_cid]["pmids"].append(pmid)

    # 3. Auto-discover genuine off-ontology emergent themes when not already authored:
    #    Scan findings, quotations, models, and direction targets for untracked molecular entities,
    #    channel paralogs, auxiliary subunits, or cell-type/signaling effectors recurring across papers.
    off_ontology_patterns = [
        (
            "emerging/cav12-vs-cav13-isoform-dissociation",
            "CaV1.2 (CACNA1C) vs. Untracked Paralog CaV1.3 (CACNA1D) Functional Dissociation",
            re.compile(r"\b(cav1\.3|ca\(v\)1\.3|cacna1d)\b", re.IGNORECASE),
            "Higher-order synthesis of studies simultaneously measuring CACNA1C (CaV1.2) and the untracked L-type calcium channel paralog CACNA1D (CaV1.3), revealing isoform-specific dissociation across basal pacemaking versus burst firing and acute versus protracted drug withdrawal.",
        ),
        (
            "emerging/camkii-glua1-s831-darpp32-effector-cascade",
            "Postsynaptic CaMKII, GluA1 (Ser831), and DARPP-32 Effector Cascade",
            re.compile(r"\b(camkii\w*|camk2\w*|glua1|gria1|s831|ser831|darpp-32|ppp1r1b)\b", re.IGNORECASE),
            "Higher-order synthesis of studies identifying untracked postsynaptic signaling effectors (CaMKII, AMPA receptor subunit GluA1 Ser831 phosphorylation, and DARPP-32) coupled to CaV1.2 activation during drug sensitization, extinction, and synaptic plasticity.",
        ),
        (
            "emerging/cell-type-cre-circuit-dissociation",
            "Cell-Type Dissociation Across Untracked PV-Cre, D1R-Cre, and Forebrain Excitatory Drivers",
            re.compile(r"\b(pv\+|parvalbumin|cav1\.2-pv|cav1\.2-nex|d1-cacna1c|d1r-expressing|camkiialpha-cre)\b", re.IGNORECASE),
            "Higher-order synthesis of conditional genetic models targeting untracked neuronal subpopulations (parvalbumin interneurons, dopamine D1-receptor neurons, and Nex/CaMKIIalpha projection neurons), uncovering opposing effects on stress coping, excitation/inhibition balance, and conditioned drug behaviors.",
        ),
        (
            "emerging/auxiliary-subunits-and-trafficking-partners",
            "Co-Regulation with Untracked Auxiliary Subunits (CACNA2D1, CACNB2) and Trafficking Partners (DISC1, EZH2)",
            re.compile(r"\b(cacna2d\d*|cacnb\d*|alpha2delta|disc1|ezh2|alpha7-nachr|α7-nachr)\b", re.IGNORECASE),
            "Higher-order synthesis of studies reporting co-regulation or physical coupling between CACNA1C and untracked auxiliary voltage-gated calcium channel subunits (CACNA2D1, CACNB2), RNA-transport scaffolds (DISC1), epigenetic regulators (EZH2), or nicotinic receptor subtypes.",
        ),
    ]

    if not topics_by_id:
        for pat_cid, pat_title, pat_regex, pat_narrative in off_ontology_patterns:
            if pat_cid in topics_by_id:
                continue
            matched_pmids: set[str] = set()
            for pmid, assessments in included_by_pmid.items():
                for a in assessments:
                    blob = " ".join(
                        str(a.get(k) or "")
                        for k in ("finding", "quotation", "direction_target", "model", "tissue_or_cell")
                    )
                    if pat_regex.search(blob):
                        matched_pmids.add(pmid)
                        break
            if len(matched_pmids) >= 2:
                topics_by_id[pat_cid] = {
                    "concept_id": pat_cid,
                    "slug": concept_id_to_slug(pat_cid),
                    "category": "emerging",
                    "name": pat_cid.split("/", 1)[-1],
                    "title": pat_title,
                    "pmids": sorted(matched_pmids, key=lambda x: int(x) if x.isdigit() else x),
                    "narrative": pat_narrative,
                    "is_emerging": True,
                    "source": "auto-discovered",
                }

    # 4. Fallback for small workspaces/tests: if fewer than 2 emerging topics exist, check shared specific direction_targets
    if len(topics_by_id) < 2:
        target_to_pmids: dict[str, set[str]] = defaultdict(set)
        target_display: dict[str, str] = {}
        for pmid, assessments in included_by_pmid.items():
            for a in assessments:
                dt = str(a.get("direction_target") or "").strip()
                if dt and dt.lower() not in ("none", "n/a", "unspecified", "null"):
                    norm_dt = re.sub(r"[^a-z0-9]+", "-", dt.lower()).strip("-")
                    if len(norm_dt) >= 3:
                        target_to_pmids[norm_dt].add(pmid)
                        target_display.setdefault(norm_dt, dt)
        for norm_dt, pset in sorted(target_to_pmids.items(), key=lambda x: (-len(x[1]), x[0])):
            if len(pset) >= 2 or (not topics_by_id and len(pset) >= 1):
                cid = f"emerging/target-{norm_dt}"
                if cid not in topics_by_id:
                    label = target_display[norm_dt]
                    topics_by_id[cid] = {
                        "concept_id": cid,
                        "slug": concept_id_to_slug(cid),
                        "category": "emerging",
                        "name": f"target-{norm_dt}",
                        "title": f"Shared Downstream Readout: {label}",
                        "pmids": sorted(pset, key=lambda x: int(x) if x.isdigit() else x),
                        "narrative": (
                            f"Higher-order synthesis across studies measuring the untracked readout {label} "
                            "across distinct experimental paradigms."
                        ),
                        "is_emerging": True,
                        "source": "auto-discovered",
                    }
                    if len(topics_by_id) >= 2:
                        break

    return list(topics_by_id.values())


def _is_phenotype_arm(gene_val: Any) -> bool:
    """Return True when an assessment record belongs to the Phenotype Mechanism Arm (PHENOTYPE:...)."""
    return str(gene_val or "").strip().upper().startswith("PHENOTYPE:")


def _title_case_phenotype(phenotype_label: str) -> str:
    """Format phenotype label in clean title case (e.g., 'Nicotine Self-Administration', 'Opioid Use Disorder')."""
    raw = str(phenotype_label or "Phenotype").strip()
    if raw.upper().startswith("PHENOTYPE:"):
        raw = raw.split(":", 1)[1].strip()
    minor = {"of", "in", "and", "or", "the", "to", "for", "with", "on", "at", "by"}
    words = raw.split()
    out: list[str] = []
    for idx, w in enumerate(words):
        if "-" in w:
            parts = [p.upper() if p.upper() in ("PTSD", "OUD", "AUD", "SUD", "IV") else p.capitalize() for p in w.split("-")]
            out.append("-".join(parts))
        elif w.upper() in ("PTSD", "OUD", "AUD", "SUD", "ADHD", "OCD", "MDD"):
            out.append(w.upper())
        elif idx > 0 and w.lower() in minor:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out) or "Phenotype"


def _gene_display_label(gene_symbol: str) -> str:
    """Return gene symbol with primary protein alias where standard."""
    g = str(gene_symbol or "Gene").strip()
    gu = g.upper()
    if gu == "CACNA1C":
        return "CACNA1C (CaV1.2)"
    if gu == "FURIN":
        return "FURIN (PCSK3)"
    return g


def _infer_relationship_in_context(
    assessment: dict[str, Any],
    concept_title: str,
    category: str,
    primary_gene: str = "CACNA1C",
    phenotype_label: str = "nicotine self-administration",
) -> dict[str, str]:
    """Infer granular (group_key, rel_title, cause, effect_label, dir_key, consequence, context_summary) for an assessment."""
    raw_gene = str(assessment.get("gene") or primary_gene).strip()
    is_pheno = _is_phenotype_arm(raw_gene)
    gene = primary_gene if is_pheno else raw_gene
    gene_disp = _gene_display_label(gene)
    pheno_title = _title_case_phenotype(phenotype_label)
    cid = str(assessment.get("concept_id") or "").strip()
    finding = _clean_finding_text(assessment.get("finding"), cid)
    fl = finding.lower()
    raw_dir = str(assessment.get("direction") or "unclear").strip().lower()
    dt = _clean_finding_text(assessment.get("direction_target") or "", cid)
    if dt.lower() in ("none", "n/a", "unspecified", "null"):
        dt = ""
    raw_design = str(assessment.get("study_design") or "experimental study").strip().lower()
    model = _sanitize_prose(str(assessment.get("model") or assessment.get("model_or_paradigm") or "").strip())
    tissue = _sanitize_prose(str(assessment.get("tissue_or_cell") or assessment.get("anatomical_or_cellular_context") or "").strip())
    sp_list = parse_canonical_species(assessment.get("species"))
    sp_str = ", ".join(sp_list) if sp_list else (str(assessment.get("species") or "unspecified").strip())
    design = _classify_study_design(raw_design, finding, model, tissue, sp_list)

    # 1. Determine strict direction or non-directional relationship class
    if raw_dir == "increase":
        dir_key = "increase"
        effect_verb = "Increases"
        effect_badge = "Increase (`increase`)"
    elif raw_dir == "decrease":
        dir_key = "decrease"
        effect_verb = "Decreases"
        effect_badge = "Decrease (`decrease`)"
    elif raw_dir in ("none", "no_effect"):
        dir_key = "no_effect"
        effect_verb = "Does Not Alter"
        effect_badge = "No Significant Effect / Dissociation (`none`)"
    else:
        has_inc = bool(re.search(r"\b(increas\w+|up-?regulat\w+|elevat\w+|enhanc\w+|induc\w+|higher)\b", fl))
        has_dec = bool(re.search(r"\b(decreas\w+|down-?regulat\w+|reduc\w+|attenuat\w+|impair\w+|blunt\w+|lower|prevent\w+|abolish\w+)\b", fl))
        if has_inc and has_dec:
            dir_key = "biphasic_or_state_dependent"
            effect_verb = "State-Dependently Regulates"
            effect_badge = "Time- or State-Dependent Regulation (`state_dependent`)"
        elif has_inc and not has_dec:
            dir_key = "increase"
            effect_verb = "Increases"
            effect_badge = "Increase (`increase`)"
        elif has_dec and not has_inc:
            dir_key = "decrease"
            effect_verb = "Decreases"
            effect_badge = "Decrease (`decrease`)"
        elif design in ("human_gwas_polygenic", "human_candidate_variant", "human_imaging_genetics"):
            if re.search(r"\b(interact\w+|\*|\sx\s)\b", fl):
                dir_key = "gene_environment_interaction"
                effect_verb = "Interacts With Exposure to Modulate"
                effect_badge = "Gene-by-Environment / Epistatic Interaction (`interaction`)"
            else:
                dir_key = "genetic_association"
                effect_verb = "Associates With"
                effect_badge = "Human Genetic Association (`genetic_association`)"
        elif design in ("human_tissue_epigenetics_transcriptomics", "human_clinical_intervention", "human_clinical_neuroimaging", "human_observational_cohort"):
            dir_key = "clinical_or_molecular_association"
            effect_verb = "Alters" if re.search(r"\b(alter\w+|chang\w+|differentially\s+methylated|deregulat\w+|hypomethylat\w+|hypermethylat\w+)\b", fl) else "Associates With"
            effect_badge = "Human Clinical / Molecular Observation (`human_observation`)"
        elif design == "review":
            dir_key = "mechanistic_pathway_synthesis"
            effect_verb = "Regulates"
            effect_badge = "Mechanistic Pathway Role (`review_synthesis`)"
        else:
            dir_key = "functional_modulation"
            effect_verb = "Modulates"
            effect_badge = "Functional / Molecular Modulation (`modulation`)"

    dt_lower = dt.lower()
    combined_target_text = f"{dt_lower} {fl}"

    if is_pheno:
        # Phenotype Arm relationship classification
        is_pheno_outcome = bool(
            re.search(
                r"\b(self-administration|operant|intake|infusion\w*|reinstatement|relapse|seeking|conditioned place preference|\bcpp\b|opioid use disorder|\boud\b|overdose|abstinence|withdrawal|preference|consumption|reinforcement|motivation|breakpoint)\b",
                dt_lower or fl,
            )
            and re.search(r"\b(agonist|antagonist|block\w+|inhibit\w+|lesion|inactivat\w+|optogenetic|chemogenetic|knockdown|knockout|infusion|microinjection|administration|treatment|modul\w+|prescrib\w+|co-prescri\w+)\b", fl)
        )
        if is_pheno_outcome:
            if category == "drug":
                cause = f"{concept_title} Receptor and Pharmacological Modulation"
            elif category == "brain":
                cause = f"{concept_title} Circuit Activity and Synaptic Inputs"
            elif category == "function":
                cause = f"{concept_title} Intracellular Signaling and Synaptic Plasticity"
            elif category == "cell":
                cause = f"{concept_title} Neuronal and Glial Populations"
            elif category == "stress":
                cause = f"{concept_title} Stress and Neuroendocrine Signaling"
            else:
                cause = f"{concept_title} Circuit and Molecular Mechanisms"
            cause_bucket = f"pheno_modulator_{category}"
            consequence = f"{pheno_title}, Operant Reinforcement, and Relapse/Reinstatement"
            consequence_bucket = "pheno_operant_relapse"
            if dir_key not in ("increase", "decrease", "no_effect"):
                effect_verb = "State-Dependently Regulates"
        else:
            cause = f"{pheno_title} and Contingent Drug/Cue Exposure"
            cause_bucket = "pheno_exposure"
            if re.search(r"\b(glua1|glua2|ampa|nmda|glt-1|eaat2|glutamat\w+|ltp|ltd|spine|synaptic plasticity|mglur\w*)\b", combined_target_text):
                consequence = f"{concept_title} Glutamatergic Synaptic Plasticity, Receptor Trafficking, and Homeostasis"
                consequence_bucket = "pheno_glutamate_plasticity"
            elif re.search(r"\b(creb|erk\w*|camkii\w*|fos\b|c-fos|bdnf|probdnf|trkb|darpp-32|kinase|transcription\w*)\b", combined_target_text):
                consequence = f"{concept_title} Activity-Dependent Kinase and Transcriptional Signaling (CREB, ERK, CaMKII, Fos)"
                consequence_bucket = "pheno_kinase_signaling"
            elif re.search(r"\b(dopamin\w+|gaba\w*|nachr\w*|cholinerg\w+|firing|burst|pacemak\w+|release|neurotransmission)\b", combined_target_text):
                consequence = f"{concept_title} Cholinergic-Dopaminergic Firing, GABAergic Inhibition, and Neurotransmission"
                consequence_bucket = "pheno_neurotransmission"
            else:
                consequence = f"{concept_title} Circuit Activity and Molecular Adaptations"
                consequence_bucket = "pheno_circuit_adaptations"
            if dir_key not in ("increase", "decrease", "no_effect"):
                effect_verb = "Remodels and Regulates"
    else:
        # Gene Arm relationship classification
        gene_pat = re.escape(gene.lower())
        is_true_genetic_variant = bool(
            design in ("human_gwas_polygenic", "human_candidate_variant", "human_imaging_genetics")
        )
        is_gene_perturbation = bool(
            re.search(
                rf"\b(knockout|knock-out|ko\b|haploinsufficien\w+|deletion|knockdown|sirna|shrna|overexpression|transgenic|nifedipine|verapamil|isradipine|diltiazem|nimodipine|nitrendipine|amlodipine|bay\s*k\s*8644|fpl\s*64176|antagonist|blockade|blocker|inhibitor|{gene_pat}\+/-|cav1\.2-cko)\b",
                fl,
            )
            and not is_true_genetic_variant
        )
        is_gene_target = bool(
            re.search(rf"\b({gene_pat}|cav1\.2|ca\(v\)1\.2|alpha1c|pcsk3)\b", dt_lower)
            or re.search(
                rf"\b({gene_pat}|cav1\.2|ca\(v\)1\.2|alpha1c|pcsk3)\s+(?:alpha1\s+subunit\s+|gene\s+|channel\s+|convertase\s+)?(mrna|protein|expression|methylation|promoter|transcript|levels|immunoreactivity|density|signaling|current|activity)",
                fl,
            )
            or re.search(
                rf"\b(methylation|cpg|methylome|hypomethylat\w+|hypermethylat\w+|eccdna|deregulated|upregulated|downregulated|differentially\s+expressed)\b.*\b({gene_pat}|cav1\.2|ca\(v\)1\.2|pcsk3)\b",
                fl,
            )
            or re.search(
                rf"\b({gene_pat}|cav1\.2|ca\(v\)1\.2|pcsk3)\b.*\b(eccdna|higher\s+expression|dna\s+methylation|hypomethylated|hypermethylated|deregulated)\b",
                fl,
            )
        )

        def _classify_consequence(text: str, default_label: str, default_key: str) -> tuple[str, str]:
            if re.search(r"\b(self-administration|reinstatement|conditioned place preference|\bcpp\b|drug-seeking|alcohol-seeking|cocaine-seeking|nicotine-seeking|ethanol intake|alcohol consumption|opioid use disorder)\b", text):
                return "Operant Drug-Seeking, Self-Administration, and Conditioned Reward", "drug_seeking_reward"
            if re.search(r"\b(sensitization|hyperlocomotion|locomotor sensitization|psychomotor)\b", text):
                return "Behavioral Sensitization and Psychomotor Activation", "behavioral_sensitization"
            if re.search(r"\b(50-khz|ultrasonic vocalization|usv|sucrose preference|orofacial|hedonic|probabilistic reward|reward responsiveness|reinforcement learning)\b", text):
                return "Hedonic Reactivity, Appetitive Vocalizations, and Reward Learning", "hedonic_reward_learning"
            if re.search(r"\b(ltp|ltd|long-term potentiation|long-term depression|synaptic plasticity|spine|glua1|ampa|nmda|epsc|ipsc|synaptogenesis)\b", text):
                return "Synaptic Plasticity (LTP/LTD), Glutamatergic Trafficking, and Spine Remodeling", "synaptic_plasticity_glua1"
            if re.search(r"\b(camkii|erk1/2|erk2|p-creb|creb|darpp-32|bdnf|probdnf|mbdnf|trkb|akt|gsk3|calcineurin|nf-?at)\b", text):
                return "Intracellular Kinase, Neurotrophin, and Transcriptional Signaling (CaMKII, ERK, CREB, BDNF)", "kinase_creb_signaling"
            if re.search(r"\b(dopamine release|dat\b|dopamine transporter|glutamate release|gaba release|neurotransmitter release|monoamine)\b", text):
                return "Subsecond Dopamine, Glutamate, and Neurotransmitter Release", "neurotransmitter_release"
            if re.search(r"\b(burst firing|pacemaking|action potential|afterhyperpolarization|firing rate|membrane excitability|calcium influx|ca2\+\s+influx|ca2\+\s+transient|ical|l-type\s+current|barium\s+current)\b", text):
                return "Neuronal Excitability, Burst Firing, and L-Type Calcium Currents", "neuronal_firing_calcium"
            if re.search(r"\b(anxiety|elevated plus maze|open field|fear extinction|contextual fear|freezing|forced swim|tail suspension|depressive|learned helplessness|startle|seizure)\b", text):
                return "Anxiety-Like, Depressive-Like, Fear, and Withdrawal Affective Behavior", "affective_anxiety_depression"
            if re.search(r"\b(social interaction|social play|sociability|prepulse inhibition|sensorimotor gating|spatial memory|working memory|morris water maze)\b", text):
                return "Social Behavior, Sensorimotor Gating, and Cognitive Performance", "social_cognitive_behavior"
            if re.search(r"\b(cortical thickness|cortical surface|gray matter|grey matter|white matter|amygdala volume|globus pallidus|functional connectivity|bold|fmri|regional activation|neural oscillations)\b", text):
                return "Regional Brain Structure, Circuit Connectivity, and Neural Activation", "brain_structure_activation"
            if re.search(r"\b(microglia|astrocyte|oligodendrocyte|myelin|neuroinflammation|cytokine|tnf|il-1|blood-brain barrier|endotheli\w+|oxidative stress|ferroptosis|mitochondri\w+)\b", text):
                return "Glial Reactivity, Myelination, Neurovascular Integrity, and Cellular Stress", "glial_neurovascular_stress"
            return default_label, default_key

        if is_true_genetic_variant and not is_gene_perturbation:
            if dir_key == "gene_environment_interaction":
                cause = f"{gene} Polymorphisms x {concept_title} Exposure"
                cause_bucket = "gxe_variant_interaction"
            elif design == "human_gwas_polygenic":
                cause = f"{gene} Genome-Wide Association Loci (GWAS / TWAS / MR)"
                cause_bucket = "gwas_polygenic_loci"
            else:
                cause = f"{gene} Candidate Polymorphisms and Coding Variants"
                cause_bucket = "candidate_genetic_variant"

            if is_gene_target:
                if re.search(r"\b(methylation|cpg|epigenetic|promoter)\b", combined_target_text):
                    consequence = f"{gene} Epigenetic DNA Methylation and Promoter Regulation"
                    consequence_bucket = "gene_epigenetics"
                else:
                    consequence = f"{gene_disp} mRNA Isoform and Protein Expression"
                    consequence_bucket = "gene_expression"
            else:
                consequence, consequence_bucket = _classify_consequence(
                    combined_target_text,
                    f"Clinical Susceptibility and Neurobehavioral Phenotypes in {concept_title}",
                    "clinical_susceptibility_phenotypes",
                )
        elif is_gene_target and not is_gene_perturbation:
            if category == "drug":
                cause = f"{concept_title} Exposure and Abstinence"
            elif category in ("addiction", "stress", "psychiatric"):
                cause = f"{concept_title} Exposure or Clinical State"
            else:
                cause = f"Upstream Physiological or Pathological Stimuli in {concept_title}"
            cause_bucket = "exposure_or_state"
            if re.search(r"\b(methylation|cpg|epigenetic|promoter|histone|ezh2|methylome|hypomethylat\w+|hypermethylat\w+)\b", combined_target_text):
                consequence = f"{gene} Epigenetic DNA Methylation and Transcriptional Regulation"
                consequence_bucket = "gene_epigenetics"
            else:
                consequence = f"{gene_disp} Expression and Activity" if gene.upper() != "CACNA1C" else f"{gene_disp} Expression and Channel Activity"
                consequence_bucket = "gene_expression_activity"
        elif is_gene_perturbation:
            cause = f"{gene_disp} Genetic Deletion, Haploinsufficiency, or Pharmacological Modulation"
            cause_bucket = "gene_perturbation"
            consequence, consequence_bucket = _classify_consequence(
                combined_target_text,
                f"Downstream {concept_title} Behavioral and Cellular Phenotypes",
                "downstream_phenotype",
            )
        else:
            cause = f"{gene_disp} Proteolytic Activity and Signaling" if gene.upper() == "FURIN" else f"{gene_disp} Channel Activity and Signaling"
            cause_bucket = "channel_signaling"
            consequence, consequence_bucket = _classify_consequence(
                combined_target_text,
                f"{concept_title} Circuit and Cellular Function",
                "circuit_cellular_function",
            )

    arm_key = "phenotype" if is_pheno else "gene"
    arm_label = "Phenotype Arm" if is_pheno else f"Gene Arm ({gene})"
    group_key = f"{arm_key}__{dir_key}__{cause_bucket}__{consequence_bucket}"
    rel_title = f"{cause} \u27f6 {effect_verb} \u27f6 {consequence}"

    ctx_parts = []
    if sp_str and sp_str != "unspecified":
        ctx_parts.append(f"species: {sp_str}")
    if design and design not in ("unspecified", "unclear"):
        ctx_parts.append(f"design: {design}")
    if dt:
        ctx_parts.append(f"readout target: {dt}")
    if tissue:
        ctx_parts.append(f"anatomical/cellular site: {tissue}")
    if model:
        ctx_parts.append(f"paradigm/model: {model}")
    context_str = "; ".join(ctx_parts) if ctx_parts else "screened experimental context"

    return {
        "group_key": group_key,
        "rel_title": _sanitize_prose(rel_title),
        "cause": _sanitize_prose(cause),
        "effect_verb": effect_verb,
        "effect_badge": effect_badge,
        "dir_key": dir_key,
        "consequence": _sanitize_prose(consequence),
        "context_str": _sanitize_prose(context_str),
        "species_list": sp_list,
        "design": design,
        "tissue": _sanitize_prose(tissue),
        "model": _sanitize_prose(model),
        "arm_key": arm_key,
        "arm_label": arm_label,
    }


def _author_year_label(article: dict[str, Any] | None, pmid: str) -> str:
    """Return 'FirstAuthor et al. (Year)' or 'Author (Year)' for prose citations."""
    if not article:
        return f"PMID {pmid}"
    authors = article.get("authors") or []
    first_author = authors[0].split()[0] if authors and authors[0].strip() else f"PMID {pmid}"
    if len(authors) > 2:
        author_part = f"{first_author} et al."
    elif len(authors) == 2:
        second_author = authors[1].split()[0] if authors[1].strip() else ""
        author_part = f"{first_author} and {second_author}" if second_author else first_author
    else:
        author_part = first_author

    pd = article.get("publication_date")
    year = ""
    if isinstance(pd, dict):
        year = str(pd.get("Year") or "")
    elif pd:
        m = re.search(r"\b(19\d\d|20\d\d)\b", str(pd))
        if m:
            year = m.group(1)
    return f"{author_part} ({year})" if year else author_part


def _synthesize_emerging_mini_review_article(
    concept_title: str,
    dedup_assessments: list[dict[str, Any]],
    articles_by_pmid: dict[str, dict[str, Any]],
    custom_narrative: str = "",
    rel_prefix_to_pmid: str = "..",
    primary_gene: str = "CACNA1C",
) -> str:
    """Write an emerging topic mini-review as a cohesive multi-paragraph review article with inline PMID citations.

    First states the general commonality found across the corpus, then dives into nuanced experimental contexts.
    """
    def _cite(p: str) -> str:
        lbl = _author_year_label(articles_by_pmid.get(p), p)
        return f"[{lbl} (PMID {p})]({rel_prefix_to_pmid}/{p}.md)"

    unique_pmids = sorted({str(a["pmid"]) for a in dedup_assessments}, key=lambda x: int(x) if x.isdigit() else x)
    sp_summary = format_species_counts(dedup_assessments)
    gene_disp = _gene_display_label(primary_gene)
    is_cav12 = primary_gene.upper() == "CACNA1C"

    # Convert any raw (PMID:12345678) or PMID 12345678 in custom_narrative into clickable links
    def _linkify_pmids_in_prose(text: str) -> str:
        def _repl(m: re.Match) -> str:
            p = m.group(1)
            return _cite(p)
        return re.sub(r"\bPMID[:\s]+(\d{7,8})\b", _repl, text)

    title_lower = concept_title.lower()
    paragraphs: list[str] = []

    # 1. Paragraph 1: General Commonality Across Studies
    if "cav1.3" in title_lower or "cacna1d" in title_lower:
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            "investigators repeatedly examine `CACNA1C` (CaV1.2) alongside its untracked neuronal L-type calcium channel "
            "paralog `CACNA1D` (CaV1.3). This cross-cutting comparison arises because standard dihydropyridine channel "
            "blockers (nifedipine, isradipine, nimodipine) and activators (Bay K 8644) bind both alpha1 subunits, "
            "requiring genetic or molecular dissection to resolve which channel drives a given behavioral or physiological phenotype. "
            "At a general level, these studies establish a conserved functional division of labor: CaV1.3 activates at more "
            "hyperpolarized membrane potentials to regulate basal pacemaking and acute psychostimulant sensitization, whereas "
            "CaV1.2 activates at more depolarized potentials to drive high-frequency burst firing, postsynaptic synapse-to-nucleus "
            "CREB and CaMKII signaling, late-phase NMDAR-independent long-term potentiation, and protracted drug-abstinence adaptations."
        )
    elif "camkii" in title_lower or "glua1" in title_lower or "darpp-32" in title_lower:
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            "a recurring molecular theme is that CaV1.2 channels do not act solely as passive conductances for membrane "
            "depolarization, but instead organize a spatially restricted postsynaptic signaling nanodomain with calmodulin, "
            "CaMKIIalpha/beta, calcineurin (PP2B), DARPP-32, and AMPA receptor GluA1 subunits. At a general level, calcium "
            "entry through CaV1.2 selectively phosphorylates GluA1 at Ser831 via CaMKII, promotes cell-surface AMPA receptor "
            "insertion, and couples synaptic depolarization to nuclear CREB and NFAT transcriptional programs across striatal, "
            "hippocampal, and amygdalar circuits."
        )
    elif "auxiliary" in title_lower or "cacna2d" in title_lower or "disc1" in title_lower:
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            "multiple independent lines of evidence demonstrate that functional CaV1.2 signaling is governed not by `CACNA1C` "
            "transcription in isolation, but by multi-protein complexes formed with untracked auxiliary voltage-gated calcium "
            "channel subunits (`CACNB2`, `CACNA2D1`, `CACNA2D2`, `CACNA2D4`), RNA-trafficking scaffolds (`DISC1`), and "
            "epigenetic/post-transcriptional regulators (`EZH2`, `eIF3e`, `Stac`). At a general level, perturbations in "
            "these partner proteins alter CaV1.2 surface trafficking, current density, or protein stability even when "
            "basal `CACNA1C` mRNA levels remain unchanged, and polygenic risk across calcium channel subunits converges on "
            "shared clinical phenotypes."
        )
    elif ("cre" in title_lower or "pv" in title_lower or "cell-type" in title_lower) and is_cav12:
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            "conditional genetic deletion of `Cacna1c` using untracked cell-type-specific Cre recombinase drivers "
            "(`PV-Cre` fast-spiking parvalbumin interneurons, `D1-Cre` dopamine D1 receptor medium spiny neurons, and "
            "`CaMKIIalpha-Cre` or `Nex-Cre` forebrain glutamatergic projection neurons) reveals that global or pan-neuronal "
            "`Cacna1c` manipulation masks opposing circuit-specific functions. At a general level, losing CaV1.2 in inhibitory "
            "interneurons versus excitatory projection neurons or striatal D1 pathways produces dissociable, and often opposite, "
            "effects on excitation/inhibition balance, stress-coping strategies, and conditioned drug seeking."
        )
    elif custom_narrative.strip():
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            + _linkify_pmids_in_prose(_sanitize_prose(custom_narrative.strip()))
        )
    else:
        p1 = (
            f"**General Commonality Across the Corpus**: Across {len(unique_pmids)} screened studies ({sp_summary}), "
            f"**{concept_title}** emerges as a cross-cutting mechanistic theme linking {gene_disp} function across "
            "multiple experimental domains that are otherwise separated in the primary ontology."
        )
    paragraphs.append(p1)

    # 2. Group the studies into thematic context paragraphs (nuanced experimental differences), one entry per PMID
    inc_studies: list[tuple[str, str, str]] = []
    dec_studies: list[tuple[str, str, str]] = []
    null_or_dissoc_studies: list[tuple[str, str, str]] = []
    state_or_mod_studies: list[tuple[str, str, str]] = []

    best_by_pmid: dict[str, dict[str, Any]] = {}
    for a in dedup_assessments:
        p = str(a.get("pmid") or "").strip()
        if not p:
            continue
        f_len = len(_clean_finding_text(a.get("finding") or "", "emerging"))
        prev = best_by_pmid.get(p)
        if prev is None or f_len > len(_clean_finding_text(prev.get("finding") or "", "emerging")):
            best_by_pmid[p] = a

    for p in sorted(best_by_pmid.keys(), key=lambda x: int(x) if x.isdigit() else x):
        a = best_by_pmid[p]
        info = _infer_relationship_in_context(a, concept_title, "emerging", primary_gene=primary_gene)
        clean_f = _clean_finding_text(a.get("finding") or "", "emerging").rstrip(".")
        clean_f = re.sub(
            r"^(?:this\s+review\s+summarizes\s+(?:how\s+)?|review\s+(?:discussing|summarizing|of|stating\s+that|noting\s+that)\s+(?:how\s+)?|reviews\s+|reports\s+that\s+|shows\s+that\s+|evaluated\s+)",
            "",
            clean_f,
            flags=re.IGNORECASE,
        ).strip()
        if clean_f:
            clean_f = clean_f[0].lower() + clean_f[1:] if len(clean_f) > 1 and clean_f[1].islower() else clean_f
        ctx_short_parts = []
        if info["species_list"]:
            ctx_short_parts.append("/".join(info["species_list"]))
        if info["tissue"]:
            t_short = info["tissue"].split(";")[0].strip()
            if len(t_short) > 55:
                t_short = t_short[:52].rstrip() + "..."
            ctx_short_parts.append(t_short)
        elif info["model"]:
            m_short = info["model"].split(";")[0].strip()
            if len(m_short) > 55:
                m_short = m_short[:52].rstrip() + "..."
            ctx_short_parts.append(m_short)
        ctx_tag = f" ({'; '.join(ctx_short_parts)})" if ctx_short_parts else ""
        sp_only_tag = f" ({'/'.join(info['species_list'])})" if info["species_list"] else ""
        verb = "reported that" if re.match(r"^(?:in\s+|while\s+|comparison\s+|using\s+|across\s+)", clean_f, re.I) else "showed that"
        full_sentence = f"{_cite(p)}{ctx_tag} {verb} {clean_f}."
        compact_cite = f"{_cite(p)}{ctx_tag}"
        short_cite = f"{_cite(p)}{sp_only_tag}"

        if info["dir_key"] == "increase":
            inc_studies.append((full_sentence, compact_cite, short_cite))
        elif info["dir_key"] == "decrease":
            dec_studies.append((full_sentence, compact_cite, short_cite))
        elif info["dir_key"] == "no_effect":
            null_or_dissoc_studies.append((full_sentence, compact_cite, short_cite))
        else:
            state_or_mod_studies.append((full_sentence, compact_cite, short_cite))

    def _build_section_paragraph(header_lead: str, items: list[tuple[str, str, str]], max_detailed: int, use_short_tail: bool) -> str:
        if not items:
            return ""
        if len(items) <= max_detailed:
            return header_lead + " " + " ".join(x[0] for x in items)
        detailed_part = " ".join(x[0] for x in items[:max_detailed])
        tail_idx = 2 if use_short_tail else 1
        remaining_part = ", ".join(x[tail_idx] for x in items[max_detailed:])
        return (
            f"{header_lead} {detailed_part} "
            f"Additional studies further characterize this relationship across complementary preparations and experimental models, "
            f"including {remaining_part}."
        )

    # Dynamically cap detailed sentences per section so the entire review stays strictly under 1,000 words (~550-820 words)
    total_studies = len(best_by_pmid)
    max_det = 5 if total_studies <= 15 else (4 if total_studies <= 28 else 3)

    inc_lead = (
        "**Contexts Demonstrating Upregulation or Potentiated Signaling**: "
        "In experimental paradigms examining activity-dependent potentiation, chronic drug withdrawal, or pathological "
        f"upregulation, multiple studies document heightened {'CaV1.2' if is_cav12 else gene_disp} expression or downstream effector coupling."
    )
    dec_lead = (
        "**Contexts Demonstrating Downregulation, Loss-of-Function Attenuation, or Pharmacological Blockade**: "
        f"Conversely, under genetic deletion, knockdown, or pharmacological {'L-type channel antagonism' if is_cav12 else f'modulation of {gene_disp} and its substrates'} across distinct "
        "anatomical and developmental contexts, studies report selective attenuation of downstream signaling and behavior."
    )
    state_lead = (
        "**Nuanced State-Dependent, Isoform-Specific, and Polygenic Contexts**: "
        f"Several investigations further show that the direction and magnitude of {'CaV1.2' if is_cav12 else gene_disp} involvement depend critically "
        "on abstinence duration, brain region, developmental stage, or genetic background."
    )
    null_lead = (
        "**Functional Dissociations and Negative Controls**: "
        f"Finally, explicit dissociation experiments define the boundary conditions where {'CaV1.2' if is_cav12 else gene_disp} is dispensable or "
        "diverges from parallel pathways."
    )

    for use_short in (False, True):
        for det_try in range(max_det, 0, -1):
            candidate_paragraphs = [p1]
            if inc_studies:
                candidate_paragraphs.append(
                    _build_section_paragraph(
                        inc_lead,
                        inc_studies,
                        det_try,
                        use_short,
                    )
                )
            if dec_studies:
                candidate_paragraphs.append(
                    _build_section_paragraph(
                        dec_lead,
                        dec_studies,
                        det_try,
                        use_short,
                    )
                )
            if state_or_mod_studies:
                candidate_paragraphs.append(
                    _build_section_paragraph(
                        state_lead,
                        state_or_mod_studies,
                        det_try,
                        use_short,
                    )
                )
            if null_or_dissoc_studies:
                candidate_paragraphs.append(
                    _build_section_paragraph(
                        null_lead,
                        null_or_dissoc_studies,
                        det_try,
                        use_short,
                    )
                )
            combined_text = "\n\n".join(candidate_paragraphs)
            if len(combined_text.split()) <= 850:
                return combined_text
    return combined_text


def _synthesize_base_interaction_sentence(
    cid: str,
    concept_title: str,
    category: str,
    primary_gene: str,
    phenotype_label: str,
    gene_assessments: list[dict[str, Any]],
    pheno_assessments: list[dict[str, Any]],
) -> str:
    """Synthesize a concise, domain-accurate Candidate Point of Interaction sentence when both Gene and Phenotype arms have evidence."""
    if not gene_assessments or not pheno_assessments or cid == "phenotype/direct":
        return ""

    gu = primary_gene.upper()
    gene_disp = _gene_display_label(primary_gene)
    pheno_lower = phenotype_label.lower()
    tl = concept_title.lower()

    all_text = " ".join(
        f"{a.get('finding', '')} {a.get('direction_target', '')}"
        for a in (gene_assessments + pheno_assessments)
    ).lower()

    shared_themes: list[str] = []
    if re.search(r"\b(glua1|glua2|ampa|ser831)\b", all_text):
        shared_themes.append("AMPA receptor (GluA1/GluA2) phosphorylation and synaptic trafficking")
    if re.search(r"\b(glutamat\w+|glt-1|eaat2|nmda\w*|ltp|ltd|synaptic plasticity)\b", all_text):
        shared_themes.append("corticostriatal and accumbal glutamatergic synaptic plasticity")
    if re.search(r"\b(dopamin\w+|d1\b|d2\b|msn|medium spiny)\b", all_text):
        shared_themes.append("mesolimbic dopamine release and D1/D2 medium spiny neuron signaling")
    if re.search(r"\b(gaba\w*|interneuron\w*|parvalbumin|\bpv\b|inhibitory)\b", all_text):
        shared_themes.append("GABAergic inhibitory microcircuit excitability")
    if not shared_themes:
        shared_themes.append("activity-dependent intracellular calcium and transcriptional signaling")
    themes_str = ", ".join(shared_themes[:2])

    if gu == "CACNA1C":
        if cid == "drug/alcohol":
            return (
                "Alcohol and nicotine co-use share mesolimbic nAChR, dopaminergic, and accumbal GLT-1 glutamatergic pathways: "
                "alcohol withdrawal upregulates hippocampal, amygdala, and striatal CACNA1C (CaV1.2), and conditional CaV1.2 "
                "deletion or L-type blockade abolishes dependence-induced alcohol seeking."
            )
        if cid == "drug/cocaine":
            return (
                "Cocaine and nicotine self-administration converge on postsynaptic nucleus accumbens CACNA1C (CaV1.2) channels, "
                "which activate CaMKII and ERK2 after abstinence to phosphorylate GluA1 at Ser831 and drive AMPA receptor surface "
                "insertion during sensitized drug seeking."
            )
        if cid == "drug/opioid":
            return (
                "Opioid and nicotine reinforcement share VTA-to-accumbens dopaminergic and kappa-opioid/dynorphin stress circuits, "
                "where L-type calcium channel (CACNA1C / CaV1.2) blockade attenuates opioid and nicotine conditioned reward, "
                "self-administration, and withdrawal symptoms."
            )
        if cid == "drug/amphetamine":
            return (
                "Psychostimulant (amphetamine/methamphetamine) sensitization and nicotine self-administration share VTA CACNA1C "
                "(CaV1.2)-dependent subsecond dopamine release in the nucleus accumbens and striatal ERK1/2-CREB plasticity."
            )
        if cid == "drug/cannabinoid":
            return (
                "Endocannabinoid CB1/CB2 modulation of nicotine self-administration intersects with CACNA1C (CaV1.2) L-type "
                "calcium channels in mesocorticolimbic circuits governing presynaptic transmitter release and cue-induced reinstatement."
            )
        if cid == "drug/benzodiazepine":
            return (
                "Benzodiazepine-sensitive GABA-A receptor transmission regulates both nicotine self-administration and CACNA1C "
                "(CaV1.2) L-type calcium channel expression during drug withdrawal."
            )
        if cid in ("addiction/aversion", "brain/amygdala", "stress/stress", "stress/PTSD", "psychiatric/anxiety"):
            return (
                f"Stress- and cue-induced {pheno_lower} and withdrawal negative affect recruit {concept_title} CaMKII, CRF, and "
                "dynorphin/kappa-opioid circuits, converging with CACNA1C (CaV1.2) regulation of amygdala synaptic plasticity, "
                "D1-neuron aversive memory, and stress reactivity."
            )
        if category == "addiction" or cid in ("psychiatric/compulsive", "psychiatric/impulsivity"):
            return (
                f"In {tl} paradigms, {pheno_lower} and CACNA1C (CaV1.2) converge on {themes_str}, where withdrawal-induced "
                "Cav1.2 upregulation and VTA-to-accumbens L-type calcium signaling modulate reward sensitivity and relapse vulnerability."
            )
        if cid in ("brain/cortex", "brain/hippocampus", "brain/limbic system"):
            return (
                f"Cue-evoked {pheno_lower} and extinction learning depend on top-down {tl} glutamatergic projections and "
                "ERK1/2-dependent synaptic plasticity, processes gated by somatodendritic CACNA1C (CaV1.2) calcium influx, "
                "dendritic spine remodeling, and excitation-transcription coupling."
            )
        if cid in ("brain/striatum", "brain/accumbens", "brain/basal ganglia"):
            return (
                f"Operant {pheno_lower} and cue-induced relapse require phasic dopamine signaling and glutamatergic AMPA/NMDA "
                f"synaptic potentiation in the {tl}, where postsynaptic CACNA1C (CaV1.2) channels activate CaMKII and ERK2 to "
                "phosphorylate GluA1 at Ser831 and drive AMPA receptor surface insertion."
            )
        if cid in ("brain/VTA", "brain/mesolimbic pathway", "brain/midbrain"):
            return (
                "Nicotine reinforces operant intake by activating somatodendritic nAChRs on VTA dopamine neurons to drive phasic "
                "dopamine release in the nucleus accumbens, a transition from tonic firing to burst firing that directly recruits "
                "high-threshold CACNA1C (CaV1.2) L-type calcium channels."
            )
        if category == "function":
            return (
                f"Both CACNA1C (CaV1.2) channel activation and operant {pheno_lower} converge on {themes_str}: "
                "depolarization-induced CaV1.2 calcium entry triggers CaMKII, Ras-ERK1/2, and CREB signaling to remodel "
                "GluA1/GluA2 AMPA synapses during drug seeking and abstinence."
            )
        if category == "cell":
            cell_pl = f"{tl}s" if not tl.endswith("glia") else tl
            return (
                f"Within {cell_pl}, {pheno_lower} and CACNA1C (CaV1.2) intersect through {themes_str}, linking L-type calcium "
                f"influx in {cell_pl} to altered glutamate homeostasis, neurovascular/glial plasticity, and nicotine seeking."
            )
        return (
            f"In {concept_title}, CACNA1C (CaV1.2) and {pheno_lower} converge on {themes_str}, positioning CaV1.2-mediated "
            "L-type calcium influx as a direct modulator of nicotine reinforcement and relapse circuitry."
        )

    if gu == "FURIN":
        if cid in ("drug/opioid", "addiction/addiction", "addiction/reward"):
            return (
                "Human genome-wide association meta-analyses (MVP, All of Us, PGC/GENOA) consistently identify FURIN (lead "
                "variants rs4702, rs11372849, rs17514846) alongside OPRM1 as a primary opioid use disorder risk locus, while "
                "biochemical and rodent studies show that furin cleaves proenkephalin into intermediate opioid peptides and "
                "regulates striatal/cortical proBDNF-to-mBDNF maturation during opioid exposure and withdrawal."
            )
        if cid in ("drug/nicotine", "drug/alcohol"):
            return (
                "Cross-substance multi-trait GWAS (MTAG) links FURIN across opioid, alcohol, and cannabis use disorders, while "
                "developmental nicotine exposure downregulates cortical, striatal, and hippocampal furin and impairs proBDNF "
                "proteolysis across generations."
            )
        if cid == "addiction/withdrawal":
            return (
                "Spontaneous morphine withdrawal in rats robustly increases proBDNF precursor accumulation and alters the "
                "mBDNF/proBDNF proteolytic ratio in the frontal cortex and striatum alongside changes in furin and extracellular "
                "tPA/plasminogen cleavage, converging with BDNF-TrkB and p75NTR plasticity that drives opioid withdrawal aversion "
                "and cue-induced relapse."
            )
        if cid == "brain/striatum":
            return (
                "Within the striatum, chronic morphine exposure and withdrawal shift the balance between intracellular "
                "furin-mediated proBDNF cleavage and proBDNF accumulation, directly modulating TrkB-ERK-CREB and "
                "dopamine/glutamate medium spiny neuron plasticity that governs opioid reinforcement and seeking."
            )
        if cid in ("brain/hippocampus", "brain/cortex"):
            return (
                f"In the {tl}, the OUD-associated 3'UTR risk allele rs4702-G downregulates FURIN via miR-338-3p and reduces "
                "mature BDNF secretion, while transgenic Furin overexpression elevates cortical and hippocampal mBDNF/proBDNF "
                "ratios, ERK-CREB phosphorylation, dendritic spine density, and late-phase LTP maintenance."
            )
        if cid in ("brain/amygdala", "brain/hypothalamus", "stress/PTSD", "stress/stress", "psychiatric/anxiety"):
            return (
                f"In {concept_title} neuroendocrine and stress circuits, FURIN cleaves proopiomelanocortin (POMC) into proACTH "
                "and processes proBDNF/proNGF and proSAAS precursors, intersecting with hypothalamic-pituitary-adrenal (HPA) "
                "axis and extended amygdala stress adaptations in opioid dependence."
            )
        if category == "function":
            return (
                f"Both FURIN (PCSK3) endoproteolytic activity and {pheno_lower} converge on {tl} via intracellular trans-Golgi "
                "cleavage of proBDNF to mature BDNF, NMDA-triggered LRP1 receptor cleavage, GABA-A receptor beta2/3 "
                "transcriptional regulation, and TrkB-ERK1/2-CREB signaling."
            )
        if category == "cell":
            return (
                f"In {tl} populations, FURIN mediates proBDNF maturation, integrin alpha V (ITGAV)-dependent astrocytic "
                f"lipophagy, LRP1 receptor processing, and neuroimmune cytokine signaling that modulate synaptic and glial "
                f"homeostasis in {pheno_lower}."
            )
        if category == "psychiatric":
            return (
                f"Conjunctional FDR and multi-omic XWAS analyses identify FURIN on chromosome 15q26.1 (rs4702) as a shared "
                f"cis-eQTL genetic risk locus linking {pheno_lower} with {tl}, mediated by miR-338-3p regulation of FURIN "
                "expression, proBDNF maturation, and FURIN/HMGB1 neuroinflammatory signaling."
            )
        return (
            f"In {concept_title}, FURIN (PCSK3) proprotein convertase activity and {pheno_lower} converge on proneurotrophin "
            "(proBDNF/proNGF) and neuropeptide precursor processing, cis-eQTL gene regulation, and activity-dependent synaptic remodeling."
        )

    return (
        f"In {concept_title}, {gene_disp} and {pheno_lower} converge on {themes_str} across shared neural circuits and cellular pathways."
    )


def _rank_arm_assessments(
    arm_assessments: list[dict[str, Any]],
    cid: str,
) -> list[dict[str, Any]]:
    """Deduplicate an arm's assessments by PMID and rank most informative experimental findings first."""
    by_pmid: dict[str, dict[str, Any]] = {}
    for a in arm_assessments:
        p = str(a.get("pmid") or "").strip()
        if not p:
            continue
        f_txt = _clean_finding_text(a.get("finding") or "", cid)
        prev = by_pmid.get(p)
        if prev is None or len(f_txt) > len(_clean_finding_text(prev.get("finding") or "", cid)):
            by_pmid[p] = a

    def _score(item: dict[str, Any]) -> tuple[int, int, int, int]:
        d = str(item.get("direction") or "").lower()
        has_dir = 1 if d in ("increase", "decrease", "no_effect", "mixed") else 0
        sd = str(item.get("study_design") or "").lower()
        not_rev = 0 if "review" in sd else 1
        f_clean = _clean_finding_text(item.get("finding") or "", cid)
        is_objective_or_truncated = bool(
            re.match(r"^(?:to\s+(?:determine|examine|investigate|evaluate|assess|characterize|test|identify|explore)\b|whether\s+)", f_clean, re.I)
            or re.search(r"(?:[=<>]\s*\d+|\(\d+)$", f_clean.rstrip("."))
        )
        complete_result = 0 if is_objective_or_truncated else 1
        fl = len(f_clean)
        return (complete_result, not_rev, has_dir, min(fl, 260))

    return sorted(by_pmid.values(), key=_score, reverse=True)


def _format_arm_lead_sentence(
    prefix_label: str,
    ranked_assess: list[dict[str, Any]],
    cid: str,
    articles_by_pmid: dict[str, dict[str, Any]],
    rel_prefix_to_pmid: str = "..",
    use_markdown_links: bool = True,
    max_cites: int = 3,
) -> str:
    """Build a lead evidence sentence with top citations for either the Gene Arm or Phenotype Arm."""
    if not ranked_assess:
        return ""
    top_a = ranked_assess[0]
    raw_f = _clean_finding_text(top_a.get("finding") or "", cid).rstrip(".")
    raw_f = re.sub(
        r"^(?:this\s+review\s+summarizes\s+(?:how\s+)?|review\s+(?:discussing|summarizing|of|stating\s+that|noting\s+that)\s+(?:how\s+)?|reviews\s+|reports\s+that\s+|shows\s+that\s+|evaluated\s+)",
        "",
        raw_f,
        flags=re.IGNORECASE,
    ).strip()
    if raw_f:
        if prefix_label:
            raw_f = raw_f[0].lower() + raw_f[1:] if len(raw_f) > 1 and raw_f[1].islower() else raw_f
        else:
            raw_f = raw_f[0].upper() + raw_f[1:]

    cites: list[str] = []
    for a in ranked_assess[:max_cites]:
        p = str(a["pmid"])
        lbl = _author_year_label(articles_by_pmid.get(p), p)
        if use_markdown_links:
            cites.append(f"[{lbl} (PMID {p})]({rel_prefix_to_pmid}/{p}.md)")
        else:
            cites.append(f"{lbl} (PMID {p})")
    if len(ranked_assess) > max_cites:
        cites.append(f"+{len(ranked_assess) - max_cites} more")
    cite_str = f" ({'; '.join(cites)})" if cites else ""
    if prefix_label:
        return f"{prefix_label}, {raw_f}{cite_str}."
    return f"{raw_f}{cite_str}."


def _build_concept_overview_and_overlap(
    cid: str,
    concept_title: str,
    category: str,
    is_emerging: bool,
    primary_gene: str,
    phenotype_label: str,
    assessments: list[dict[str, Any]],
    articles_by_pmid: dict[str, dict[str, Any]],
    custom_narrative: str = "",
    rel_prefix_to_pmid: str = "..",
) -> dict[str, str]:
    """Compute plain and markdown-linked Concept Synthesis lead paragraph and Candidate Point of Interaction."""
    gene_disp = _gene_display_label(primary_gene)
    pheno_title = _title_case_phenotype(phenotype_label)
    pheno_lower = phenotype_label.lower()

    gene_assess = [a for a in assessments if not _is_phenotype_arm(a.get("gene"))]
    pheno_assess = [a for a in assessments if _is_phenotype_arm(a.get("gene"))]
    ranked_gene = _rank_arm_assessments(gene_assess, cid)
    ranked_pheno = _rank_arm_assessments(pheno_assess, cid)

    gene_cnt = len({str(a["pmid"]) for a in gene_assess})
    pheno_cnt = len({str(a["pmid"]) for a in pheno_assess})
    total_cnt = len({str(a["pmid"]) for a in assessments})
    sp_summary = format_species_counts(assessments)

    base_inter = _synthesize_base_interaction_sentence(
        cid=cid,
        concept_title=concept_title,
        category=category,
        primary_gene=primary_gene,
        phenotype_label=phenotype_label,
        gene_assessments=gene_assess,
        pheno_assessments=pheno_assess,
    )

    interaction_summary_plain = ""
    overlap_md_block = ""

    if gene_cnt > 0 and pheno_cnt > 0 and base_inter:
        g_cites = [
            f"{_author_year_label(articles_by_pmid.get(str(a['pmid'])), str(a['pmid']))} (PMID {a['pmid']})"
            for a in ranked_gene[:2]
        ]
        p_cites = [
            f"{_author_year_label(articles_by_pmid.get(str(a['pmid'])), str(a['pmid']))} (PMID {a['pmid']})"
            for a in ranked_pheno[:2]
        ]
        interaction_summary_plain = (
            f"{base_inter} ({primary_gene}: {'; '.join(g_cites)}; {pheno_title}: {'; '.join(p_cites)})."
        )

        lower_inter = base_inter[0].lower() + base_inter[1:] if len(base_inter) > 1 and base_inter[1].islower() else base_inter
        g_sent_md = _format_arm_lead_sentence(f"For {primary_gene}", ranked_gene, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        p_sent_md = _format_arm_lead_sentence(f"In {pheno_lower} models", ranked_pheno, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        g_sent_plain = _format_arm_lead_sentence(f"For {primary_gene}", ranked_gene, cid, articles_by_pmid, rel_prefix_to_pmid, False, 3)
        p_sent_plain = _format_arm_lead_sentence(f"In {pheno_lower} models", ranked_pheno, cid, articles_by_pmid, rel_prefix_to_pmid, False, 3)

        lead_md = (
            f"Across {total_cnt} confirmed studies in {concept_title} ({gene_cnt} {primary_gene} studies and "
            f"{pheno_cnt} {pheno_lower} studies ({sp_summary})), {lower_inter} {g_sent_md} {p_sent_md}"
        ).strip()
        lead_plain = (
            f"Across {total_cnt} confirmed studies in {concept_title} ({gene_cnt} {primary_gene} studies and "
            f"{pheno_cnt} {pheno_lower} studies ({sp_summary})), {lower_inter} {g_sent_plain} {p_sent_plain}"
        ).strip()

        g_ev_md = _format_arm_lead_sentence("", ranked_gene, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        p_ev_md = _format_arm_lead_sentence("", ranked_pheno, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        overlap_md_block = "\n".join([
            "### Gene-Phenotype Mechanistic Overlap and Candidate Points of Interaction",
            "",
            f"- **Candidate Point of Interaction**: {base_inter}",
            f"- **{gene_disp} Evidence ({gene_cnt} studies)**: {g_ev_md}",
            f"- **{pheno_title} Evidence ({pheno_cnt} studies)**: {p_ev_md}",
        ])
    elif gene_cnt > 0:
        g_sent_md = _format_arm_lead_sentence(f"For {primary_gene}", ranked_gene, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        g_sent_plain = _format_arm_lead_sentence(f"For {primary_gene}", ranked_gene, cid, articles_by_pmid, rel_prefix_to_pmid, False, 3)
        extra_md = ""
        extra_plain = ""
        if len(ranked_gene) > 1:
            extra_md = " " + _format_arm_lead_sentence("Additionally", ranked_gene[1:2], cid, articles_by_pmid, rel_prefix_to_pmid, True, 1)
            extra_plain = " " + _format_arm_lead_sentence("Additionally", ranked_gene[1:2], cid, articles_by_pmid, rel_prefix_to_pmid, False, 1)
        if is_emerging and custom_narrative.strip():
            base_em = _sanitize_prose(custom_narrative.strip()).rstrip(".")
            lead_md = f"{base_em} ({total_cnt} confirmed studies ({sp_summary})). {g_sent_md}{extra_md}".strip()
            lead_plain = f"{base_em} ({total_cnt} confirmed studies ({sp_summary})). {g_sent_plain}{extra_plain}".strip()
        else:
            lead_md = (
                f"Across {total_cnt} confirmed {primary_gene} studies in {concept_title} ({sp_summary}), experimental and "
                f"genetic evidence characterizes how {gene_disp} regulates {concept_title.lower()} function. {g_sent_md}{extra_md}"
            ).strip()
            lead_plain = (
                f"Across {total_cnt} confirmed {primary_gene} studies in {concept_title} ({sp_summary}), experimental and "
                f"genetic evidence characterizes how {gene_disp} regulates {concept_title.lower()} function. {g_sent_plain}{extra_plain}"
            ).strip()
    else:
        p_sent_md = _format_arm_lead_sentence(f"In {pheno_lower} models", ranked_pheno, cid, articles_by_pmid, rel_prefix_to_pmid, True, 3)
        p_sent_plain = _format_arm_lead_sentence(f"In {pheno_lower} models", ranked_pheno, cid, articles_by_pmid, rel_prefix_to_pmid, False, 3)
        extra_md = ""
        extra_plain = ""
        if len(ranked_pheno) > 1:
            extra_md = " " + _format_arm_lead_sentence("Additionally", ranked_pheno[1:2], cid, articles_by_pmid, rel_prefix_to_pmid, True, 1)
            extra_plain = " " + _format_arm_lead_sentence("Additionally", ranked_pheno[1:2], cid, articles_by_pmid, rel_prefix_to_pmid, False, 1)
        action_phrase = "operant nicotine intake and seeking" if "nicotine" in pheno_lower else f"{pheno_lower} susceptibility and relapse"
        lead_md = (
            f"Across {total_cnt} confirmed {pheno_lower} studies in {concept_title} ({sp_summary}), experimental evidence "
            f"defines how {concept_title.lower()} mechanisms regulate {action_phrase}. {p_sent_md}{extra_md}"
        ).strip()
        lead_plain = (
            f"Across {total_cnt} confirmed {pheno_lower} studies in {concept_title} ({sp_summary}), experimental evidence "
            f"defines how {concept_title.lower()} mechanisms regulate {action_phrase}. {p_sent_plain}{extra_plain}"
        ).strip()

    return {
        "lead_md": _sanitize_prose(lead_md),
        "lead_plain": _sanitize_prose(lead_plain),
        "interaction_summary": _sanitize_prose(interaction_summary_plain),
        "overlap_md_block": _sanitize_prose(overlap_md_block),
    }


def _synthesize_concept_mini_review_prose(
    cid: str,
    concept_title: str,
    category: str,
    is_emerging: bool,
    primary_gene: str,
    phenotype_label: str,
    assessments: list[dict[str, Any]],
    articles_by_pmid: dict[str, dict[str, Any]],
    related_concepts: list[tuple[str, str, int]],
    custom_narrative: str = "",
    rel_prefix_to_pmid: str = "..",
) -> tuple[str, dict[str, str]]:
    """Build concept review prose, returning (markdown_prose, overview_dict)."""
    dedup_assessments: list[dict[str, Any]] = []
    seen_pf: set[tuple[str, str]] = set()
    for a in assessments:
        p = str(a.get("pmid") or "").strip()
        f_txt = _clean_finding_text(a.get("finding") or "", a.get("concept_id") or "")
        if not p or (p, f_txt) in seen_pf:
            continue
        seen_pf.add((p, f_txt))
        dedup_assessments.append(a)

    overview = _build_concept_overview_and_overlap(
        cid=cid,
        concept_title=concept_title,
        category=category,
        is_emerging=is_emerging,
        primary_gene=primary_gene,
        phenotype_label=phenotype_label,
        assessments=dedup_assessments,
        articles_by_pmid=articles_by_pmid,
        custom_narrative=custom_narrative,
        rel_prefix_to_pmid=rel_prefix_to_pmid,
    )

    paragraphs: list[str] = []

    if is_emerging:
        article_prose = _synthesize_emerging_mini_review_article(
            concept_title=concept_title,
            dedup_assessments=dedup_assessments,
            articles_by_pmid=articles_by_pmid,
            custom_narrative=custom_narrative,
            rel_prefix_to_pmid=rel_prefix_to_pmid,
            primary_gene=primary_gene,
        )
        paragraphs.append(article_prose)
    else:
        paragraphs.append(overview["lead_md"])

        rel_groups: dict[str, dict[str, Any]] = {}
        for a in dedup_assessments:
            info = _infer_relationship_in_context(
                a,
                concept_title,
                category,
                primary_gene=primary_gene,
                phenotype_label=phenotype_label,
            )
            gkey = info["group_key"]
            if gkey not in rel_groups:
                rel_groups[gkey] = {
                    "group_key": gkey,
                    "rel_title": info["rel_title"],
                    "cause": info["cause"],
                    "effect_verb": info["effect_verb"],
                    "effect_badge": info["effect_badge"],
                    "dir_key": info["dir_key"],
                    "consequence": info["consequence"],
                    "arm_label": info["arm_label"],
                    "assessments": [],
                    "infos": [],
                    "pmids": set(),
                }
            p = str(a["pmid"])
            if p not in rel_groups[gkey]["pmids"]:
                rel_groups[gkey]["pmids"].add(p)
                rel_groups[gkey]["assessments"].append(a)
                rel_groups[gkey]["infos"].append(info)

        dir_order = {
            "increase": 0,
            "decrease": 1,
            "biphasic_or_state_dependent": 2,
            "no_effect": 3,
            "gene_environment_interaction": 4,
            "genetic_association": 5,
            "clinical_or_molecular_association": 6,
            "functional_modulation": 7,
            "mechanistic_pathway_synthesis": 8,
        }
        sorted_groups = sorted(
            rel_groups.values(),
            key=lambda g: (-len(g["pmids"]), dir_order.get(g["dir_key"], 99), g["rel_title"]),
        )

        if sorted_groups:
            rel_blocks: list[str] = ["### Relationships in Context"]
            for idx, grp in enumerate(sorted_groups, start=1):
                grp_assess = grp["assessments"]
                grp_infos = grp["infos"]
                sp_formatted = format_species_counts(grp_assess)

                design_counts: Counter[str] = Counter()
                tissues_seen: list[str] = []
                models_seen: list[str] = []
                for inf in grp_infos:
                    d_val = inf["design"]
                    if d_val and d_val not in ("unspecified", "unclear"):
                        design_counts[d_val] += 1
                    t_val = inf["tissue"]
                    if t_val and t_val not in tissues_seen:
                        tissues_seen.append(t_val)
                    m_val = inf["model"]
                    if m_val and m_val not in models_seen:
                        models_seen.append(m_val)

                ctx_lines = [
                    f"    - **Evidence Arm**: {grp['arm_label']}",
                    f"    - **Species**: {sp_formatted}",
                ]
                if design_counts:
                    des_str = ", ".join(f"{d} ({c})" for d, c in design_counts.most_common(6))
                    ctx_lines.append(f"    - **Study Designs**: {des_str}")
                if tissues_seen:
                    ctx_lines.append(f"    - **Anatomical / Cellular Sites**: {'; '.join(tissues_seen[:6])}")
                if models_seen:
                    ctx_lines.append(f"    - **Paradigms / Models**: {'; '.join(models_seen[:6])}")

                study_lines: list[str] = []
                for a, inf in zip(grp_assess, grp_infos):
                    p = str(a["pmid"])
                    art = articles_by_pmid.get(p)
                    cite_label = _author_year_label(art, p)
                    finding_text = _clean_finding_text(
                        a.get("finding") or "Confirmed relationship in screened record.",
                        a.get("concept_id") or "",
                    ).rstrip(".")
                    study_lines.append(
                        f"    - [{cite_label} (PMID {p})]({rel_prefix_to_pmid}/{p}.md): {finding_text} ({inf['context_str']})."
                    )

                block = (
                    f"#### {idx}. {grp['rel_title']}\n\n"
                    f"- **Context**:\n"
                    + "\n".join(ctx_lines)
                    + f"\n- **Supporting Studies ({len(study_lines)})**:\n"
                    + "\n".join(study_lines)
                )
                rel_blocks.append(block)

            paragraphs.append("\n\n".join(rel_blocks))

    if related_concepts:
        rel_links = []
        for other_cid, other_slug, shared_cnt in related_concepts[:6]:
            rel_links.append(f"[{other_cid}](./{other_slug}.md) ({shared_cnt} shared paper{'s' if shared_cnt > 1 else ''})")
        paragraphs.append(
            "### Cross-Concept Bridges\n\n"
            "Studies in this concept review also co-occur with the following concepts, allowing direct traversal "
            "across related domains: " + ", ".join(rel_links) + "."
        )

    return "\n\n".join(paragraphs), overview


def export_okf(store_or_workspace: Any, confirm: bool = False) -> dict[str, Any]:
    """Generate Google Open Knowledge Format Markdown files under okf/ for confirmed included references."""
    if hasattr(store_or_workspace, "base") and hasattr(store_or_workspace, "root"):
        store = store_or_workspace
    else:
        from wasp_core import Store
        store = Store(Path(store_or_workspace))

    if confirm and not is_okf_confirmed(store):
        try:
            store.log_human_decision(
                stage="okf_export",
                decision="Approved Open Knowledge Format (OKF) generation",
                rationale="User confirmed generation of OKF concept mini-reviews, reference notes, and Cytoscape graph tab.",
            )
        except Exception:
            pass

    okf_dir = store.root / "okf"
    concepts_dir = okf_dir / "concepts"
    okf_dir.mkdir(parents=True, exist_ok=True)
    concepts_dir.mkdir(parents=True, exist_ok=True)

    included_by_pmid = get_screened_in_records(store)
    articles_table = {str(a["pmid"]): a for a in store.table("articles")}

    articles_by_pmid: dict[str, dict[str, Any]] = {}
    for pmid, assessments in included_by_pmid.items():
        article = articles_table.get(pmid)
        if article is None:
            first_version = assessments[0].get("source_version")
            if first_version:
                try:
                    article = store.article(pmid, first_version)
                except Exception:
                    pass
        if article is not None:
            articles_by_pmid[pmid] = article

    context_file = store.base / "context.json"
    context = {}
    if context_file.exists():
        try:
            from wasp_core import load
            context = load(context_file)
        except Exception:
            pass

    genes_list = [g["symbol"] for g in context.get("genes", []) if isinstance(g, dict) and g.get("symbol")]
    genes_label = ", ".join(genes_list) if genes_list else "Target Gene"
    primary_gene = genes_list[0] if genes_list else "Gene"
    phenotype_label = context.get("phenotype", "Phenotype Review")
    phenotype_title = _title_case_phenotype(phenotype_label)
    timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    custom_narratives: dict[str, str] = {}
    narr_file = store.base / "okf_narratives.json"
    if narr_file.exists():
        try:
            raw_narr = json.loads(narr_file.read_text(encoding="utf-8"))
            if isinstance(raw_narr, dict):
                custom_narratives = {str(k): _sanitize_prose(str(v)) for k, v in raw_narr.items()}
        except Exception:
            pass

    # 1. Group assessments by Ontology Concept
    concept_assessments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pmid_to_concepts: dict[str, set[str]] = defaultdict(set)
    for pmid, assessments in included_by_pmid.items():
        for a in assessments:
            cid = str(a.get("concept_id") or "phenotype/direct").strip()
            cat, _ = parse_concept_category_and_name(cid)
            if cat != "emerging":
                concept_assessments[cid].append(a)
                pmid_to_concepts[pmid].add(cid)

    # 2. Discover or load Emerging Topics (category: "emerging")
    emerging_topics = _discover_emerging_topics(store, included_by_pmid, articles_by_pmid)
    pmid_to_emerging: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for et in emerging_topics:
        for p in et["pmids"]:
            if p in included_by_pmid:
                pmid_to_emerging[p].append(et)

    # Build unified dictionary of all Concept & Emerging Topic Review nodes
    all_mini_reviews: dict[str, dict[str, Any]] = {}
    for cid, assess_list in sorted(concept_assessments.items()):
        cat, short_name = parse_concept_category_and_name(cid)
        slug = concept_id_to_slug(cid)
        pmids_for_cid = sorted({str(a["pmid"]) for a in assess_list}, key=lambda x: int(x) if x.isdigit() else x)
        gene_pmids = sorted({str(a["pmid"]) for a in assess_list if not _is_phenotype_arm(a.get("gene"))}, key=lambda x: int(x) if x.isdigit() else x)
        pheno_pmids = sorted({str(a["pmid"]) for a in assess_list if _is_phenotype_arm(a.get("gene"))}, key=lambda x: int(x) if x.isdigit() else x)
        gc, pc = len(gene_pmids), len(pheno_pmids)
        ev_role = "overlap" if ((gc > 0 and pc > 0) or cid == "phenotype/direct") else ("gene_only" if gc > 0 else "phenotype_only")
        all_mini_reviews[cid] = {
            "concept_id": cid,
            "slug": slug,
            "category": cat,
            "name": short_name,
            "title": short_name.replace("_", " ").replace("-", " ").title() if short_name.upper() not in ("PTSD", "VTA") else short_name.upper(),
            "pmids": pmids_for_cid,
            "gene_pmids": gene_pmids,
            "phenotype_pmids": pheno_pmids,
            "gene_pmid_count": gc,
            "phenotype_pmid_count": pc,
            "evidence_role": ev_role,
            "assessments": assess_list,
            "narrative": custom_narratives.get(cid, ""),
            "is_emerging": False,
        }

    for et in emerging_topics:
        cid = et["concept_id"]
        et_pmids = [p for p in et["pmids"] if p in included_by_pmid]
        if not et_pmids:
            continue
        et_assess: list[dict[str, Any]] = []
        for p in et_pmids:
            p_list = included_by_pmid.get(p, [])
            if p_list:
                best_a = max(
                    p_list,
                    key=lambda row: (
                        0 if _is_phenotype_arm(row.get("gene")) else 1,
                        1 if str(row.get("direction") or "").lower() in ("increase", "decrease", "no_effect", "mixed") else 0,
                        len(_clean_finding_text(row.get("finding") or "", "emerging")),
                    ),
                )
                et_assess.append(best_a)
        gene_pmids = sorted({str(a["pmid"]) for a in et_assess if not _is_phenotype_arm(a.get("gene"))}, key=lambda x: int(x) if x.isdigit() else x)
        pheno_pmids = sorted({str(a["pmid"]) for a in et_assess if _is_phenotype_arm(a.get("gene"))}, key=lambda x: int(x) if x.isdigit() else x)
        gc, pc = len(gene_pmids), len(pheno_pmids)
        ev_role = "overlap" if (gc > 0 and pc > 0) else ("gene_only" if gc > 0 else "phenotype_only")
        all_mini_reviews[cid] = {
            "concept_id": cid,
            "slug": et["slug"],
            "category": "emerging",
            "name": et["name"],
            "title": et["title"],
            "pmids": et_pmids,
            "gene_pmids": gene_pmids,
            "phenotype_pmids": pheno_pmids,
            "gene_pmid_count": gc,
            "phenotype_pmid_count": pc,
            "evidence_role": ev_role,
            "assessments": et_assess,
            "narrative": custom_narratives.get(cid) or et.get("narrative", ""),
            "is_emerging": True,
        }

    # Compute Concept <-> Concept co-occurrence edges (shared PMIDs)
    concept_cooccurrence: dict[tuple[str, str], set[str]] = {}
    mr_keys = sorted(all_mini_reviews.keys())
    for i in range(len(mr_keys)):
        for j in range(i + 1, len(mr_keys)):
            c1, c2 = mr_keys[i], mr_keys[j]
            shared = set(all_mini_reviews[c1]["pmids"]) & set(all_mini_reviews[c2]["pmids"])
            if shared:
                concept_cooccurrence[(c1, c2)] = shared

    generated_files: list[Path] = []
    generated_concept_files: list[Path] = []

    # 3. Write Focused Concept & Emerging Topic Review Markdown files (`okf/concepts/<slug>.md`)
    for cid, mr in sorted(all_mini_reviews.items()):
        slug = mr["slug"]
        cat = mr["category"]
        is_emerging = mr["is_emerging"]
        assess_list = mr["assessments"]
        pmids_for_cid = mr["pmids"]
        gc = mr["gene_pmid_count"]
        pc = mr["phenotype_pmid_count"]
        ev_role = mr["evidence_role"]

        related_list: list[tuple[str, str, int]] = []
        for (c1, c2), shared_set in concept_cooccurrence.items():
            if c1 == cid:
                related_list.append((c2, all_mini_reviews[c2]["slug"], len(shared_set)))
            elif c2 == cid:
                related_list.append((c1, all_mini_reviews[c1]["slug"], len(shared_set)))
        related_list.sort(key=lambda x: (-x[2], x[0]))

        species_counter = summarize_species_counts(assess_list)
        direction_counter = Counter(
            str(a.get("direction") or "unspecified").strip().lower()
            for a in assess_list
        )
        unique_genes = sorted({str(a.get("gene") or primary_gene) for a in assess_list})

        prose_md, overview_info = _synthesize_concept_mini_review_prose(
            cid=cid,
            concept_title=mr["title"],
            category=cat,
            is_emerging=is_emerging,
            primary_gene=primary_gene,
            phenotype_label=phenotype_label,
            assessments=assess_list,
            articles_by_pmid=articles_by_pmid,
            related_concepts=related_list,
            custom_narrative=mr["narrative"],
            rel_prefix_to_pmid="..",
        )
        mr["summary_plain"] = overview_info["lead_plain"]
        mr["interaction_summary"] = overview_info["interaction_summary"]

        mr_frontmatter = {
            "type": "Concept",
            "title": f"{mr['title']} ({CATEGORY_TITLES.get(cat, cat)})",
            "concept_id": cid,
            "category": cat,
            "is_emerging": is_emerging,
            "evidence_role": ev_role,
            "genes": unique_genes,
            "pmid_count": len(pmids_for_cid),
            "gene_pmid_count": gc,
            "phenotype_pmid_count": pc,
            "pmids": pmids_for_cid,
            "species_breakdown": dict(species_counter),
            "direction_breakdown": dict(direction_counter),
            "related_concepts": [r[0] for r in related_list],
            "tags": ["open-knowledge-format", "concept-mini-review", cat, ev_role] + unique_genes,
            "created_at": timestamp_iso,
            "verified": True,
        }

        ev_table_lines = [
            "| Reference | Author (Year) | Arm | Species | Study Design | Direction | Target | Key Finding |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        quote_blocks: list[str] = []
        seen_pmid_assess: set[tuple[str, str]] = set()
        for a in assess_list:
            p = str(a["pmid"])
            raw_f_txt = str(a.get("finding") or "")
            f_txt = _clean_finding_text(raw_f_txt, str(a.get("concept_id") or ""))
            if (p, f_txt) in seen_pmid_assess:
                continue
            seen_pmid_assess.add((p, f_txt))
            art = articles_by_pmid.get(p)
            ay = _author_year_label(art, p)
            arm_cell = f"Phenotype Arm ({phenotype_title})" if _is_phenotype_arm(a.get("gene")) else f"Gene Arm ({primary_gene})"
            sp_list = parse_canonical_species(a.get("species"))
            sp = _clean_text_for_cell(", ".join(sp_list) or "unspecified")
            sd_raw = str(a.get("study_design") or "unspecified").strip().lower()
            sd_classified = _classify_study_design(
                sd_raw,
                f_txt,
                str(a.get("model") or a.get("model_or_paradigm") or ""),
                str(a.get("tissue_or_cell") or a.get("anatomical_or_cellular_context") or ""),
                sp_list,
            )
            sd = _clean_text_for_cell(sd_classified or "unspecified")
            dr = _clean_text_for_cell(a.get("direction") or "unspecified")
            dt = _clean_text_for_cell(a.get("direction_target") or "none")
            fd = _clean_text_for_cell(f_txt or "Included by screening")
            ev_table_lines.append(
                f"| [Reference {p}](../{p}.md) | {_clean_text_for_cell(ay)} | {_clean_text_for_cell(arm_cell)} | {sp} | {sd} | {dr} | {dt} | {fd} |"
            )
            q_txt = str(a.get("quotation") or "").strip()
            if q_txt:
                quote_blocks.append(f"- **[Reference {p} ({ay}, {arm_cell})](../{p}.md)**:\n  > {_sanitize_prose(q_txt)}")

        quotes_section = (
            "## Verbatim Supporting Quotations\n\n" + "\n\n".join(quote_blocks)
            if quote_blocks
            else "## Verbatim Supporting Quotations\n\nNo verbatim quotations recorded for this concept."
        )

        cat_heading = CATEGORY_TITLES.get(cat, cat.title())
        badge_type = "Emerging Topic Review" if is_emerging else "Ontology Concept Review"
        if ev_role == "overlap":
            role_desc = f"Gene x Phenotype Overlap ({gc} Gene Arm, {pc} Phenotype Arm)"
        elif ev_role == "gene_only":
            role_desc = f"Gene Arm ({gc} {primary_gene} papers)"
        else:
            role_desc = f"Phenotype Mechanism Arm ({pc} {phenotype_label} papers)"

        mr_md = f"""{to_yaml_frontmatter(mr_frontmatter)}# {mr['title']}

- **Review Type**: {badge_type}
- **Category**: {cat_heading} (`{cat}`)
- **Concept Identifier**: `{cid}`
- **Evidence Role**: {role_desc}
- **Supporting References**: {len(pmids_for_cid)}
- **Species Breakdown**: {format_species_counts(assess_list)}
- **Navigation**: [Open Knowledge Format index](../index.md)

## Concept Synthesis

{prose_md}

## Supporting Study Matrix

{chr(10).join(ev_table_lines)}

{quotes_section}
"""
        mr_md = _sanitize_prose(mr_md)
        mr_path = concepts_dir / f"{slug}.md"
        mr_path.write_text(mr_md, encoding="utf-8")
        generated_files.append(mr_path)
        generated_concept_files.append(mr_path)
        mr["markdown_body"] = mr_md

    # 4. Write Atomic Reference Notes (`okf/<PMID>.md`, type: Reference)
    index_rows: list[dict[str, Any]] = []
    pmid_preview_map: dict[str, dict[str, Any]] = {}

    for pmid in sorted(included_by_pmid.keys(), key=lambda x: int(x) if x.isdigit() else x):
        assessments = included_by_pmid[pmid]
        first_version = assessments[0].get("source_version")
        article = articles_by_pmid.get(pmid)

        raw_title = (article.get("title") if article else None) or f"Literature Reference {pmid}"
        clean_title = _sanitize_prose(re.sub(r"\s+", " ", raw_title).strip())
        journal_name = _sanitize_prose((article.get("journal") if article else None) or "Unknown Journal")
        doi_val = article.get("doi") if article else None
        pmcid_val = article.get("pmcid") if article else None
        authors_list = [_sanitize_prose(str(x)) for x in ((article.get("authors") if article else None) or [])]

        pub_year = ""
        pub_date_str = ""
        if article and article.get("publication_date"):
            pd = article["publication_date"]
            if isinstance(pd, dict):
                pub_year = str(pd.get("Year") or "")
                m = str(pd.get("Month") or "01")
                d = str(pd.get("Day") or "01")
                pub_date_str = f"{pub_year}-{m}-{d}" if pub_year else ""
            else:
                pub_date_str = str(pd)
                m_yr = re.search(r"\b(19\d\d|20\d\d)\b", pub_date_str)
                if m_yr:
                    pub_year = m_yr.group(1)

        unique_genes = sorted({str(a["gene"]) for a in assessments if a.get("gene")})
        unique_concepts = sorted({str(a["concept_id"]) for a in assessments if a.get("concept_id")})
        emerging_for_pmid = [et["concept_id"] for et in pmid_to_emerging.get(pmid, [])]
        unique_species_set: set[str] = set()
        for a in assessments:
            for sp_c in parse_canonical_species(a.get("species")):
                if sp_c != "unspecified":
                    unique_species_set.add(sp_c)
        unique_species = sorted(
            unique_species_set,
            key=lambda s: SPECIES_PRIORITY.index(s) if s in SPECIES_PRIORITY else 99,
        )
        unique_directions = sorted({str(a.get("direction") or "").strip().lower() for a in assessments if a.get("direction")})

        first_finding = next(
            (
                _clean_finding_text(str(a["finding"]), str(a.get("concept_id") or ""))
                for a in assessments
                if a.get("finding")
            ),
            clean_title,
        )
        short_desc = _sanitize_prose(re.sub(r"\s+", " ", first_finding).strip())
        if len(short_desc) > 160:
            short_desc = short_desc[:157] + "..."

        concept_tags = [c.replace("/", "-") for c in unique_concepts + emerging_for_pmid]
        tags = ["literature-reference", "screened-in"] + unique_genes + unique_species + concept_tags

        clean_assessments = []
        for a in assessments:
            sp_list = parse_canonical_species(a.get("species"))
            sp_norm = ", ".join(sp_list)
            raw_f = str(a.get("finding") or "")
            cleaned_f = _clean_finding_text(raw_f, str(a.get("concept_id") or ""))
            sd_raw = str(a.get("study_design") or "").strip().lower()
            sd_classified = _classify_study_design(
                sd_raw,
                cleaned_f,
                str(a.get("model") or a.get("model_or_paradigm") or ""),
                str(a.get("tissue_or_cell") or a.get("anatomical_or_cellular_context") or ""),
                sp_list,
            ) if sd_raw else None
            entry = {
                "gene": a.get("gene"),
                "concept": a.get("concept_id"),
                "decision": "include",
                "species": sp_norm or a.get("species"),
                "study_design": sd_classified or a.get("study_design"),
                "direction": a.get("direction"),
                "direction_target": a.get("direction_target"),
                "finding": _sanitize_prose(cleaned_f) if cleaned_f else None,
                "quotation": _sanitize_prose(str(a.get("quotation"))) if a.get("quotation") else None,
            }
            clean_assessments.append({k: v for k, v in entry.items() if v is not None})

        frontmatter = {
            "type": "Reference",
            "title": clean_title,
            "description": short_desc,
            "resource": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "pmid": str(pmid),
            "doi": doi_val,
            "pmcid": pmcid_val,
            "journal": journal_name,
            "publication_year": pub_year or None,
            "publication_date": pub_date_str or None,
            "authors": authors_list,
            "genes": unique_genes,
            "concepts": unique_concepts,
            "emerging_topics": emerging_for_pmid,
            "species": unique_species,
            "directions": unique_directions,
            "tags": tags,
            "screening": {
                "decision": "include",
                "assessments": clean_assessments,
            },
            "created_at": timestamp_iso,
            "verified": True,
        }

        linked_mr_lines: list[str] = []
        for cid in unique_concepts + emerging_for_pmid:
            if cid in all_mini_reviews:
                mr = all_mini_reviews[cid]
                cat_label = CATEGORY_TITLES.get(mr["category"], mr["category"])
                linked_mr_lines.append(
                    f"- [{mr['title']} ({cat_label})](./concepts/{mr['slug']}.md)"
                )
        if not linked_mr_lines:
            linked_mr_lines.append("- [Open Knowledge Format index](./index.md)")

        assess_blocks = []
        for idx, a in enumerate(assessments, start=1):
            g = str(a.get("gene", "N/A"))
            is_ph = _is_phenotype_arm(g)
            target_header = f"Phenotype {phenotype_title}" if is_ph else f"Gene {g}"
            c = str(a.get("concept_id", "N/A"))
            raw_f = str(a.get("finding", "Included based on review screening criteria."))
            f = _sanitize_prose(_clean_finding_text(raw_f, c))
            sp_list = parse_canonical_species(a.get("species"))
            sp = ", ".join(sp_list) or "Not recorded"
            sd_raw = str(a.get("study_design") or "").strip().lower()
            sd = (
                _classify_study_design(
                    sd_raw,
                    f,
                    str(a.get("model") or a.get("model_or_paradigm") or ""),
                    str(a.get("tissue_or_cell") or a.get("anatomical_or_cellular_context") or ""),
                    sp_list,
                )
                if sd_raw
                else "Not recorded"
            )
            dir_str = a.get("direction")
            target_str = a.get("direction_target")
            quote = _sanitize_prose(str(a.get("quotation") or "").strip())

            c_link = f"[{c}](./concepts/{all_mini_reviews[c]['slug']}.md)" if c in all_mini_reviews else f"`{c}`"
            block_lines = [
                f"### Assessment {idx}: {target_header} across Concept {c}",
                "",
                f"- **Target**: {g}",
                f"- **Concept Review**: {c_link}",
                "- **Decision**: Included",
                f"- **Species Scope**: {sp}",
                f"- **Study Design**: {sd}",
            ]
            if dir_str:
                block_lines.append(f"- **Direction of Effect**: {dir_str}")
            if target_str:
                block_lines.append(f"- **Direction Target**: {target_str}")
            block_lines.append(f"- **Key Finding**: {f}")
            if quote:
                block_lines.extend([
                    "- **Supporting Quotation**:",
                    f"  > {quote}",
                ])
            assess_blocks.append("\n".join(block_lines))

        assessments_md = "\n\n".join(assess_blocks)

        related_pmids: set[str] = set()
        for cid in unique_concepts + emerging_for_pmid:
            if cid in all_mini_reviews:
                for other_p in all_mini_reviews[cid]["pmids"]:
                    if other_p != pmid:
                        related_pmids.add(other_p)
        related_pmid_lines: list[str] = []
        for rp in sorted(related_pmids, key=lambda x: int(x) if x.isdigit() else x)[:10]:
            r_art = articles_by_pmid.get(rp)
            r_ay = _author_year_label(r_art, rp)
            r_title = _sanitize_prose((r_art.get("title") if r_art else None) or f"Reference {rp}")
            related_pmid_lines.append(f"- [Reference {rp} ({r_ay})](./{rp}.md): {r_title}")
        related_refs_md = (
            "\n".join(related_pmid_lines)
            if related_pmid_lines
            else "- No co-occurring references in the same concept review."
        )

        authors_str = ", ".join(authors_list) if authors_list else "Authors not listed"
        doi_line = f"[{doi_val}](https://doi.org/{doi_val})" if doi_val else "Not listed"
        genes_str = ", ".join(unique_genes) if unique_genes else "None"
        concepts_str = ", ".join(unique_concepts) if unique_concepts else "None"

        ref_doc_md = f"""{to_yaml_frontmatter(frontmatter)}# {clean_title}

- **PMID**: [{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)
- **DOI**: {doi_line}
- **Journal**: {journal_name} ({pub_year or 'N/A'})
- **Authors**: {authors_str}
- **Genes Evaluated**: {genes_str}
- **Concepts Evaluated**: {concepts_str}

## Linked Concept and Emerging Topic Reviews

{chr(10).join(linked_mr_lines)}

## Screening and Evidence Assessment

The following findings and supporting evidence were confirmed during systematic screening:

{assessments_md}

## Connected References in Knowledge Graph

{related_refs_md}

## Provenance and Open Knowledge Format Metadata

- **Specification**: [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
- **Concept Type**: `Reference`
- **Review Workspace**: `{store.root.name}`
- **Source Record Version**: `{first_version or 'N/A'}`
- **Verification Status**: Confirmed by systematic screening
- **Navigation**: [Open Knowledge Format index](./index.md)
"""
        ref_doc_md = _sanitize_prose(ref_doc_md)
        ref_file = okf_dir / f"{pmid}.md"
        ref_file.write_text(ref_doc_md, encoding="utf-8")
        generated_files.append(ref_file)

        index_rows.append({
            "pmid": pmid,
            "author_year": _author_year_label(article, pmid),
            "title": clean_title,
            "journal_year": f"{journal_name} ({pub_year})" if pub_year else journal_name,
            "genes": genes_str,
            "concepts": concepts_str,
            "species": ", ".join(unique_species) if unique_species else "unspecified",
            "directions": ", ".join(unique_directions) if unique_directions else "unspecified",
            "finding": short_desc,
        })
        pmid_preview_map[pmid] = {
            "pmid": pmid,
            "title": clean_title,
            "author_year": _author_year_label(article, pmid),
            "journal_year": f"{journal_name} ({pub_year})" if pub_year else journal_name,
            "authors": authors_str,
            "doi": doi_val,
            "genes": unique_genes,
            "concepts": unique_concepts,
            "emerging_topics": emerging_for_pmid,
            "species": unique_species or ["unspecified"],
            "directions": unique_directions or ["unspecified"],
            "assessments": clean_assessments,
        }

    # 5. Build `okf/index.md` organized by Overlap Summary Table + Top-Level Ontology Categories + Emerging Topics
    index_frontmatter = {
        "type": "Index",
        "title": f"Open Knowledge Format Synthesis: {genes_label} and {phenotype_label}",
        "description": "Ontology-structured concept reviews, emerging topics, and confirmed reference notes in Google Open Knowledge Format.",
        "tags": ["open-knowledge-format", "literature-review", "screened-evidence", "concept-reviews"] + genes_list,
        "created_at": timestamp_iso,
        "verified": True,
    }

    category_sections: list[str] = []
    for cat in CATEGORY_ORDER:
        cat_mrs = [mr for mr in all_mini_reviews.values() if mr["category"] == cat]
        if not cat_mrs:
            continue
        cat_title = CATEGORY_TITLES.get(cat, cat.title())
        cat_lines = [
            f"### {cat_title} (`{cat}`)",
            "",
        ]
        if cat == "emerging":
            cat_lines.extend([
                "This section captures higher-order emergent themes, off-ontology paralog comparisons, cell-type Cre driver "
                "dissociations, and auxiliary molecular complexes discovered across screened studies.",
                "",
            ])
        cat_lines.extend([
            "| Review Topic | Evidence Role | Supporting Papers | Species | Mechanistic Overlap / Synthesis Summary | Linked References |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for mr in sorted(cat_mrs, key=lambda x: (-len(x["pmids"]), x["title"])):
            sp_formatted = format_species_counts(mr["assessments"])
            summary_cell = _clean_text_for_cell(mr["interaction_summary"] or mr["summary_plain"])
            ref_links = ", ".join(f"[PMID {p}](./{p}.md)" for p in mr["pmids"][:8])
            if len(mr["pmids"]) > 8:
                ref_links += f" (+{len(mr['pmids']) - 8} more)"
            if mr["evidence_role"] == "overlap":
                role_cell = f"Overlap ({mr['gene_pmid_count']}G / {mr['phenotype_pmid_count']}P)"
            elif mr["evidence_role"] == "gene_only":
                role_cell = f"Gene Arm ({mr['gene_pmid_count']}G)"
            else:
                role_cell = f"Phenotype Arm ({mr['phenotype_pmid_count']}P)"
            cat_lines.append(
                f"| [{_clean_text_for_cell(mr['title'])}](./concepts/{mr['slug']}.md) "
                f"| {role_cell} "
                f"| {len(mr['pmids'])} "
                f"| {_clean_text_for_cell(sp_formatted)} "
                f"| {summary_cell} "
                f"| {ref_links} |"
            )
        cat_lines.append("")
        category_sections.append("\n".join(cat_lines))

    if not category_sections:
        category_sections.append("No confirmed included references or concept reviews have been generated yet.")

    if index_rows:
        table_lines = [
            "| PMID | Author (Year) | Title | Species | Direction | Concept(s) | Key Finding | Reference Note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in index_rows:
            table_lines.append(
                f"| [{r['pmid']}](./{r['pmid']}.md) | {_clean_text_for_cell(r['author_year'])} "
                f"| {_clean_text_for_cell(r['title'])} | {_clean_text_for_cell(r['species'])} "
                f"| {_clean_text_for_cell(r['directions'])} | {_clean_text_for_cell(r['concepts'])} "
                f"| {_clean_text_for_cell(r['finding'])} | [Reference {r['pmid']}](./{r['pmid']}.md) |"
            )
        table_md = "\n".join(table_lines)
    else:
        table_md = "No references have been confirmed as included in this review workspace."

    ont_mr_count = sum(1 for mr in all_mini_reviews.values() if not mr["is_emerging"])
    em_mr_count = sum(1 for mr in all_mini_reviews.values() if mr["is_emerging"])
    overlap_total_count = sum(1 for mr in all_mini_reviews.values() if mr["evidence_role"] == "overlap")

    index_md = f"""{to_yaml_frontmatter(index_frontmatter)}# Open Knowledge Format (OKF): {genes_label} in {phenotype_label}

- **Review Workspace**: `{store.root.name}`
- **Target Gene(s)**: {genes_label}
- **Phenotype Scope**: {phenotype_label}
- **Ontology Concept Reviews**: {ont_mr_count} ({overlap_total_count} Gene x Phenotype Overlap Concepts)
- **Emerging Topic Reviews**: {em_mr_count}
- **Confirmed Reference Notes**: {len(index_rows)}
- **Specification Reference**: [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)

This knowledge base organizes confirmed included literature from both the **Target Gene Arm ({genes_label})** and the **Phenotype Mechanism Arm ({phenotype_label})**, alongside **Human GWAS Catalog associations**, into a Dual-Hub network designed for visual graph exploration and mechanistic overlap identification:
1. **Focused Concept and Emerging Topic Reviews**: Synthesized before graph construction to capture gene-arm relationships, phenotype-mechanism relationships, and candidate points of interaction where gene and phenotype pathways intersect.
2. **Atomic Reference Notes**: Record per-study bibliographic metadata, screening assessments, verbatim quotes, and cross-links.

## Ontology and Emerging Topic Reviews

Across the **{ont_mr_count} ontology concepts** and **{em_mr_count} emerging topic reviews** below, **{overlap_total_count} concepts** contain confirmed evidence from both the **{primary_gene} Gene Arm** and the **{phenotype_title} Mechanism Arm** (marked as `Overlap (G / P)`). Expand any category below to inspect each concept's candidate point of interaction, species breakdown, and linked reference notes.

{chr(10).join(category_sections)}

## Atomic Reference Notes ({len(index_rows)})

{table_md}
"""
    index_md = _sanitize_prose(index_md)
    index_file = okf_dir / "index.md"
    index_file.write_text(index_md, encoding="utf-8")
    generated_files.append(index_file)

    # 6. Build Cytoscape.js Graph Specification (`corpus/okf_graph.json`)
    gwas_records = store.table("association_evidence") if hasattr(store, "table") else []
    graph_data = _build_cytoscape_graph_data(
        primary_gene=primary_gene,
        genes_list=genes_list,
        phenotype_label=phenotype_label,
        all_mini_reviews=all_mini_reviews,
        concept_cooccurrence=concept_cooccurrence,
        pmid_preview_map=pmid_preview_map,
        gwas_records=gwas_records,
    )
    graph_file = store.base / "okf_graph.json"
    graph_file.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 7. Clean up obsolete .md files in okf/ and okf/concepts/
    active_root_names = {f.name for f in generated_files if f.parent == okf_dir}
    for existing_file in okf_dir.glob("*.md"):
        if existing_file.name not in active_root_names:
            try:
                existing_file.unlink()
            except OSError:
                pass

    active_concept_names = {f.name for f in generated_concept_files}
    for existing_cfile in concepts_dir.glob("*.md"):
        if existing_cfile.name not in active_concept_names:
            try:
                existing_cfile.unlink()
            except OSError:
                pass
            html_sibling = existing_cfile.with_suffix(".html")
            if html_sibling.exists():
                try:
                    html_sibling.unlink()
                except OSError:
                    pass

    return {
        "workspace": str(store.root),
        "okf_dir": str(okf_dir),
        "included_count": len(index_rows),
        "concept_mini_reviews_count": ont_mr_count,
        "emerging_topics_count": em_mr_count,
        "overlap_concepts_count": overlap_total_count,
        "graph_json": str(graph_file),
        "generated_files": [str(f) for f in generated_files],
    }


def _build_cytoscape_graph_data(
    primary_gene: str,
    genes_list: list[str],
    phenotype_label: str,
    all_mini_reviews: dict[str, dict[str, Any]],
    concept_cooccurrence: dict[tuple[str, str], set[str]],
    pmid_preview_map: dict[str, dict[str, Any]],
    gwas_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct Dual-Hub Bipartite nodes, edges, colors, and side-panel preview payloads for the Cytoscape.js visualizer."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    pheno_title = _title_case_phenotype(phenotype_label)
    gene_connected_count = sum(1 for mr in all_mini_reviews.values() if mr["gene_pmid_count"] > 0)
    pheno_connected_count = sum(1 for mr in all_mini_reviews.values() if mr["phenotype_pmid_count"] > 0 or mr["concept_id"] == "phenotype/direct")
    overlap_count = sum(1 for mr in all_mini_reviews.values() if mr["evidence_role"] == "overlap")
    pheno_unique_pmids = len({
        p for mr in all_mini_reviews.values() for p in mr.get("phenotype_pmids", [])
    })

    # 1. Left Target Gene Hub Node
    gene_id = f"gene:{primary_gene}"
    gene_bio_label = "proprotein convertase biology" if primary_gene.upper() == "FURIN" else "channel biology"
    nodes.append({
        "data": {
            "id": gene_id,
            "label": primary_gene,
            "node_type": "gene",
            "evidence_role": "gene_hub",
            "category": "gene",
            "color": CATEGORY_COLORS["gene"],
            "size": 68,
            "species": ["human", "rat", "mouse"],
            "directions": ["increase", "decrease", "no_effect", "mixed"],
            "title": f"Target Gene Hub: {', '.join(genes_list or [primary_gene])}",
            "subtitle": f"Connected to {gene_connected_count} Concept Reviews ({overlap_count} shared with {pheno_title})",
            "summary": (
                f"Primary candidate gene hub ({primary_gene}) linking baseline {gene_bio_label}, "
                f"human GWAS loci, and {gene_connected_count} ontology/emerging concept reviews across the literature corpus."
            ),
            "note_url": "./gene-function.html",
        }
    })

    # 2. Right Phenotype Mechanism Hub Node
    pheno_hub_id = "phenotype:hub"
    nodes.append({
        "data": {
            "id": pheno_hub_id,
            "label": pheno_title,
            "node_type": "phenotype_hub",
            "evidence_role": "phenotype_hub",
            "category": "phenotype",
            "color": CATEGORY_COLORS["phenotype"],
            "size": 68,
            "species": ["human", "rat", "mouse"],
            "directions": ["increase", "decrease", "no_effect", "mixed"],
            "title": f"Phenotype Mechanism Hub: {pheno_title}",
            "subtitle": f"{pheno_connected_count} Concept Reviews | {pheno_unique_pmids} Phenotype-Arm Studies | {overlap_count} Overlap Domains",
            "summary": (
                f"Target phenotype mechanism hub representing neural circuits, cellular populations, and signaling "
                f"pathways that govern {phenotype_label}. Intersects with {primary_gene} across {overlap_count} shared "
                f"ontology concepts in the center overlap zone."
            ),
            "note_url": "./synthesis.html",
        }
    })

    # 3. Human GWAS Hub Node (connected to Gene Hub)
    gwas_list = gwas_records or []
    gwas_count = len(gwas_list)
    gwas_preview_items = []
    for rec in gwas_list:
        rsid = str(rec.get("rsid") or rec.get("variant_id") or "N/A")
        trait = str(rec.get("reported_trait") or rec.get("trait") or "trait")
        pval = str(rec.get("p_value") or "NR")
        eff = str(rec.get("effect_size") or rec.get("or_or_beta") or "NR")
        g_pmid = str(rec.get("pmid") or "")
        gwas_preview_items.append({
            "pmid": g_pmid,
            "author_year": f"rsID {rsid} (GWAS)",
            "species": "human",
            "study_design": "human_gwas_catalog",
            "direction": f"p = {pval}",
            "direction_target": trait if trait != "trait" else "",
            "finding": f"Lead variant {rsid} associated with {trait} (p = {pval}, effect = {eff}).",
            "quotation": "",
        })
    nodes.append({
        "data": {
            "id": "gwas:hub",
            "label": f"{primary_gene} Human GWAS ({gwas_count})",
            "node_type": "gwas_hub",
            "evidence_role": "gwas_hub",
            "category": "psychiatric",
            "color": "#a3be8c",
            "size": 48,
            "pmid_count": gwas_count,
            "species": ["human"],
            "directions": ["increase", "decrease", "mixed"],
            "title": f"Human GWAS Catalog Associations: {primary_gene}",
            "subtitle": f"{gwas_count} Genome-Wide Significant Associations (NHGRI-EBI GWAS Catalog)",
            "summary": (
                f"NHGRI-EBI GWAS Catalog records for {primary_gene} ({gwas_count} total associations). "
                "Dominant human traits: neuropsychiatric and physiological traits."
            ),
            "assessments": gwas_preview_items,
            "note_url": "./gwas-associations.html",
        }
    })
    edges.append({
        "data": {
            "id": f"e:{gene_id}->gwas:hub",
            "source": gene_id,
            "target": "gwas:hub",
            "edge_type": "gene_gwas",
            "category": "psychiatric",
            "color": "#a3be8c",
            "weight": 3.5,
            "pmid_count": gwas_count,
            "label": str(gwas_count),
        }
    })

    active_categories = sorted(
        {mr["category"] for mr in all_mini_reviews.values()},
        key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99,
    )

    # 4. Concept & Emerging Topic Review Nodes + Dual-Hub Edges
    sorted_mrs = sorted(
        all_mini_reviews.items(),
        key=lambda kv: (
            CATEGORY_ORDER.index(kv[1]["category"]) if kv[1]["category"] in CATEGORY_ORDER else 99,
            -len(kv[1]["pmids"]),
            kv[1]["title"],
        ),
    )
    for cid, mr in sorted_mrs:
        cat = mr["category"]
        c_node_id = f"concept:{cid}"
        c_pmids = mr["pmids"]
        gc = mr["gene_pmid_count"]
        pc = mr["phenotype_pmid_count"]
        ev_role = mr["evidence_role"]
        c_sp_counts = summarize_species_counts(mr["assessments"])
        c_sp = list(c_sp_counts.keys())
        c_sp_summary = format_species_counts(mr["assessments"])
        c_dir = sorted({str(a.get("direction") or "unspecified").lower() for a in mr["assessments"] if a.get("direction")})
        node_size = min(64, 20 + int((len(c_pmids) ** 0.52) * 3.6))
        cat_color = CATEGORY_COLORS.get(cat, "#88c0d0")
        cat_title = "Emerging Topic" if mr["is_emerging"] else CATEGORY_TITLES.get(cat, cat)

        if ev_role == "overlap":
            subtitle = f"{cat_title} | Gene x Phenotype Overlap ({gc} {primary_gene}, {pc} {pheno_title})"
        elif ev_role == "gene_only":
            subtitle = f"{cat_title} | Gene Arm ({len(c_pmids)} Papers)"
        else:
            subtitle = f"{cat_title} | Phenotype Mechanism Arm ({len(c_pmids)} Papers)"

        preview_items = []
        seen_pf = set()
        for a in mr["assessments"]:
            p = str(a["pmid"])
            raw_f_txt = str(a.get("finding") or "")
            f_txt = _clean_finding_text(raw_f_txt, str(a.get("concept_id") or ""))
            if (p, f_txt) in seen_pf:
                continue
            seen_pf.add((p, f_txt))
            p_info = pmid_preview_map.get(p, {})
            sp_list = parse_canonical_species(a.get("species"))
            sd_raw = str(a.get("study_design") or "unspecified").strip().lower()
            sd_classified = _classify_study_design(
                sd_raw,
                f_txt,
                str(a.get("model") or a.get("model_or_paradigm") or ""),
                str(a.get("tissue_or_cell") or a.get("anatomical_or_cellular_context") or ""),
                sp_list,
            )
            preview_items.append({
                "pmid": p,
                "author_year": p_info.get("author_year", f"PMID {p}"),
                "arm": pheno_title if _is_phenotype_arm(a.get("gene")) else primary_gene,
                "species": ", ".join(sp_list) or "unspecified",
                "study_design": sd_classified or "unspecified",
                "direction": a.get("direction") or "unspecified",
                "direction_target": a.get("direction_target") or "",
                "finding": _sanitize_prose(f_txt),
                "quotation": _sanitize_prose(str(a.get("quotation") or "")),
            })

        nodes.append({
            "data": {
                "id": c_node_id,
                "label": f"{mr['title']} ({len(c_pmids)})",
                "concept_id": cid,
                "slug": mr["slug"],
                "node_type": "emerging_concept" if mr["is_emerging"] else "concept",
                "evidence_role": ev_role,
                "category": cat,
                "is_emerging": mr["is_emerging"],
                "color": cat_color,
                "size": node_size,
                "pmid_count": len(c_pmids),
                "gene_pmid_count": gc,
                "phenotype_pmid_count": pc,
                "species": c_sp or ["unspecified"],
                "species_summary": c_sp_summary,
                "directions": c_dir or ["unspecified"],
                "title": mr["title"],
                "subtitle": subtitle,
                "summary": mr.get("summary_plain") or mr["narrative"] or f"Focused review synthesizing {len(c_pmids)} confirmed study record(s) for {mr['title']}.",
                "interaction_summary": mr.get("interaction_summary", ""),
                "assessments": preview_items,
                "pmids": c_pmids,
                "note_url": f"./okf/concepts/{mr['slug']}.html",
                "md_url": f"./okf/concepts/{mr['slug']}.md",
            }
        })

        if gc > 0:
            edges.append({
                "data": {
                    "id": f"e:{gene_id}->{c_node_id}",
                    "source": gene_id,
                    "target": c_node_id,
                    "edge_type": "gene_concept",
                    "category": cat,
                    "color": cat_color,
                    "weight": round(max(1.8, min(7.5, 1.8 + (gc ** 0.42) * 1.0)), 2),
                    "pmid_count": gc,
                    "label": str(gc),
                }
            })
        if pc > 0 or cid == "phenotype/direct":
            p_edge_cnt = pc if pc > 0 else gc
            edges.append({
                "data": {
                    "id": f"e:{pheno_hub_id}->{c_node_id}",
                    "source": pheno_hub_id,
                    "target": c_node_id,
                    "edge_type": "phenotype_concept",
                    "category": cat,
                    "color": CATEGORY_COLORS["phenotype"],
                    "weight": round(max(1.8, min(7.5, 1.8 + (p_edge_cnt ** 0.42) * 1.0)), 2),
                    "pmid_count": p_edge_cnt,
                    "label": str(p_edge_cnt),
                }
            })

    # 5. Atomic PMID Reference Leaf Nodes + Concept -> PMID Edges
    for pmid, p_info in sorted(pmid_preview_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        p_node_id = f"pmid:{pmid}"
        primary_dir = (p_info["directions"][0] if p_info["directions"] else "unspecified").lower()
        primary_sp = (p_info["species"][0] if p_info["species"] else "unspecified").lower()

        first_cid = (p_info["concepts"] + p_info["emerging_topics"] or ["phenotype/direct"])[0]
        first_cat = all_mini_reviews.get(first_cid, {}).get("category", "pmid")
        node_color = CATEGORY_COLORS.get(first_cat, CATEGORY_COLORS["pmid"])

        nodes.append({
            "data": {
                "id": p_node_id,
                "label": p_info["author_year"],
                "pmid": pmid,
                "node_type": "pmid",
                "category": first_cat,
                "color": node_color,
                "size": 22,
                "species": p_info["species"],
                "primary_species": primary_sp,
                "directions": p_info["directions"],
                "primary_direction": primary_dir,
                "title": p_info["title"],
                "subtitle": f"PMID {pmid} | {p_info['journal_year']}",
                "authors": p_info["authors"],
                "doi": p_info["doi"],
                "assessments": p_info["assessments"],
                "concepts": [
                    {
                        "id": f"concept:{c}",
                        "concept_id": c,
                        "title": all_mini_reviews[c]["title"],
                        "slug": all_mini_reviews[c]["slug"],
                        "category": all_mini_reviews[c]["category"],
                    }
                    for c in (p_info["concepts"] + p_info["emerging_topics"])
                    if c in all_mini_reviews
                ],
                "note_url": f"./okf/{pmid}.html",
                "md_url": f"./okf/{pmid}.md",
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        })

        for cid in p_info["concepts"] + p_info["emerging_topics"]:
            if cid in all_mini_reviews:
                pair_dir = next(
                    (a.get("direction") for a in p_info["assessments"] if a.get("concept") == cid and a.get("direction")),
                    primary_dir,
                )
                edges.append({
                    "data": {
                        "id": f"e:concept:{cid}->pmid:{pmid}",
                        "source": f"concept:{cid}",
                        "target": p_node_id,
                        "edge_type": "concept_pmid",
                        "direction": str(pair_dir or "unspecified").lower(),
                        "weight": 1,
                        "label": str(pair_dir or "") if pair_dir and pair_dir not in ("unspecified", "none") else "",
                    }
                })

    return {
        "gene": primary_gene,
        "genes": genes_list,
        "phenotype": phenotype_label,
        "category_colors": CATEGORY_COLORS,
        "category_titles": CATEGORY_TITLES,
        "active_categories": active_categories,
        "nodes": nodes,
        "edges": edges,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Export confirmed references and mini-reviews to Google Open Knowledge Format.")
    parser.add_argument("workspace", help="Path to wasp-lit research workspace")
    parser.add_argument("--confirm", action="store_true", help="Record human confirmation for OKF export")
    args = parser.parse_args(argv)

    res = export_okf(args.workspace, confirm=args.confirm)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
