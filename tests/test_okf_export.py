"""Tests for Google Open Knowledge Format (OKF) export in wasp-lit."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wasp_core import Store, atomic, digest, load, now
from okf_export import export_okf, to_yaml_frontmatter, get_screened_in_records

try:
    import yaml
except ImportError:
    yaml = None


CONTEXT = {
    "genes": [{"symbol": "DRD2", "aliases": [], "identity_source": "synthetic test"}],
    "phenotype": "substance preference",
    "phenotype_terms": ["preference", "self-administration"],
    "reference_organism": "Rattus norvegicus",
    "evidence_species": "rodent",
    "concept_ids": ["behavior/self_administration"],
    "abstract_cap": 10,
    "fulltext_quota": 2,
    "synthetic": True,
}

ONTOLOGY = {
    "behavior": {
        "self_administration": ["self-administration", "operant"]
    }
}


def make_article(pmid: str, title: str, abstract: str, year: str = "2026"):
    return {
        "pmid": str(pmid),
        "title": title,
        "abstract": abstract,
        "journal": "Neuropsychopharmacology",
        "publication_date": {"Year": year, "Month": "03", "Day": "15"},
        "doi": f"10.1038/s41386-026-{pmid}",
        "pmcid": f"PMC{pmid}",
        "authors": ["Doe JA", "Smith BC"],
        "publication_types": ["Journal Article"],
        "is_preprint": False,
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


class OkfExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.store = Store(self.workspace)
        self.store.init(CONTEXT, ONTOLOGY)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_empty_workspace(self):
        """When no records have passed screening, index.md is created cleanly."""
        res = export_okf(self.store)
        self.assertEqual(res["included_count"], 0)
        index_file = self.workspace / "okf" / "index.md"
        self.assertTrue(index_file.is_file())

        text = index_file.read_text(encoding="utf-8")
        self.assertIn("type: Index", text)
        self.assertIn("No references have passed systematic screening yet", text)

        # Audit markdown must pass
        audit_res = self.store.audit()
        self.assertTrue(audit_res["ok"], f"Audit failed: {audit_res['errors']}")

    def test_export_screened_in_references(self):
        """Screened-in records generate individual OKF concept documents and populated index."""
        # Setup article records
        art1 = make_article(
            "35651629",
            "Dopamine D2 receptor remodeling in operant responding",
            "Contingent operant administration altered striatal D2 receptor expression.",
            year="2022",
        )
        art2 = make_article(
            "28957664",
            "Striatal enhancer landscape in cocaine seeking",
            "Enhancer remodeling controlled drug seeking behavior in rats.",
            year="2018",
        )

        v1 = digest(art1)
        v2 = digest(art2)

        # Save into articles table
        self.store.save_table("articles", [
            {**art1, "source_version": v1, "abstract_status": "available", "source_snapshot": None},
            {**art2, "source_version": v2, "abstract_status": "available", "source_snapshot": None},
        ])

        # Add triage decisions (art1 included, art2 excluded)
        self.store.save_table("triage", [
            {
                "run_id": "run-01",
                "gene": "DRD2",
                "concept_id": "behavior/self_administration",
                "pmid": "35651629",
                "source_version": v1,
                "raw_decision": "include",
                "effective_decision": "include",
                "policy": "raw",
                "gene_identity": "confirmed",
                "concept_addressed": True,
                "species_in_scope": "yes",
                "confidence": 0.95,
            },
            {
                "run_id": "run-01",
                "gene": "DRD2",
                "concept_id": "behavior/self_administration",
                "pmid": "28957664",
                "source_version": v2,
                "raw_decision": "exclude",
                "effective_decision": "exclude",
                "policy": "raw",
                "gene_identity": "absent",
                "concept_addressed": False,
                "species_in_scope": "no",
                "confidence": 0.90,
            },
        ])

        # Add subagent evidence for art2 under another concept that includes it
        self.store.save_table("evidence", [
            {
                "evidence_id": "e-123",
                "job_id": "job-01",
                "gene": "DRD2",
                "concept_id": "behavior/self_administration",
                "pmid": "28957664",
                "source_version": v2,
                "decision": "include",
                "gene_identity": "confirmed",
                "concept_support": "direct",
                "phenotype_relevance": "direct",
                "direction": "increase",
                "direction_target": "drug seeking",
                "finding": "Striatal enhancer activation elevated drug seeking.",
                "study_design": "in_vivo",
                "species": "rat",
                "quotation": "Enhancer remodeling controlled drug seeking behavior in rats.",
                "reason": "Direct behavioral finding",
            }
        ])

        # Add fulltext retrieval entry for art1
        self.store.save_table("fulltexts", [
            {
                "pmid": "35651629",
                "provider": "pmc-efetch",
                "license": "CC-BY",
                "document": {
                    "pmid": "35651629",
                    "passages": [
                        {"text": "Striatal dopamine signaling was significantly altered following prolonged access."}
                    ]
                }
            }
        ])

        # Run OKF export and refresh overview documents
        res = self.store.render_okf()
        self.assertEqual(res["included_count"], 2)
        self.store.overview()

        # Verify okf files exist
        okf_dir = self.workspace / "okf"
        self.assertTrue((okf_dir / "index.md").is_file())
        self.assertTrue((okf_dir / "35651629.md").is_file())
        self.assertTrue((okf_dir / "28957664.md").is_file())

        # Inspect 35651629.md
        text1 = (okf_dir / "35651629.md").read_text(encoding="utf-8")
        self.assertIn("type: Reference", text1)
        self.assertIn("title: Dopamine D2 receptor remodeling in operant responding", text1)
        self.assertIn("resource: https://pubmed.ncbi.nlm.nih.gov/35651629/", text1)
        self.assertIn("verified: true", text1)
        self.assertIn("pmid: '35651629'", text1)
        self.assertIn("## Abstract", text1)
        self.assertIn("Contingent operant administration altered striatal D2 receptor expression.", text1)
        self.assertIn("## Full-Text Retrieval", text1)
        self.assertIn("pmc-efetch", text1)
        self.assertIn("Striatal dopamine signaling was significantly altered", text1)

        # Inspect 28957664.md
        text2 = (okf_dir / "28957664.md").read_text(encoding="utf-8")
        self.assertIn("type: Reference", text2)
        self.assertIn("pmid: '28957664'", text2)
        self.assertIn("Striatal enhancer activation elevated drug seeking.", text2)
        self.assertIn("- **Direction of Effect**: increase", text2)
        self.assertIn("Enhancer remodeling controlled drug seeking behavior in rats.", text2)

        # Inspect index.md
        index_text = (okf_dir / "index.md").read_text(encoding="utf-8")
        self.assertIn("type: Index", index_text)
        self.assertIn("- **Total References Passing Screening**: 2", index_text)
        self.assertIn("[35651629](./35651629.md)", index_text)
        self.assertIn("[28957664](./28957664.md)", index_text)
        self.assertIn("[Reference 35651629](./35651629.md)", index_text)
        self.assertIn("[Reference 28957664](./28957664.md)", index_text)

        # Ensure no unlinked .md or file:// URIs in prose
        self.assertEqual(self.store.audit_markdown(), [])

        # Ensure top README mentions OKF
        readme_text = (self.workspace / "README.md").read_text(encoding="utf-8")
        self.assertIn("[Open Knowledge Format reference index](./okf/index.md)", readme_text)

        # Ensure ai-decisions.md mentions OKF
        ai_dec_text = (self.workspace / "ai-decisions.md").read_text(encoding="utf-8")
        self.assertIn("[Open Knowledge Format index](./okf/index.md)", ai_dec_text)

    def test_cli_okf_command(self):
        """wasp.py okf executes cleanly via command line entry."""
        import subprocess
        wasp_py = Path(__file__).resolve().parents[1] / "scripts" / "wasp.py"
        cmd = [sys.executable, str(wasp_py), "okf", str(self.workspace)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"CLI error: {p.stderr}")
        self.assertIn('"okf_dir":', p.stdout)
        self.assertTrue((self.workspace / "okf" / "index.md").is_file())


if __name__ == "__main__":
    unittest.main()
