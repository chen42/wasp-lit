"""Tests for Google Open Knowledge Format (OKF) two-tier mini-review, reference export, and Cytoscape HTML tab."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from okf_export import export_okf, get_screened_in_records, is_okf_confirmed
from wasp_core import Store


class TestOkfExport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmpdir.name) / "review_ws"
        self.store = Store(self.ws)

        context = {
            "genes": [{"symbol": "OPRM1", "ncbi_gene_id": "4988", "aliases": ["MOR-1"], "identity_source": "NCBI"}],
            "phenotype": "opioid self-administration",
            "phenotype_terms": ["opioid self-administration", "heroin"],
            "reference_organism": "Rattus norvegicus",
            "evidence_species": "rat, mouse, human",
            "concept_ids": ["drug/opioids", "brain/nucleus_accumbens"],
            "abstract_cap": 50,
            "other_abstract_cap": 20,
            "include_all_concepts": False,
            "fulltext_quota": 5,
        }
        ontology = {
            "concepts": [
                {
                    "id": "drug/opioids",
                    "category": "drug",
                    "name": "opioids",
                    "terms": ["opioid", "heroin", "morphine"],
                },
                {
                    "id": "brain/nucleus_accumbens",
                    "category": "brain",
                    "name": "nucleus_accumbens",
                    "terms": ["nucleus accumbens", "NAc"],
                },
            ]
        }
        self.store.init(context, ontology)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_strict_inclusion_and_confirmation_gate(self) -> None:
        # Before confirmation, overview() does not prematurely create okf/
        self.store.overview()
        self.assertFalse(is_okf_confirmed(self.store))
        self.assertFalse((self.ws / "okf" / "index.md").exists())

        # Unconfirmed raw Jev triage records must NOT be included under strict policy
        triage_rows = [
            {
                "pmid": "11111111",
                "gene": "OPRM1",
                "concept_id": "drug/opioids",
                "source_version": "v1",
                "policy": "raw",
                "raw_decision": "include",
                "effective_decision": "include",
                "confidence": 0.95,
                "gene_identity": "target",
                "concept_addressed": True,
                "species_in_scope": "yes",
            }
        ]
        self.store.save_table("triage", triage_rows)
        self.assertEqual(get_screened_in_records(self.store), {})

        # Explicit export with confirm=True logs human confirmation and generates okf/index.md
        res = self.store.render_okf(confirm=True)
        self.assertTrue(is_okf_confirmed(self.store))
        self.assertEqual(res["included_count"], 0)
        self.assertTrue((self.ws / "okf" / "index.md").exists())
        self.assertEqual(self.store.audit_markdown(), [])

    def test_two_tier_mini_reviews_emerging_topics_and_cytoscape_html(self) -> None:
        articles = [
            {
                "pmid": "29384712",
                "source_version": "v1_hash",
                "title": "Mu-opioid receptor signaling in rat nucleus accumbens drives heroin self-administration",
                "abstract": "Activation of OPRM1 in the nucleus accumbens increased heroin self-administration and c-Fos expression in rats.",
                "abstract_status": "available",
                "journal": "Journal of Neuroscience",
                "publication_date": {"Year": "2023", "Month": "05", "Day": "14"},
                "doi": "10.1523/JNEUROSCI.1234-23.2023",
                "pmcid": "PMC9876543",
                "authors": ["Smith JA", "Doe RB", "Chen H"],
                "is_preprint": False,
            },
            {
                "pmid": "30192834",
                "source_version": "v1_hash2",
                "title": "OPRM1 knockout mice exhibit reduced morphine conditioned place preference",
                "abstract": "Deletion of Oprm1 reduced morphine reward and c-Fos expression in mouse ventral striatum.",
                "abstract_status": "available",
                "journal": "Biological Psychiatry",
                "publication_date": {"Year": "2024", "Month": "02", "Day": "01"},
                "doi": "10.1016/j.biopsych.2024.01.005",
                "pmcid": None,
                "authors": ["Johnson K", "Lee M"],
                "is_preprint": False,
            },
        ]
        self.store.save_table("articles", articles)

        # Subagent-confirmed evidence rows bridging two ontology categories + shared direction_target + 2 species
        evidence = [
            {
                "evidence_id": "ev-1",
                "pmid": "29384712",
                "gene": "OPRM1",
                "concept_id": "drug/opioids",
                "source_version": "v1_hash",
                "decision": "include",
                "gene_identity": "exact",
                "concept_support": "direct",
                "species": "rat",
                "study_design": "operant self-administration",
                "direction": "increase",
                "direction_target": "c-Fos expression",
                "finding": "OPRM1 activation increased heroin self-administration and accumbal c-Fos expression.",
                "quotation": "Activation of OPRM1 in the nucleus accumbens increased heroin self-administration and c-Fos expression in rats.",
                "reason": "Direct operant evidence in rat.",
            },
            {
                "evidence_id": "ev-2",
                "pmid": "29384712",
                "gene": "OPRM1",
                "concept_id": "brain/nucleus_accumbens",
                "source_version": "v1_hash",
                "decision": "include",
                "gene_identity": "exact",
                "concept_support": "direct",
                "species": "rat",
                "study_design": "operant self-administration",
                "direction": "increase",
                "direction_target": "c-Fos expression",
                "finding": "Accumbal OPRM1 signaling mediated heroin reinforcement.",
                "quotation": "Activation of OPRM1 in the nucleus accumbens increased heroin self-administration and c-Fos expression in rats.",
                "reason": "Direct brain region evidence.",
            },
            {
                "evidence_id": "ev-3",
                "pmid": "30192834",
                "gene": "OPRM1",
                "concept_id": "drug/opioids",
                "source_version": "v1_hash2",
                "decision": "include",
                "gene_identity": "exact",
                "concept_support": "direct",
                "species": "mouse",
                "study_design": "knockout behavioral assay",
                "direction": "decrease",
                "direction_target": "c-Fos expression",
                "finding": "Oprm1 knockout reduced morphine reward and striatal c-Fos induction.",
                "quotation": "Deletion of Oprm1 reduced morphine reward and c-Fos expression in mouse ventral striatum.",
                "reason": "Direct knockout evidence in mouse.",
            },
        ]
        self.store.save_table("evidence", evidence)

        # Also add an explicit custom emerging topic via store.record_okf_topic
        self.store.record_okf_topic(
            topic_id="striatal-cfos-plasticity",
            title="Striatal Immediate-Early Gene Plasticity",
            pmids=["29384712", "30192834"],
            narrative="Both rat operant heroin self-administration and mouse Oprm1 knockout models converge on striatal c-Fos induction as a shared downstream readout of mu-opioid receptor activity.",
            direction="mixed",
            species=["rat", "mouse"],
        )

        res = self.store.render_okf(confirm=True)
        self.assertEqual(res["included_count"], 2)
        self.assertEqual(res["concept_mini_reviews_count"], 2)
        self.assertGreaterEqual(res["emerging_topics_count"], 1)

        # Check atomic reference notes exist and link to Concept Reviews
        ref_file = self.ws / "okf" / "29384712.md"
        self.assertTrue(ref_file.exists())
        ref_text = ref_file.read_text(encoding="utf-8")
        self.assertIn("type: Reference", ref_text)
        self.assertIn("## Linked Concept and Emerging Topic Reviews", ref_text)
        self.assertIn("./concepts/drug--opioids.md", ref_text)
        self.assertIn("./concepts/brain--nucleus_accumbens.md", ref_text)
        self.assertIn("./concepts/emerging--striatal-cfos-plasticity.md", ref_text)
        self.assertIn("- **Direction of Effect**: increase", ref_text)
        self.assertIn("[Reference 30192834", ref_text)

        # Check Ontology Concept Review content
        drug_mr = self.ws / "okf" / "concepts" / "drug--opioids.md"
        self.assertTrue(drug_mr.exists())
        drug_mr_text = drug_mr.read_text(encoding="utf-8")
        self.assertIn("type: Concept", drug_mr_text)
        self.assertIn("## Concept Synthesis", drug_mr_text)
        self.assertNotIn("Across the screened literature corpus", drug_mr_text)
        self.assertIn("### Relationships in Context", drug_mr_text)
        self.assertIn("\u27f6", drug_mr_text)
        self.assertNotIn("- **Cause**:", drug_mr_text)
        self.assertNotIn("- **Effect (Direction)**:", drug_mr_text)
        self.assertNotIn("- **Consequence**:", drug_mr_text)
        self.assertIn("- **Context**:", drug_mr_text)
        self.assertIn("rat (1), mouse (1)", drug_mr_text)
        self.assertIn("29384712.md", drug_mr_text)
        self.assertIn("30192834.md", drug_mr_text)
        self.assertIn("brain/nucleus_accumbens", drug_mr_text)

        # Check index.md species counts format
        idx_text = (self.ws / "okf" / "index.md").read_text(encoding="utf-8")
        self.assertIn("rat (1), mouse (1)", idx_text)

        # Check Emerging Topic Review content (written as a small review article, not Relationships in Context)
        em_mr = self.ws / "okf" / "concepts" / "emerging--striatal-cfos-plasticity.md"
        self.assertTrue(em_mr.exists())
        em_mr_text = em_mr.read_text(encoding="utf-8")
        self.assertIn("Emerging Topic Review", em_mr_text)
        self.assertIn("Striatal Immediate-Early Gene Plasticity", em_mr_text)
        self.assertNotIn("### Relationships in Context", em_mr_text)
        self.assertIn("PMID 29384712", em_mr_text)

        # Check Cytoscape graph JSON (GeneCup style: gene in center connected directly to concepts)
        graph_path = self.ws / "corpus" / "okf_graph.json"
        self.assertTrue(graph_path.exists())
        graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
        self.assertEqual(graph_data["category_colors"]["emerging"], "#ff79c6")
        node_types = {n["data"]["node_type"] for n in graph_data["nodes"]}
        self.assertIn("gene", node_types)
        self.assertNotIn("category", node_types)
        self.assertIn("concept", node_types)
        self.assertIn("emerging_concept", node_types)
        self.assertIn("pmid", node_types)
        edge_types = {e["data"]["edge_type"] for e in graph_data["edges"]}
        self.assertIn("gene_concept", edge_types)
        self.assertNotIn("cooccurrence", edge_types)

        # Check HTML rendering includes Open Knowledge (OKF) tab and Cytoscape visualizer
        html_res = self.store.render_html()
        self.assertTrue((self.ws / "okf.html").exists())
        self.assertTrue((self.ws / "okf" / "index.html").exists())
        self.assertTrue((self.ws / "okf" / "29384712.html").exists())
        self.assertTrue((self.ws / "okf" / "concepts" / "drug--opioids.html").exists())
        self.assertTrue((self.ws / "okf" / "concepts" / "emerging--striatal-cfos-plasticity.html").exists())

        okf_html = (self.ws / "okf.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(okf_html, "html.parser")
        self.assertIsNotNone(soup.find("div", id="cy-graph"))
        self.assertIsNotNone(soup.find("aside", id="okf-side-panel"))
        self.assertIsNotNone(soup.find("span", attrs={"data-category": "emerging"}))
        toggle_pmids = soup.find("input", id="okf-toggle-pmids")
        self.assertIsNotNone(toggle_pmids)
        self.assertFalse(toggle_pmids.has_attr("checked"))
        cat_branches = soup.find_all("details", class_="okf-cat-branch")
        self.assertGreater(len(cat_branches), 0)
        for cb in cat_branches:
            self.assertFalse(cb.has_attr("open"))
        active_nav = soup.find("a", class_="nav-link active")
        self.assertIsNotNone(active_nav)
        self.assertEqual(active_nav.text, "Knowledge Graph")

        # Verify Markdown audit passes with zero errors
        self.assertEqual(self.store.audit_markdown(), [])

    def test_cli_okf_and_okf_topic_commands(self) -> None:
        wasp_script = SKILL_ROOT / "scripts" / "wasp.py"
        proc_topic = subprocess.run(
            [
                sys.executable,
                str(wasp_script),
                "okf-topic",
                str(self.ws),
                "--id",
                " withdrawal-circuitry ",
                "--title",
                "Withdrawal Circuitry Plasticity",
                "--pmids",
                "29384712",
                "--narrative",
                "Emerging withdrawal circuit synthesis.",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        topic_out = json.loads(proc_topic.stdout)
        self.assertEqual(topic_out["concept_id"], "emerging/withdrawal-circuitry")

        proc_okf = subprocess.run(
            [sys.executable, str(wasp_script), "okf", str(self.ws), "--confirm"],
            capture_output=True,
            text=True,
            check=True,
        )
        output = json.loads(proc_okf.stdout)
        self.assertEqual(output["included_count"], 0)
        self.assertTrue((self.ws / "okf" / "index.md").exists())
        self.assertTrue(is_okf_confirmed(self.store))


if __name__ == "__main__":
    unittest.main()
