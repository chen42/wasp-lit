"""Export screened literature references into Google Open Knowledge Format (OKF).

Conforms to the Google Cloud Open Knowledge Format specification:
https://github.com/GoogleCloudPlatform/open-knowledge-format

Each reference passing systematic screening is exported as a standalone concept Markdown
file under the `okf/` directory with structured YAML frontmatter (type: Reference) and
complete evidence assessments, abstract, and provenance. A progressive disclosure index
is maintained at `okf/index.md` (type: Index).
"""

from __future__ import annotations

import datetime
from pathlib import Path
import re
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


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
    # Check if string requires quotes
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
    return re.sub(r"\s+", " ", s) or "none"


def get_screened_in_records(store) -> dict[str, list[dict[str, Any]]]:
    """Identify all PMIDs that passed screening and collect their evidence assessments."""
    triage_rows = store.table("triage")
    evidence_rows = store.table("evidence")

    # Reconstruct effective assessment map: (gene, concept_id, pmid, source_version) -> item
    latest_map: dict[tuple, dict[str, Any]] = {}
    for row in triage_rows:
        if row.get("policy", "raw") == "raw":
            reasons = []
            if row.get("gene_identity") == "absent":
                reasons.append("gene absent")
            elif row.get("gene_identity") == "ambiguous":
                reasons.append("ambiguous gene homonym")
            if not row.get("concept_addressed"):
                reasons.append("concept not addressed")
            if row.get("species_in_scope") == "no":
                reasons.append("species outside scope")
            reason_text = "; ".join(reasons) if reasons else f"Jev {row.get('effective_decision')} (confidence={row.get('confidence')})"
            key = (row["gene"], row["concept_id"], str(row["pmid"]), row.get("source_version"))
            latest_map[key] = {
                "pmid": str(row["pmid"]),
                "gene": row["gene"],
                "concept_id": row["concept_id"],
                "source_version": row.get("source_version"),
                "decision": row.get("effective_decision"),
                "gene_identity": row.get("gene_identity"),
                "concept_support": "addressed" if row.get("concept_addressed") else "none",
                "species": row.get("species_in_scope"),
                "study_design": "Jev triage",
                "direction": None,
                "direction_target": None,
                "finding": f"Jev classification (confidence={row.get('confidence')})",
                "quotation": None,
                "reason": reason_text,
            }

    for item in evidence_rows:
        key = (item["gene"], item["concept_id"], str(item["pmid"]), item.get("source_version"))
        latest_map[key] = item

    # Group assessments for records where decision is include
    included_by_pmid: dict[str, list[dict[str, Any]]] = {}
    for (gene, concept_id, pmid, version), assessment in latest_map.items():
        if assessment.get("decision") == "include":
            included_by_pmid.setdefault(pmid, []).append(assessment)

    # Also inspect manual human decisions for explicit overrides
    for hd in store.table("human_decisions"):
        stage = hd.get("stage", "")
        dec = hd.get("decision", "").lower()
        if "include" in dec or stage in ("screening_override", "screening_adjudication"):
            for pmid_val in hd.get("pmids", []):
                pmid_str = str(pmid_val).strip()
                if pmid_str and pmid_str not in included_by_pmid:
                    included_by_pmid[pmid_str] = [{
                        "pmid": pmid_str,
                        "gene": "User Override",
                        "concept_id": "human_decision",
                        "decision": "include",
                        "study_design": "Human evaluation",
                        "finding": hd.get("decision", "Human inclusion override"),
                        "reason": hd.get("rationale"),
                    }]

    return included_by_pmid


