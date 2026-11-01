"""Tests for HTML rendering of wasp-lit workspace markdown files with dark theme and PMID tooltips."""

from pathlib import Path
import json
import tempfile
import unittest

from bs4 import BeautifulSoup
from wasp_core import Store, atomic


class RenderHtmlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.store = Store(str(self.workspace))
        context = {
            "genes": [{"symbol": "CACNA1C", "aliases": ["Cav1.2"], "identity_source": "synthetic test"}],
            "phenotype": "nicotine self-administration",
            "phenotype_terms": ["nicotine self-administration"],
            "reference_organism": "Homo sapiens",
            "evidence_species": "human, mouse, rat",
            "concept_ids": ["drug/nicotine"],
            "abstract_cap": 2,
            "fulltext_quota": 2,
        }
        ontology = {"drug": {"nicotine": ["nicotine"]}}
        self.store.init(context, ontology)

        # Add a synthetic article to articles.jsonl
        art = {
            "pmid": "37047381",
            "title": "Structure and function of CaV1.2 calcium channels.",
            "authors": ["Author A", "Author B", "Author C", "Author D"],
            "journal": "Nature Reviews Neuroscience",
            "publication_date": {"Year": "2023"},
            "abstract": "CaV1.2 channels mediate voltage-gated calcium influx in excitable cells.",
            "abstract_status": "available",
            "source_version": "v1",
        }
        ref = self.store.source("r1", "fetch", {"records": [art]})
        self.store.put_records([art], ref)

        # Write sample synthesis.md and gene-function.md
        synthesis_md = (
            "# Candidate-gene plausibility assessment: CACNA1C\n\n"
            "CaV1.2 is expressed in cardiac myocytes ([PMID: 37047381](https://pubmed.ncbi.nlm.nih.gov/37047381/)).\n\n"
            "See the [baseline gene function summary](./gene-function.md) and "
            "[human decision log](./human-decisions.md).\n\n"
            "| PMID | Level |\n"
            "| --- | --- |\n"
            "| 37047381 | abstract |\n"
        )
        (self.workspace / "synthesis.md").write_text(synthesis_md, encoding="utf-8")
        (self.workspace / "gene-function.md").write_text("# CACNA1C Function\n\nBaseline function.\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_render_html_generates_dark_themed_html_with_pmid_tooltips(self):
        res = self.store.render_html()
        self.assertIn("synthesis.html", res["generated_html_files"][0])
        self.assertTrue((self.workspace / "synthesis.html").is_file())
        self.assertTrue((self.workspace / "gene-function.html").is_file())
        self.assertTrue((self.workspace / "pmid-cache.js").is_file())

        html_content = (self.workspace / "synthesis.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Check high-contrast dark theme CSS variables with warm ivory (yellow-tinted white) font
        self.assertIn("--bg-color: #14171d;", html_content)
        self.assertIn("--panel-bg-color: #1d212a;", html_content)
        self.assertIn("--text-color: #faf4e6;", html_content)

        # 2. Check tooltip container
        self.assertIsNotNone(soup.find("div", id="tooltip"))

        # 3. Check PMID links have class and data-pmid
        pmid_links = soup.find_all("a", class_="pmid-link")
        self.assertGreaterEqual(len(pmid_links), 2)
        for link in pmid_links:
            self.assertEqual(link["data-pmid"], "37047381")
            self.assertEqual(link["target"], "_blank")

        # 4. Check .md link was rewritten to .html (both in nav and in article body)
        gf_links = soup.find_all("a", href="./gene-function.html")
        self.assertGreaterEqual(len(gf_links), 2)
        body_gf_link = [l for l in gf_links if "gene function summary" in l.text]
        self.assertTrue(len(body_gf_link) > 0)

        # 5. Check navigation header has active class on synthesis
        active_nav = soup.find("a", class_="nav-link active")
        self.assertIsNotNone(active_nav)
        self.assertEqual(active_nav["href"], "./synthesis.html")

        # 6. Check pmidCache embedded in page
        self.assertIn('"37047381"', html_content)
        self.assertIn("Structure and function of CaV1.2 calcium channels.", html_content)
        self.assertIn("Author A, ..., Author D", html_content)

        # 7. Check ontology.html was generated and linked in navigation
        self.assertTrue((self.workspace / "ontology.html").is_file())
        ont_nav = soup.find("a", href="./ontology.html")
        self.assertIsNotNone(ont_nav)
        self.assertEqual(ont_nav.text, "Ontology")

        ont_html = (self.workspace / "ontology.html").read_text(encoding="utf-8")
        ont_soup = BeautifulSoup(ont_html, "html.parser")
        ont_active_nav = ont_soup.find("a", class_="nav-link active")
        self.assertIsNotNone(ont_active_nav)
        self.assertEqual(ont_active_nav["href"], "./ontology.html")
        self.assertIsNotNone(ont_soup.find("div", class_="kpi-grid"))
        self.assertIsNotNone(ont_soup.find("div", class_="tree-container"))

    def test_generate_ontology_markdown_with_focused_concepts(self):
        # Create a workspace with a run containing focused concepts and fulltext
        run_data = {
            "run_id": "r1-test",
            "created_at": "2026-10-31T12:00:00Z",
            "searches": {
                "q-focused": {
                    "abstract_cap": 200,
                    "count": 12,
                    "selected_pmids": ["37047381"],
                    "query": "CACNA1C AND nicotine",
                    "concept": {
                        "category": "drug",
                        "id": "drug/nicotine",
                        "name": "nicotine",
                        "terms": ["nicotine", "smoking"],
                    },
                },
                "q-std": {
                    "abstract_cap": 30,
                    "count": 5,
                    "selected_pmids": [],
                    "query": "CACNA1C AND alcohol",
                    "concept": {
                        "category": "drug",
                        "id": "drug/alcohol",
                        "name": "alcohol",
                        "terms": ["alcohol"],
                    },
                },
            },
        }
        (self.workspace / "corpus" / "runs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "corpus" / "runs" / "run_01.json").write_text(json.dumps(run_data), encoding="utf-8")

        # Add fulltext entry for 37047381
        ft_entry = {"pmid": "37047381", "pmcid": "PMC1234567"}
        (self.workspace / "corpus" / "fulltexts.jsonl").write_text(json.dumps(ft_entry) + "\n", encoding="utf-8")

        res = self.store.render_html()
        self.assertTrue((self.workspace / "ontology.html").is_file())

        ont_html = (self.workspace / "ontology.html").read_text(encoding="utf-8")
        ont_soup = BeautifulSoup(ont_html, "html.parser")

        # Verify focused badge and styling
        focused_leaf = ont_soup.find("div", class_="tree-leaf is-focused")
        self.assertIsNotNone(focused_leaf)
        self.assertIn("Focused (Cap 200)", focused_leaf.text)
        self.assertIn("drug/nicotine", focused_leaf.text)

        # Verify fulltext link rendered in leaf node
        ft_links = focused_leaf.find_all("a", class_="pmid-link")
        self.assertTrue(any(l.get("data-pmid") == "37047381" for l in ft_links))

        # Verify branches are collapsed by default
        branches = ont_soup.find_all("details", class_="tree-branch")
        self.assertTrue(len(branches) > 0)
        self.assertFalse(any(b.has_attr("open") for b in branches))

        # Verify search strata and fulltext tables render as HTML tables (not unrendered markdown)
        tables = ont_soup.find_all("table")
        self.assertEqual(len(tables), 2)
        strata_headers = [th.text for th in tables[0].find_all("th")]
        self.assertIn("Category", strata_headers)
        self.assertIn("Concept ID", strata_headers)
        self.assertIn("Full-Text", strata_headers)

        ft_headers = [th.text for th in tables[1].find_all("th")]
        self.assertIn("PMID", ft_headers)
        self.assertIn("Mapped Concepts", ft_headers)

    def test_detect_accurate_provenance_pi_dev(self):
        import os
        from render_html import detect_accurate_provenance
        # Simulate Pi.dev environment
        with tempfile.TemporaryDirectory() as td:
            pi_dir = Path(td)
            sess_dir = pi_dir / ".pi" / "sessions"
            sess_dir.mkdir(parents=True)
            sess_file = sess_dir / "2026-10-31T10-00-00.jsonl"
            sess_file.write_text(json.dumps({"type": "model_change", "provider": "openai-codex", "modelId": "gpt-6.1-sol"}) + "\n")
            
            old_cwd = os.getcwd()
            try:
                os.chdir(pi_dir)
                os.environ["PI_CODING_AGENT_DIR"] = "/tmp/fake-pi"
                # Clear other harness vars if set
                saved = {k: os.environ.pop(k, None) for k in ("ANTIGRAVITY_AGENT", "ANTIGRAVITY_APP_DATA_DIR", "CLAUDE_CODE", "WASP_HARNESS")}
                try:
                    prov = detect_accurate_provenance()
                    self.assertEqual(prov["harness"], "Pi.dev")
                    self.assertEqual(prov["model"], "gpt-6.1-sol (openai-codex)")
                finally:
                    for k, v in saved.items():
                        if v is not None:
                            os.environ[k] = v
            finally:
                os.chdir(old_cwd)
                os.environ.pop("PI_CODING_AGENT_DIR", None)

    def test_detect_accurate_provenance_unknown_environment(self):
        import os
        from render_html import detect_accurate_provenance
        with tempfile.TemporaryDirectory() as td:
            saved = {k: os.environ.pop(k, None) for k in (
                "ANTIGRAVITY_AGENT", "ANTIGRAVITY_APP_DATA_DIR", "CLAUDE_CODE", 
                "WASP_HARNESS", "WASP_LLM_MODEL", "LLM_MODEL", "MODEL_NAME", 
                "AGENT_MODEL", "PI_CODING_AGENT_DIR", "OLLAMA_MODEL", "OLLAMA_HOST"
            )}
            old_cwd = os.getcwd()
            try:
                os.chdir(td)
                prov = detect_accurate_provenance()
                # Should not invent guesses
                self.assertIsNone(prov["harness"])
                self.assertIsNone(prov["model"])
            finally:
                os.chdir(old_cwd)
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
