import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wikigenes import ArticleTextParser, SearchResultsParser, cache_path, fetch_html, run


SEARCH_HTML = '''
<div class="queryResult queryResultOdd">
  <div class="queryResultLeft">
    <a href="/e/gene/e/79365.html"><b>BHLHE</b><b>41</b></a>
    - <a href="/e/gene/e/79365.html">basic helix-loop-helix family, member e41</a>
  </div><div class="queryResultRight">Homo sapiens</div>
</div>
<div class="queryResult">
  <div class="queryResultLeft">
    <a href="/e/gene/e/79362.html">Bhlhe41</a>
    - <a href="/e/gene/e/79362.html">basic helix-loop-helix family, member e41</a>
  </div><div class="queryResultRight">Mus musculus</div>
</div>
<div class="queryResult queryResultOdd">
  <div class="queryResultLeft">
    <a href="/e/gene/e/117095.html">Bhlhe41</a>
    - <a href="/e/gene/e/117095.html">basic helix-loop-helix family, member e41</a>
  </div><div class="queryResultRight">Rattus norvegicus</div>
</div>
<div class="queryResult">
  <div class="queryResultLeft"><a href="/e/gene/e/465351.html">BHLHE41</a></div>
  <div class="queryResultRight">Pan troglodytes</div>
</div>
'''

ARTICLE_HTML = '''
<html><body>
<div id="header"><p>Ignore navigation</p></div>
<div id="main_content">
  <h1>Gene Review</h1>
  <h2>BHLHE41 - basic helix-loop-helix family, member e41</h2>
  <h2>Homo sapiens</h2>
  <h3>Biological context</h3>
  <ul><li>DEC2 regulates gene expression <a href="/e/ref/e/12345.html">[1]</a> <a href="https://pubmed.ncbi.nlm.nih.gov/12345/">PubMed</a>.</li></ul>
  <h3>References</h3><p>Unrelated reference link. <a href="https://example.org/unrelated">Link</a></p>
</div></body></html>
'''


class WikiGenesParserTests(unittest.TestCase):
    def test_search_parser_extracts_gene_ids_symbols_and_species(self):
        parser = SearchResultsParser()
        parser.feed(SEARCH_HTML)
        self.assertEqual(len(parser.rows), 4)
        self.assertEqual(parser.rows[0]["symbol"], "BHLHE41")
        self.assertEqual(parser.rows[0]["species"], "Homo sapiens")
        self.assertEqual(parser.rows[0]["wikigenes_id"], "79365")
        self.assertEqual(parser.rows[1]["species"], "Mus musculus")
        self.assertEqual(parser.rows[2]["species"], "Rattus norvegicus")
        self.assertEqual(parser.rows[3]["species"], "Pan troglodytes")

    def test_article_parser_groups_content_under_headings_and_keeps_links(self):
        parser = ArticleTextParser()
        parser.feed(ARTICLE_HTML)
        sections = parser.sections()
        self.assertEqual(sections[0]["heading"], "Gene Review")
        self.assertEqual(sections[1]["heading"], "BHLHE41 - basic helix-loop-helix family, member e41")
        biological = next(s for s in sections if s["heading"] == "Biological context")
        self.assertIn("DEC2 regulates gene expression [1] PubMed.", biological["items"])
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/12345/", parser.links)
        self.assertNotIn("https://example.org/unrelated", parser.links)
        self.assertNotIn("Ignore navigation", " ".join(x["text"] for x in parser.blocks))

    def test_fetch_uses_cached_html_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            url = "https://www.wikigenes.org/?search=TP53"
            path = cache_path(cache, url)
            path.write_text("<html>cached</html>", encoding="utf-8")
            content, returned_path, was_cached = fetch_html(url, cache, 0, 1, 0, False)
            self.assertEqual(content, b"<html>cached</html>")
            self.assertEqual(returned_path, path)
            self.assertTrue(was_cached)

    def test_run_filters_species_and_retains_all_matching_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                genes=["BHLHE41", "Bhlhe41"], input=None,
                species="human,mouse,rat", cache_dir=tmp, delay=0,
                timeout=1, retries=0, refresh=False,
                include_nonexact=False, fetch_pages=False,
            )
            with patch("wikigenes.fetch_html", return_value=(SEARCH_HTML.encode(), Path(tmp) / "search.html", False)):
                result = run(args)
            self.assertEqual([r["species"] for r in result["records"]], [
                "Homo sapiens", "Mus musculus", "Rattus norvegicus"
            ])
            self.assertTrue(all(r["matched_queries"] == ["BHLHE41", "Bhlhe41"] for r in result["records"]))

    def test_run_saves_only_function_sections_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                genes=["BHLHE41"], input=None,
                species="human,mouse,rat", cache_dir=tmp, delay=0,
                timeout=1, retries=0, refresh=False,
                include_nonexact=False, fetch_pages=True,
            )
            responses = [(SEARCH_HTML.encode(), Path(tmp) / "search.html", False)]
            responses.extend((ARTICLE_HTML.encode(), Path(tmp) / f"article-{i}.html", False) for i in range(3))
            with patch("wikigenes.fetch_html", side_effect=responses):
                result = run(args)
            self.assertEqual(len(result["records"]), 3)
            for record in result["records"]:
                self.assertEqual([s["heading"] for s in record["function_sections"]], ["Biological context"])
                self.assertIn("https://pubmed.ncbi.nlm.nih.gov/12345/", record["function_links"])
                self.assertNotIn("https://example.org/unrelated", record["function_links"])


if __name__ == "__main__":
    unittest.main()