def export_okf(store_or_workspace: Any) -> dict[str, Any]:
    """Generate Google Open Knowledge Format Markdown files under okf/ for screened references.

    Parameters:
        store_or_workspace: Store instance or filesystem Path/str to review workspace.

    Returns:
        Dictionary with okf_dir, total included references count, and generated file paths.
    """
    if hasattr(store_or_workspace, "base") and hasattr(store_or_workspace, "root"):
        store = store_or_workspace
    else:
        from wasp_core import Store
        store = Store(Path(store_or_workspace))

    okf_dir = store.root / "okf"
    okf_dir.mkdir(parents=True, exist_ok=True)

    included_by_pmid = get_screened_in_records(store)
    articles_table = {str(a["pmid"]): a for a in store.table("articles")}
    fulltexts_table = {str(f["pmid"]): f for f in store.table("fulltexts")}

    # Context details
    context_file = store.base / "context.json"
    context = {}
    if context_file.exists():
        try:
            from wasp_core import load
            context = load(context_file)
        except Exception:
            pass

    genes_list = [g["symbol"] for g in context.get("genes", []) if isinstance(g, dict)]
    genes_label = ", ".join(genes_list) if genes_list else "Literature Review Genes"
    phenotype_label = context.get("phenotype", "Phenotype Review")
    timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    generated_files: list[Path] = []
    index_rows: list[dict[str, str]] = []

    # Process each screened-in reference
    for pmid in sorted(included_by_pmid.keys(), key=lambda x: int(x) if x.isdigit() else x):
        assessments = included_by_pmid[pmid]
        first_version = assessments[0].get("source_version")

        # Resolve article record
        article = None
        if first_version:
            try:
                article = store.article(pmid, first_version)
            except Exception:
                pass
        if article is None:
            article = articles_table.get(pmid)

        raw_title = (article.get("title") if article else None) or f"Literature Reference {pmid}"
        clean_title = re.sub(r"\s+", " ", raw_title).strip()
        abstract_text = (article.get("abstract") if article else None) or "Abstract text not indexed."

        journal_name = (article.get("journal") if article else None) or "Unknown Journal"
        doi_val = article.get("doi") if article else None
        pmcid_val = article.get("pmcid") if article else None
        authors_list = (article.get("authors") if article else None) or []
        is_preprint = bool(article.get("is_preprint")) if article else False

        # Extract publication date
        pub_year = ""
        pub_date_str = ""
        if article and article.get("publication_date"):
            pd = article["publication_date"]
            if isinstance(pd, dict):
                pub_year = pd.get("Year") or ""
                m = pd.get("Month") or "01"
                d = pd.get("Day") or "01"
                pub_date_str = f"{pub_year}-{m}-{d}" if pub_year else ""
            else:
                pub_date_str = str(pd)
                m_yr = re.search(r"\b(19\d\d|20\d\d)\b", pub_date_str)
                if m_yr:
                    pub_year = m_yr.group(1)

        unique_genes = sorted(list({a["gene"] for a in assessments if a.get("gene")}))
        unique_concepts = sorted(list({a["concept_id"] for a in assessments if a.get("concept_id")}))

        # Primary finding for description
        first_finding = next((a["finding"] for a in assessments if a.get("finding")), clean_title)
        short_desc = re.sub(r"\s+", " ", first_finding).strip()
        if len(short_desc) > 160:
            short_desc = short_desc[:157] + "..."

        concept_tags = [c.replace("/", "-") for c in unique_concepts]
        tags = ["literature-reference", "screened-in"] + unique_genes + concept_tags

        # Clean assessments for frontmatter
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
                "finding": a.get("finding"),
                "quotation": a.get("quotation"),
            }
            clean_assessments.append({k: v for k, v in entry.items() if v is not None})

        # Frontmatter dictionary conforming to OKF specification (type: Reference)
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
            "is_preprint": is_preprint,
            "authors": authors_list,
            "genes": unique_genes,
            "concepts": unique_concepts,
            "tags": tags,
            "screening": {
                "decision": "include",
                "assessments": clean_assessments,
            },
            "created_at": timestamp_iso,
            "verified": True,
        }

        # Format assessments in Markdown
        assess_blocks = []
        for idx, a in enumerate(assessments, start=1):
            g = a.get("gene", "N/A")
            c = a.get("concept_id", "N/A")
            f = a.get("finding", "Included based on review screening criteria.")
            sp = a.get("species") or "Not recorded"
            sd = a.get("study_design") or "Not recorded"
            dir_str = a.get("direction")
            target_str = a.get("direction_target")
            quote = a.get("quotation")

            block_lines = [
                f"### Assessment {idx}: Gene {g} across Concept {c}",
                "",
                f"- **Gene**: {g}",
                f"- **Concept**: {c}",
                f"- **Decision**: Included",
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

        # Full-text section if available
        ft_info = fulltexts_table.get(pmid)
        if ft_info:
            ft_provider = ft_info.get("provider", "PMC")
            ft_doc = ft_info.get("document") if isinstance(ft_info.get("document"), dict) else {}
            ft_license = ft_info.get("license", "Fair use / text mining")
            passages = ft_doc.get("passages") or []
            ft_lines = [
                "## Full-Text Retrieval",
                "",
                f"- **Status**: Full-text retrieved via `{ft_provider}`",
                f"- **License**: {ft_license}",
                f"- **Extracted Passages Count**: {len(passages)}",
            ]
            if passages:
                ft_lines.append("")
                ft_lines.append("### Key Passages")
                for p_idx, p_item in enumerate(passages[:5], start=1):
                    p_text = p_item.get("text", "") if isinstance(p_item, dict) else str(p_item)
                    if p_text:
                        p_clean = re.sub(r"\s+", " ", p_text).strip()
                        if len(p_clean) > 300:
                            p_clean = p_clean[:297] + "..."
                        ft_lines.append(f"{p_idx}. {p_clean}")
            fulltext_section = "\n".join(ft_lines)
        else:
            fulltext_section = "## Full-Text Retrieval\n\nFull text not retrieved for this reference in the current review workspace."

        authors_str = ", ".join(authors_list) if authors_list else "Authors not listed"
        doi_line = f"[{doi_val}](https://doi.org/{doi_val})" if doi_val else "Not listed"
        genes_str = ", ".join(unique_genes) if unique_genes else "None"
        concepts_str = ", ".join(unique_concepts) if unique_concepts else "None"

        # Assemble reference document
        ref_doc_md = f"""{to_yaml_frontmatter(frontmatter)}# {clean_title}

- **PMID**: [{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)
- **DOI**: {doi_line}
- **Journal**: {journal_name} ({pub_year or 'N/A'})
- **Authors**: {authors_str}
- **Genes Evaluated**: {genes_str}
- **Concepts Evaluated**: {concepts_str}

## Screening and Evidence Assessment

The following findings and supporting evidence met the inclusion criteria during systematic screening:

{assessments_md}

## Abstract

{abstract_text}

{fulltext_section}

## Provenance and Open Knowledge Format Metadata

- **Specification**: [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
- **Concept Type**: `Reference`
- **Review Workspace**: `{store.root.name}`
- **Source Record Version**: `{first_version or 'N/A'}`
- **Verification Status**: Verified in review corpus
- **Navigation**: [Open Knowledge Format index](./index.md)
"""
        ref_file = okf_dir / f"{pmid}.md"
        ref_file.write_text(ref_doc_md, encoding="utf-8")
        generated_files.append(ref_file)

        index_rows.append({
            "pmid": pmid,
            "title": clean_title,
            "journal_year": f"{journal_name} ({pub_year})" if pub_year else journal_name,
            "genes": genes_str,
            "concepts": concepts_str,
            "finding": short_desc,
        })

    # Generate okf/index.md
    index_frontmatter = {
        "type": "Index",
        "title": "Screened Literature References",
        "description": "Google Open Knowledge Format index of references passing screening in wasp-lit review.",
        "tags": ["open-knowledge-format", "literature-review", "screened-evidence"] + genes_list,
        "created_at": timestamp_iso,
        "verified": True,
    }

    if index_rows:
        table_lines = [
            "| PMID | Title | Journal / Year | Gene(s) | Concept(s) | Key Finding | Reference Document |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in index_rows:
            table_lines.append(
                f"| [{r['pmid']}](./{r['pmid']}.md) | {_clean_text_for_cell(r['title'])} "
                f"| {_clean_text_for_cell(r['journal_year'])} | {_clean_text_for_cell(r['genes'])} "
                f"| {_clean_text_for_cell(r['concepts'])} | {_clean_text_for_cell(r['finding'])} "
                f"| [Reference {r['pmid']}](./{r['pmid']}.md) |"
            )
        table_md = "\n".join(table_lines)
    else:
        table_md = "No references have passed systematic screening yet in this review workspace."

    index_md = f"""{to_yaml_frontmatter(index_frontmatter)}# Screened References (Open Knowledge Format)

- **Review Workspace**: `{store.root.name}`
- **Target Gene(s)**: {genes_label}
- **Phenotype Scope**: {phenotype_label}
- **Total References Passing Screening**: {len(index_rows)}
- **Specification Reference**: [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)

This directory organizes all literature references that passed systematic screening into atomic, self-describing Markdown documents following the Google Open Knowledge Format. Each reference document encapsulates bibliographic metadata, structured screening assessments, the full abstract, and provenance attribution.

## Index of Screened References

{table_md}
"""
    index_file = okf_dir / "index.md"
    index_file.write_text(index_md, encoding="utf-8")
    generated_files.append(index_file)

    # Clean up obsolete reference files in okf/
    active_names = {f.name for f in generated_files}
    for existing_file in okf_dir.glob("*.md"):
        if existing_file.name not in active_names:
            try:
                existing_file.unlink()
            except OSError:
                pass

    return {
        "workspace": str(store.root),
        "okf_dir": str(okf_dir),
        "included_count": len(index_rows),
        "generated_files": [str(f) for f in generated_files],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Export screened references to Google Open Knowledge Format.")
    parser.add_argument("workspace", help="Path to wasp-lit research workspace")
    args = parser.parse_args(argv)

    res = export_okf(args.workspace)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
