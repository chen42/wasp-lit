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
    """Load explicit emerging topics and auto-discover emerging cross-domain themes from screened evidence."""
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

    # 3. Auto-discover cross-category bridges (papers that connect >= 2 distinct ontology categories)
    multi_cat_pmids: list[str] = []
    bridged_categories: set[str] = set()
    for pmid, assessments in included_by_pmid.items():
        cats = {parse_concept_category_and_name(a.get("concept_id", ""))[0] for a in assessments}
        cats.discard("emerging")
        if len(cats) >= 2:
            multi_cat_pmids.append(pmid)
            bridged_categories.update(cats)

    if multi_cat_pmids and "emerging/cross-domain-mechanistic-convergence" not in topics_by_id:
        cat_labels = ", ".join(sorted(bridged_categories))
        topics_by_id["emerging/cross-domain-mechanistic-convergence"] = {
            "concept_id": "emerging/cross-domain-mechanistic-convergence",
            "slug": "emerging--cross-domain-mechanistic-convergence",
            "category": "emerging",
            "name": "cross-domain-mechanistic-convergence",
            "title": "Cross-Domain Mechanistic Convergence",
            "pmids": sorted(set(multi_cat_pmids), key=lambda x: int(x) if x.isdigit() else x),
            "narrative": (
                f"This emerging topic captures studies that bridge multiple ontology categories ({cat_labels}) "
                "within the same experimental investigation, linking molecular or cellular mechanisms directly to "
                "circuit-level or behavioral addiction phenotypes."
            ),
            "is_emerging": True,
            "source": "auto-discovered",
        }

    # 4. Auto-discover shared molecular/physiological direction targets across papers
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
        # Create an emerging topic if a specific target is investigated across papers or when no other emerging topic exists
        if len(pset) >= 2 or (not topics_by_id and len(pset) >= 1):
            cid = f"emerging/target-{norm_dt}"
            if cid not in topics_by_id:
                label = target_display[norm_dt]
                topics_by_id[cid] = {
                    "concept_id": cid,
                    "slug": concept_id_to_slug(cid),
                    "category": "emerging",
                    "name": f"target-{norm_dt}",
                    "title": f"Emerging Readout: {label}",
                    "pmids": sorted(pset, key=lambda x: int(x) if x.isdigit() else x),
                    "narrative": (
                        f"This emerging topic synthesizes evidence specifically measuring {label} as a functional readout "
                        "across screened studies."
                    ),
                    "is_emerging": True,
                    "source": "auto-discovered",
                }
                if len(topics_by_id) >= 4:
                    break

    # 5. Auto-discover translational / cross-species concordance if multiple species are represented
    species_to_pmids: dict[str, set[str]] = defaultdict(set)
    for pmid, assessments in included_by_pmid.items():
        for a in assessments:
            sp = str(a.get("species") or "").strip().lower()
            if sp and sp not in ("none", "n/a", "unspecified", "not recorded"):
                species_to_pmids[sp].add(pmid)
    if len(species_to_pmids) >= 2 and "emerging/cross-species-translational-concordance" not in topics_by_id:
        all_sp_pmids = sorted(
            {p for pset in species_to_pmids.values() for p in pset},
            key=lambda x: int(x) if x.isdigit() else x,
        )
        sp_summary = ", ".join(f"{sp} (n={len(pset)})" for sp, pset in sorted(species_to_pmids.items()))
        topics_by_id["emerging/cross-species-translational-concordance"] = {
            "concept_id": "emerging/cross-species-translational-concordance",
            "slug": "emerging--cross-species-translational-concordance",
            "category": "emerging",
            "name": "cross-species-translational-concordance",
            "title": "Cross-Species Translational Concordance",
            "pmids": all_sp_pmids,
            "narrative": (
                f"This emerging topic compares findings across multiple model organisms and human studies ({sp_summary}) "
                "to evaluate translational consistency."
            ),
            "is_emerging": True,
            "source": "auto-discovered",
        }

    return list(topics_by_id.values())


