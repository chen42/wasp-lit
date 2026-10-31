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

        # 1. Check Nord dark theme CSS variables
        self.assertIn("--bg-color: #2e3440;", html_content)
        self.assertIn("--panel-bg-color: #3b4252;", html_content)
        self.assertIn("--text-color: #d8dee9;", html_content)

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


if __name__ == "__main__":
    unittest.main()