def _author_year_label(article: dict[str, Any] | None, pmid: str) -> str:
    """Return 'FirstAuthor et al., Year' or 'Author, Year' for prose citations."""
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


def _synthesize_concept_mini_review_prose(
    concept_title: str,
    category: str,
    is_emerging: bool,
    assessments: list[dict[str, Any]],
    articles_by_pmid: dict[str, dict[str, Any]],
    related_concepts: list[tuple[str, str, int]],
    custom_narrative: str = "",
    rel_prefix_to_pmid: str = "..",
) -> str:
    """Build a focused, cohesive mini-review narrative with inline [Author (Year)](../<PMID>.md) links."""
    unique_pmids = sorted({str(a["pmid"]) for a in assessments}, key=lambda x: int(x) if x.isdigit() else x)
    genes = sorted({str(a.get("gene") or "target gene") for a in assessments})
    genes_str = ", ".join(genes)

    species_counts = Counter(
        str(a.get("species") or "unspecified").strip().lower()
        for a in assessments
        if a.get("species")
    )
    design_counts = Counter(
        str(a.get("study_design") or "experimental study").strip()
        for a in assessments
        if a.get("study_design")
    )
    dir_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in assessments:
        d = str(a.get("direction") or "unspecified").strip().lower()
        dir_groups[d].append(a)

    paragraphs: list[str] = []

    if custom_narrative.strip():
        paragraphs.append(_sanitize_prose(custom_narrative.strip()))

    # Paragraph 1: Scope, species, and study designs
    sp_text = ", ".join(f"{sp} ({cnt})" for sp, cnt in species_counts.most_common()) if species_counts else "unspecified species"
    des_text = ", ".join(f"{d} ({cnt})" for d, cnt in design_counts.most_common(4)) if design_counts else "screened studies"
    domain_type = "emerging cross-domain theme" if is_emerging else f"ontology concept under {CATEGORY_TITLES.get(category, category)}"
    p1 = (
        f"Across the screened literature corpus for {genes_str}, {len(unique_pmids)} confirmed study record(s) "
        f"address **{concept_title}** ({domain_type}). "
        f"Evidence spans {sp_text}, using study designs that include {des_text}."
    )
    paragraphs.append(_sanitize_prose(p1))

    # Paragraph 2: Findings grouped by direction of effect and mechanistic readout
    finding_sentences: list[str] = []
    for direction_key in ("increase", "decrease", "mixed", "no_effect", "unspecified", "none"):
        group = dir_groups.get(direction_key, [])
        if not group:
            continue
        seen_pmids_in_group: set[str] = set()
        for a in group:
            p = str(a["pmid"])
            if p in seen_pmids_in_group:
                continue
            seen_pmids_in_group.add(p)
            art = articles_by_pmid.get(p)
            cite_label = _author_year_label(art, p)
            finding_text = _sanitize_prose(str(a.get("finding") or "Confirmed association in screened record.").strip().rstrip("."))
            target_str = str(a.get("direction_target") or "").strip()
            dir_badge = ""
            if direction_key not in ("unspecified", "none"):
                if target_str and target_str.lower() not in ("none", "n/a"):
                    dir_badge = f" (direction: {direction_key} on {target_str})"
                else:
                    dir_badge = f" (direction: {direction_key})"
            finding_sentences.append(
                f"- [{cite_label} (PMID {p})]({rel_prefix_to_pmid}/{p}.md){dir_badge}: {finding_text}."
            )

    if finding_sentences:
        paragraphs.append("### Synthesized Findings Across Studies\n\n" + "\n".join(finding_sentences))

    # Paragraph 3: Cross-concept connections
    if related_concepts:
        rel_links = []
        for other_cid, other_slug, shared_cnt in related_concepts[:6]:
            rel_links.append(f"[{other_cid}](./{other_slug}.md) ({shared_cnt} shared paper{'s' if shared_cnt > 1 else ''})")
        paragraphs.append(
            "### Cross-Concept Bridges\n\n"
            "Studies in this mini-review also co-occur with the following concepts, allowing direct traversal "
            "across related domains: " + ", ".join(rel_links) + "."
        )

    return "\n\n".join(paragraphs)


def export_okf(store_or_workspace: Any, confirm: bool = False) -> dict[str, Any]:
    """Generate Google Open Knowledge Format Markdown files under okf/ for confirmed included references.

    Parameters:
        store_or_workspace: Store instance or filesystem Path/str to review workspace.
        confirm: If True and no human confirmation decision is logged yet, record confirmation.

    Returns:
        Dictionary with okf_dir, included reference count, concept mini-review count,
        emerging topic count, and generated file paths.
    """
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

    # Resolve full article records for each included PMID
    articles_by_pmid: dict[str, dict[str, Any]] = {}
    for pmid, assessments in included_by_pmid.items():
        first_version = assessments[0].get("source_version")
        article = None
        if first_version:
            try:
                article = store.article(pmid, first_version)
            except Exception:
                pass
        if article is None:
            article = articles_table.get(pmid)
        if article is not None:
            articles_by_pmid[pmid] = article

    # Context details
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
    timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Load optional custom concept narratives from corpus/okf_narratives.json
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

    # Build unified dictionary of all Mini-Review nodes (Ontology Concepts + Emerging Topics)
    all_mini_reviews: dict[str, dict[str, Any]] = {}
    for cid, assess_list in sorted(concept_assessments.items()):
        cat, short_name = parse_concept_category_and_name(cid)
        slug = concept_id_to_slug(cid)
        pmids_for_cid = sorted({str(a["pmid"]) for a in assess_list}, key=lambda x: int(x) if x.isdigit() else x)
        all_mini_reviews[cid] = {
            "concept_id": cid,
            "slug": slug,
            "category": cat,
            "name": short_name,
            "title": short_name.replace("_", " ").replace("-", " ").title(),
            "pmids": pmids_for_cid,
            "assessments": assess_list,
            "narrative": custom_narratives.get(cid, ""),
            "is_emerging": False,
        }

    for et in emerging_topics:
        cid = et["concept_id"]
        et_pmids = [p for p in et["pmids"] if p in included_by_pmid]
        if not et_pmids:
            continue
        # Collect assessments across those PMIDs
        et_assess: list[dict[str, Any]] = []
        for p in et_pmids:
            et_assess.extend(included_by_pmid.get(p, []))
        all_mini_reviews[cid] = {
            "concept_id": cid,
            "slug": et["slug"],
            "category": "emerging",
            "name": et["name"],
            "title": et["title"],
            "pmids": et_pmids,
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

    # 3. Write Focused Concept & Emerging Topic Mini-Review Markdown files (`okf/concepts/<slug>.md`)
    for cid, mr in sorted(all_mini_reviews.items()):
        slug = mr["slug"]
        cat = mr["category"]
        is_emerging = mr["is_emerging"]
        assess_list = mr["assessments"]
        pmids_for_cid = mr["pmids"]

        # Find related concepts sharing PMIDs
        related_list: list[tuple[str, str, int]] = []
        for (c1, c2), shared_set in concept_cooccurrence.items():
            if c1 == cid:
                related_list.append((c2, all_mini_reviews[c2]["slug"], len(shared_set)))
            elif c2 == cid:
                related_list.append((c1, all_mini_reviews[c1]["slug"], len(shared_set)))
        related_list.sort(key=lambda x: (-x[2], x[0]))

        species_counter = Counter(
            str(a.get("species") or "unspecified").strip().lower()
            for a in assess_list
            if a.get("species")
        )
        direction_counter = Counter(
            str(a.get("direction") or "unspecified").strip().lower()
            for a in assess_list
        )
        unique_genes = sorted({str(a.get("gene") or primary_gene) for a in assess_list})

        mr_frontmatter = {
            "type": "Concept",
            "title": f"{mr['title']} ({CATEGORY_TITLES.get(cat, cat)})",
            "concept_id": cid,
            "category": cat,
            "is_emerging": is_emerging,
            "genes": unique_genes,
            "pmid_count": len(pmids_for_cid),
            "pmids": pmids_for_cid,
            "species_breakdown": dict(species_counter),
            "direction_breakdown": dict(direction_counter),
            "related_concepts": [r[0] for r in related_list],
            "tags": ["open-knowledge-format", "concept-mini-review", cat] + unique_genes,
            "created_at": timestamp_iso,
            "verified": True,
        }

        prose_md = _synthesize_concept_mini_review_prose(
            concept_title=mr["title"],
            category=cat,
            is_emerging=is_emerging,
            assessments=assess_list,
            articles_by_pmid=articles_by_pmid,
            related_concepts=related_list,
            custom_narrative=mr["narrative"],
            rel_prefix_to_pmid="..",
        )

        # Evidence table for this mini-review
        ev_table_lines = [
            "| Reference | Author (Year) | Species | Study Design | Direction | Target | Key Finding |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        quote_blocks: list[str] = []
        seen_pmid_assess: set[tuple[str, str]] = set()
        for a in assess_list:
            p = str(a["pmid"])
            f_txt = str(a.get("finding") or "")
            if (p, f_txt) in seen_pmid_assess:
                continue
            seen_pmid_assess.add((p, f_txt))
            art = articles_by_pmid.get(p)
            ay = _author_year_label(art, p)
            sp = _clean_text_for_cell(a.get("species") or "unspecified")
            sd = _clean_text_for_cell(a.get("study_design") or "unspecified")
            dr = _clean_text_for_cell(a.get("direction") or "unspecified")
            dt = _clean_text_for_cell(a.get("direction_target") or "none")
            fd = _clean_text_for_cell(f_txt or "Included by screening")
            ev_table_lines.append(
                f"| [Reference {p}](../{p}.md) | {_clean_text_for_cell(ay)} | {sp} | {sd} | {dr} | {dt} | {fd} |"
            )
            q_txt = str(a.get("quotation") or "").strip()
            if q_txt:
                quote_blocks.append(f"- **[Reference {p} ({ay})](../{p}.md)**:\n  > {_sanitize_prose(q_txt)}")

        quotes_section = (
            "## Verbatim Supporting Quotations\n\n" + "\n\n".join(quote_blocks)
            if quote_blocks
            else "## Verbatim Supporting Quotations\n\nNo verbatim quotations recorded for this concept."
        )

        cat_heading = CATEGORY_TITLES.get(cat, cat.title())
        badge_type = "Emerging Topic Mini-Review" if is_emerging else "Ontology Concept Mini-Review"

        mr_md = f"""{to_yaml_frontmatter(mr_frontmatter)}# {mr['title']}

- **Mini-Review Type**: {badge_type}
- **Category**: {cat_heading} (`{cat}`)
- **Concept Identifier**: `{cid}`
- **Target Gene(s)**: {", ".join(unique_genes)}
- **Supporting References**: {len(pmids_for_cid)}
- **Navigation**: [Open Knowledge Format index](../index.md)

## Mini-Review Synthesis

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
        unique_species = sorted({str(a.get("species") or "").strip().lower() for a in assessments if a.get("species")})
        unique_directions = sorted({str(a.get("direction") or "").strip().lower() for a in assessments if a.get("direction")})

        first_finding = next((str(a["finding"]) for a in assessments if a.get("finding")), clean_title)
        short_desc = _sanitize_prose(re.sub(r"\s+", " ", first_finding).strip())
        if len(short_desc) > 160:
            short_desc = short_desc[:157] + "..."

        concept_tags = [c.replace("/", "-") for c in unique_concepts + emerging_for_pmid]
        tags = ["literature-reference", "screened-in"] + unique_genes + unique_species + concept_tags

        clean_assessments = []
        for a in assessments:
            entry = {
                "gene": a.get("gene"),
                "concept": a.get("concept_id"),
                "decision": "include",
                "species": a.get("species"),
                "study_design": a.get("study_design"),
                "direction": a.get("direction"),
                "direction_target": a.get("direction_target"),
                "finding": _sanitize_prose(str(a.get("finding"))) if a.get("finding") else None,
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

        # Links to Mini-Reviews supported by this paper
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

        # Format individual screening assessments
        assess_blocks = []
        for idx, a in enumerate(assessments, start=1):
            g = a.get("gene", "N/A")
            c = str(a.get("concept_id", "N/A"))
            f = _sanitize_prose(str(a.get("finding", "Included based on review screening criteria.")))
            sp = a.get("species") or "Not recorded"
            sd = a.get("study_design") or "Not recorded"
            dir_str = a.get("direction")
            target_str = a.get("direction_target")
            quote = _sanitize_prose(str(a.get("quotation") or "").strip())

            c_link = f"[{c}](./concepts/{all_mini_reviews[c]['slug']}.md)" if c in all_mini_reviews else f"`{c}`"
            block_lines = [
                f"### Assessment {idx}: Gene {g} across Concept {c}",
                "",
                f"- **Gene**: {g}",
                f"- **Concept Mini-Review**: {c_link}",
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

        # Related PMIDs sharing at least one concept or emerging topic
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
            else "- No co-occurring references in the same concept mini-review."
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

## Linked Concept and Emerging Topic Mini-Reviews

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

    # 5. Build `okf/index.md` organized by Top-Level Ontology Categories + Emerging Topics
    index_frontmatter = {
        "type": "Index",
        "title": f"Open Knowledge Format Synthesis: {genes_label} and {phenotype_label}",
        "description": "Ontology-structured mini-reviews, emerging topics, and confirmed reference notes in Google Open Knowledge Format.",
        "tags": ["open-knowledge-format", "literature-review", "screened-evidence", "mini-reviews"] + genes_list,
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
                "This section captures cross-cutting mechanistic themes, shared molecular readouts, and translational "
                "patterns that emerge across screened studies beyond single ontology branches.",
                "",
            ])
        cat_lines.extend([
            "| Mini-Review Topic | Supporting Papers | Species | Directions of Effect | Linked References |",
            "| --- | --- | --- | --- | --- |",
        ])
        for mr in sorted(cat_mrs, key=lambda x: (-len(x["pmids"]), x["title"])):
            sp_set = sorted({str(a.get("species") or "unspecified").lower() for a in mr["assessments"] if a.get("species")})
            dir_set = sorted({str(a.get("direction") or "unspecified").lower() for a in mr["assessments"] if a.get("direction")})
            ref_links = ", ".join(f"[PMID {p}](./{p}.md)" for p in mr["pmids"][:8])
            if len(mr["pmids"]) > 8:
                ref_links += f" (+{len(mr['pmids']) - 8} more)"
            cat_lines.append(
                f"| [{_clean_text_for_cell(mr['title'])}](./concepts/{mr['slug']}.md) "
                f"| {len(mr['pmids'])} "
                f"| {_clean_text_for_cell(', '.join(sp_set) or 'unspecified')} "
                f"| {_clean_text_for_cell(', '.join(dir_set) or 'unspecified')} "
                f"| {ref_links} |"
            )
        cat_lines.append("")
        category_sections.append("\n".join(cat_lines))

    if not category_sections:
        category_sections.append("No confirmed included references or concept mini-reviews have been generated yet.")

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

    index_md = f"""{to_yaml_frontmatter(index_frontmatter)}# Open Knowledge Format (OKF): {genes_label} in {phenotype_label}

- **Review Workspace**: `{store.root.name}`
- **Target Gene(s)**: {genes_label}
- **Phenotype Scope**: {phenotype_label}
- **Ontology Concept Mini-Reviews**: {ont_mr_count}
- **Emerging Topic Mini-Reviews**: {em_mr_count}
- **Confirmed Reference Notes**: {len(index_rows)}
- **Specification Reference**: [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)

This knowledge base organizes confirmed included literature into a two-tier network designed for rapid question answering and visual graph exploration:
1. **Focused Concept and Emerging Topic Mini-Reviews**: Synthesize findings, study designs, species concordance, directions of effect, and verbatim quotations per ontology domain and emerging cross-domain theme.
2. **Atomic Reference Notes**: Record per-study bibliographic metadata, screening assessments, verbatim quotes, and cross-links.

## Ontology and Emerging Topic Mini-Reviews

{chr(10).join(category_sections)}

## Atomic Reference Notes

{table_md}
"""
    index_md = _sanitize_prose(index_md)
    index_file = okf_dir / "index.md"
    index_file.write_text(index_md, encoding="utf-8")
    generated_files.append(index_file)

    # 6. Build Cytoscape.js Graph Specification (`corpus/okf_graph.json`)
    graph_data = _build_cytoscape_graph_data(
        primary_gene=primary_gene,
        genes_list=genes_list,
        phenotype_label=phenotype_label,
        all_mini_reviews=all_mini_reviews,
        concept_cooccurrence=concept_cooccurrence,
        pmid_preview_map=pmid_preview_map,
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

    return {
        "workspace": str(store.root),
        "okf_dir": str(okf_dir),
        "included_count": len(index_rows),
        "concept_mini_reviews_count": ont_mr_count,
        "emerging_topics_count": em_mr_count,
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
) -> dict[str, Any]:
    """Construct nodes, edges, colors, and side-panel preview payloads for the Cytoscape.js visualizer."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # 1. Central Gene Hub Node
    gene_id = f"gene:{primary_gene}"
    nodes.append({
        "data": {
            "id": gene_id,
            "label": primary_gene,
            "node_type": "gene",
            "category": "gene",
            "color": CATEGORY_COLORS["gene"],
            "size": 58,
            "species": ["human", "rat", "mouse"],
            "directions": ["increase", "decrease", "no_effect", "mixed"],
            "title": f"Target Gene Hub: {', '.join(genes_list or [primary_gene])}",
            "subtitle": f"Phenotype Scope: {phenotype_label}",
            "summary": (
                f"Central target gene hub connecting {len(all_mini_reviews)} Concept & Emerging Topic "
                f"Mini-Reviews and {len(pmid_preview_map)} confirmed included studies."
            ),
            "note_url": "./gene-function.html",
        }
    })

    # 2. Category Hub Nodes (for active ontology categories + emerging topics)
    active_categories = sorted(
        {mr["category"] for mr in all_mini_reviews.values()},
        key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99,
    )
    for cat in active_categories:
        cat_node_id = f"cat:{cat}"
        cat_mrs = [mr for mr in all_mini_reviews.values() if mr["category"] == cat]
        cat_pmids = sorted({p for mr in cat_mrs for p in mr["pmids"]}, key=lambda x: int(x) if x.isdigit() else x)
        cat_sp = sorted({sp for p in cat_pmids for sp in pmid_preview_map.get(p, {}).get("species", [])})
        cat_dir = sorted({d for p in cat_pmids for d in pmid_preview_map.get(p, {}).get("directions", [])})
        nodes.append({
            "data": {
                "id": cat_node_id,
                "label": "Emerging Topics" if cat == "emerging" else cat.title(),
                "node_type": "category",
                "category": cat,
                "is_emerging": (cat == "emerging"),
                "color": CATEGORY_COLORS.get(cat, "#88c0d0"),
                "size": 44,
                "pmid_count": len(cat_pmids),
                "species": cat_sp or ["unspecified"],
                "directions": cat_dir or ["unspecified"],
                "title": CATEGORY_TITLES.get(cat, cat.title()),
                "subtitle": f"Category Hub ({len(cat_mrs)} Mini-Reviews, {len(cat_pmids)} Papers)",
                "summary": (
                    f"Contains {len(cat_mrs)} focused mini-review(s): "
                    + ", ".join(mr["title"] for mr in cat_mrs)
                ),
                "concepts": [{"id": f"concept:{mr['concept_id']}", "title": mr["title"], "slug": mr["slug"]} for mr in cat_mrs],
                "pmids": cat_pmids,
            }
        })
        edges.append({
            "data": {
                "id": f"e:{gene_id}->{cat_node_id}",
                "source": gene_id,
                "target": cat_node_id,
                "edge_type": "hierarchy_gene_cat",
                "weight": max(2, len(cat_pmids)),
                "label": "",
            }
        })

    # 3. Concept & Emerging Topic Mini-Review Nodes
    for cid, mr in sorted(all_mini_reviews.items()):
        cat = mr["category"]
        c_node_id = f"concept:{cid}"
        cat_node_id = f"cat:{cat}"
        c_pmids = mr["pmids"]
        c_sp = sorted({str(a.get("species") or "unspecified").lower() for a in mr["assessments"] if a.get("species")})
        c_dir = sorted({str(a.get("direction") or "unspecified").lower() for a in mr["assessments"] if a.get("direction")})
        node_size = min(50, 28 + len(c_pmids) * 4)

        # Build concise preview items for side-panel
        preview_items = []
        seen_pf = set()
        for a in mr["assessments"]:
            p = str(a["pmid"])
            f_txt = str(a.get("finding") or "")
            if (p, f_txt) in seen_pf:
                continue
            seen_pf.add((p, f_txt))
            p_info = pmid_preview_map.get(p, {})
            preview_items.append({
                "pmid": p,
                "author_year": p_info.get("author_year", f"PMID {p}"),
                "species": a.get("species") or "unspecified",
                "study_design": a.get("study_design") or "unspecified",
                "direction": a.get("direction") or "unspecified",
                "direction_target": a.get("direction_target") or "",
                "finding": _sanitize_prose(f_txt),
                "quotation": _sanitize_prose(str(a.get("quotation") or "")),
            })

        nodes.append({
            "data": {
                "id": c_node_id,
                "label": mr["title"],
                "concept_id": cid,
                "slug": mr["slug"],
                "node_type": "emerging_concept" if mr["is_emerging"] else "concept",
                "category": cat,
                "is_emerging": mr["is_emerging"],
                "color": CATEGORY_COLORS.get(cat, "#88c0d0"),
                "size": node_size,
                "pmid_count": len(c_pmids),
                "species": c_sp or ["unspecified"],
                "directions": c_dir or ["unspecified"],
                "title": mr["title"],
                "subtitle": f"{'Emerging Topic' if mr['is_emerging'] else CATEGORY_TITLES.get(cat, cat)} ({len(c_pmids)} Papers)",
                "summary": mr["narrative"] or f"Focused mini-review synthesizing {len(c_pmids)} confirmed study record(s) for {mr['title']}.",
                "assessments": preview_items,
                "pmids": c_pmids,
                "note_url": f"./okf/concepts/{mr['slug']}.html",
                "md_url": f"./okf/concepts/{mr['slug']}.md",
            }
        })
        edges.append({
            "data": {
                "id": f"e:{cat_node_id}->{c_node_id}",
                "source": cat_node_id,
                "target": c_node_id,
                "edge_type": "hierarchy_cat_concept",
                "weight": max(1, len(c_pmids)),
                "label": "",
            }
        })

    # 4. Concept <-> Concept Co-occurrence Edges (Bridging Papers)
    for (c1, c2), shared_set in sorted(concept_cooccurrence.items()):
        shared_list = sorted(shared_set, key=lambda x: int(x) if x.isdigit() else x)
        edges.append({
            "data": {
                "id": f"e:co:{c1}<->{c2}",
                "source": f"concept:{c1}",
                "target": f"concept:{c2}",
                "edge_type": "cooccurrence",
                "weight": len(shared_list),
                "shared_pmids": shared_list,
                "label": f"{len(shared_list)} shared",
            }
        })

    # 5. Atomic PMID Reference Leaf Nodes + Concept -> PMID Edges
    for pmid, p_info in sorted(pmid_preview_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
        p_node_id = f"pmid:{pmid}"
        primary_dir = (p_info["directions"][0] if p_info["directions"] else "unspecified").lower()
        primary_sp = (p_info["species"][0] if p_info["species"] else "unspecified").lower()

        # Color PMID border/fill based on primary category or direction
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
                # Find direction for this specific (cid, pmid) pair
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
