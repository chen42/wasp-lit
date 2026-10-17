"""Offline acceptance tests. All numerical IDs and scientific text are synthetic."""

from collections import Counter
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wasp_core import (WaspError, Store, atomic, digest, enumerate_pmids, file_hash,
                          load, normalize_ontology, plan_queries, validate_context)
from pubmed_extension import BackendError, EUROPEPMC_BASE, PubmedBackend, parse_bioc, parse_jats, parse_records


ONTOLOGY = {"test": {"stress": ["stress"]}}
CONTEXT = {"genes": [{"symbol": "WASP_TEST_GENE", "aliases": [], "identity_source": "synthetic fixture"}],
           "phenotype": "synthetic stress response", "phenotype_terms": ["stress"],
           "reference_organism": "synthetic organism", "evidence_species": "synthetic fixture only",
           "concept_ids": ["test/stress"], "abstract_cap": 2, "fulltext_quota": 2, "synthetic": True}


def record(pmid, abstract="WASP_TEST_GENE manipulation reduced the synthetic stress response."):
    return {"pmid": str(pmid), "title": "Synthetic test, not a publication", "abstract": abstract,
            "publication_types": ["Journal Article"], "is_preprint": False,
            "publication_date": {"Year": "2026"}, "pubmed_url": "synthetic fixture; not a paper URL"}


class FakeBackend:
    def __init__(self, records=None, ids=None):
        self.records = records or [record(900000003), record(900000002), record(900000001)]
        self.ids = ids or [r["pmid"] for r in self.records]
        self.calls = []
        self.fail_fetch = False
        self.omit = set()
        self.fail_fulltext = set()
        self.unavailable = set()
        self.available = set(self.ids)

    def search(self, query, maximum=9999):
        self.calls.append(("search", query))
        return {"count": len(self.ids), "pmids": self.ids[:maximum], "query_translation": query, "warnings": {}}

    def fetch(self, pmids):
        self.calls.append(("fetch", pmids))
        if self.fail_fetch:
            raise RuntimeError("synthetic network failure")
        return {"records": [r for r in self.records if r["pmid"] in pmids and r["pmid"] not in self.omit]}

    def order_ids(self, pmids):
        self.calls.append(("order_ids", pmids))
        return {"count": len(pmids), "pmids": [p for p in self.ids if p in pmids]}

    def links(self, pmid):
        self.calls.append(("links", pmid))
        pmcids = ["PMC" + pmid] if pmid in self.available else []
        return {"pmid": str(pmid), "pubmed_pmcids": pmcids, "candidate_pmcids": pmcids,
                "europepmc": {"status": "not found"}}

    def fulltext(self, pmid, linked):
        self.calls.append(("fulltext", pmid))
        if pmid in self.fail_fulltext:
            raise RuntimeError("synthetic transient failure")
        if self.unavailable and pmid in self.unavailable:
            return {"status": "unavailable", "pmid": str(pmid), "attempts": [],
                    "candidate_pmcids": list(linked.get("candidate_pmcids") or []),
                    "reason": "synthetic absence", "confirmed_by": ["synthetic"], "errored": []}
        return {"status": "retrieved", "provider": "synthetic", "pmid": str(pmid),
                "candidate_pmcids": list(linked.get("candidate_pmcids") or []),
                "attempts": [{"provider": "synthetic", "status": "retrieved"}],
                "document": {"pmid": pmid, "full_text": "Synthetic full text. Not a paper.",
                             "identity_basis": "synthetic test", "provider": "synthetic",
                             "passages": [{"text": "Synthetic full text. Not a paper."}]}}


def assessment(pmid, decision="include", direction="decrease", quote=None):
    return {"pmid": pmid, "gene_identity": "confirmed", "decision": decision,
            "concept_support": "direct", "phenotype_relevance": "direct", "direction": direction,
            "direction_target": "synthetic stress response" if direction != "unclear" else None,
            "finding": "Synthetic fixture finding, not scientific evidence", "study_design": "in_vivo",
            "species": None, "model": None, "tissue_or_cell": None,
            "quotation": quote or record(pmid)["abstract"], "reason": "synthetic fixture"}


def response(store, job, rows=None):
    rows = rows if rows is not None else [assessment(p) for p in job["assigned_pmids"]]
    counts = Counter(r["decision"] for r in rows)
    summary = {"summary": {"concept": job["concept"]["name"], "gene": job["gene"]["symbol"],
                "assigned": len(rows), "include": counts["include"], "exclude": counts["exclude"],
                "needs_review": counts["needs_review"], "capped": job["capped"]}}
    path = store.root / ("synthetic-response-" + job["job_id"] + ".jsonl")
    atomic(path, rows + [summary], jsonl=True)
    return path


class OntologyTests(unittest.TestCase):
    def test_original_counts_and_terms_preserved(self):
        original = Path(__file__).resolve().parents[1] / "addiction_ontology.json"
        value = normalize_ontology(original)
        self.assertEqual(len(value["concepts"]), 47)
        self.assertEqual(len({t for c in value["concepts"] for t in c["terms"]}), 348)
        self.assertTrue(all("|" not in t for c in value["concepts"] for t in c["terms"]))

    def test_curated_resource_integrity_and_optimized_coverage(self):
        root = Path(__file__).resolve().parents[1]
        raw = load(root / "resources/addiction_ontology.json")
        value = normalize_ontology(deepcopy(raw))
        concepts = {c["id"]: c for c in value["concepts"]}
        self.assertEqual(raw["schema_version"], 1)
        self.assertEqual(len(concepts), 50)
        self.assertEqual(len({c["category"] for c in concepts.values()}), 7)
        self.assertGreaterEqual(sum(len(c["terms"]) for c in concepts.values()), 611)
        self.assertGreaterEqual(len({t for c in concepts.values() for t in c["terms"]}), 610)
        for concept in raw["concepts"]:
            self.assertEqual(len(concept["terms"]), len(set(concept["terms"])))
            self.assertTrue(all(isinstance(t, str) and t.strip() == t and t
                                and "|" not in t for t in concept["terms"]))
        required = {
            "addiction/aversion": {"conditioned odor aversion"},
            "addiction/habit": {"habit", "habit formation", "goal-directed behavior",
                                "goal-directed behaviour", "outcome devaluation",
                                "contingency degradation"},
            "addiction/relapse": {"cue reactivity", "cue-induced craving",
                                 "cue-induced drug seeking", "cue-induced reinstatement"},
            "brain/bnst": {"BNST", "bed nucleus of the stria terminalis"},
            "function/neuroplasticity": {"inhibitory postsynaptic current",
                                         "inhibitory postsynaptic potential",
                                         "miniature inhibitory postsynaptic current"},
        }
        for concept_id, terms in required.items():
            self.assertTrue(terms <= set(concepts[concept_id]["terms"]), concept_id)
        context = deepcopy(CONTEXT)
        context["concept_ids"] = list(concepts)
        queries = plan_queries(validate_context(context, value), value)
        self.assertEqual(len(queries), 51)
        self.assertTrue(any('"BNST"[tiab]' in q["query"] for q in queries))
        self.assertTrue(any('"outcome devaluation"[tiab]' in q["query"] for q in queries))
        self.assertFalse(any("|" in q["query"] for q in queries))

    def test_all_concepts_use_function_selected_and_other_caps(self):
        root = Path(__file__).resolve().parents[1]
        ontology = normalize_ontology(root / "resources/addiction_ontology.json")
        context = deepcopy(CONTEXT)
        context.update(concept_ids=["function/neurotransmission", "brain/VTA"],
                       include_all_concepts=True, abstract_cap=200, other_abstract_cap=30)
        queries = plan_queries(validate_context(context, ontology), ontology)
        self.assertEqual(len(queries), len(ontology["concepts"]) + 1)
        caps = {q["concept"]["id"]: q["abstract_cap"] for q in queries}
        self.assertEqual(caps["function/neurotransmission"], 200)
        self.assertEqual(caps["brain/VTA"], 200)
        self.assertEqual(caps["phenotype/direct"], 30)
        self.assertTrue(all(cap == 30 for concept_id, cap in caps.items()
                            if concept_id not in {"function/neurotransmission", "brain/VTA"}))

    def test_original_and_legacy_resource_hashes_preserved(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(file_hash(root / "addiction_ontology.json"),
                         "b7338ed1d1f75aa1aaafd9c353ef8176f8df4b77e94cb38bbc7b11721aa42bcd")
        self.assertEqual(file_hash(root / "resources/addiction_ontology.legacy-v1.json"),
                         "fd12c3a4c1b16b1ac4d701c24c743d33ce5dad5d889f94e9eff6afedd0a0dd04")

    def test_curated_workspace_freezes_vocabulary_and_hash(self):
        root = Path(__file__).resolve().parents[1]
        ontology = load(root / "resources/addiction_ontology.json")
        context = deepcopy(CONTEXT)
        context["concept_ids"] = ["addiction/habit", "brain/bnst"]
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.init(context, deepcopy(ontology))
            saved = load(store.base / "ontology.json")
            saved_bytes = (store.base / "ontology.json").read_bytes()
            self.assertEqual(load(store.base / "manifest.json")["ontology_sha256"], digest(saved))
            for field in ("terms", "search_terms"):
                updated = deepcopy(ontology)
                concept = next(c for c in updated["concepts"] if c["id"] == "addiction/habit")
                if field == "terms":
                    concept[field].append("synthetic later vocabulary addition")
                else:
                    concept[field].append("habit formation")
                with self.assertRaisesRegex(WaspError, "different scope"):
                    store.init(context, updated)
                self.assertEqual((store.base / "ontology.json").read_bytes(), saved_bytes)
            store.init(context, deepcopy(ontology))

    def test_search_terms_normalized_without_adding_legacy_defaults(self):
        legacy = normalize_ontology(ONTOLOGY)
        self.assertNotIn("search_terms", legacy["concepts"][0])
        source = deepcopy(legacy)
        source["concepts"][0]["terms"] = ["stress", "restraint stress"]
        source["concepts"][0]["search_terms"] = ["stress", "stress"]
        normalized = normalize_ontology(source)
        self.assertEqual(normalized["concepts"][0]["search_terms"], ["stress"])
        self.assertEqual(normalized["concepts"][0]["terms"], ["stress", "restraint stress"])

    def test_invalid_search_terms_rejected_not_silently_defaulted(self):
        for invalid in ([], None, "stress", [" "], [False], ["not in the vocabulary"]):
            with self.subTest(search_terms=invalid):
                ontology = normalize_ontology(ONTOLOGY)
                ontology["concepts"][0]["search_terms"] = invalid
                with self.assertRaises(WaspError):
                    normalize_ontology(ontology)

    def test_queries_use_search_subset_and_keep_full_concept(self):
        ontology = normalize_ontology({"test": {"stress": ["stress", "restraint stress"]}})
        ontology["concepts"][0]["search_terms"] = ["stress"]
        context = validate_context(CONTEXT, ontology)
        queries = plan_queries(context, ontology)
        contextual = next(q for q in queries if q["lane"] == "contextual")
        self.assertIn('"stress"[tiab]', contextual["query"])
        self.assertNotIn('"restraint stress"[tiab]', contextual["query"])
        self.assertEqual(contextual["concept"]["terms"], ["restraint stress", "stress"])
        self.assertEqual(contextual["concept"]["search_terms"], ["stress"])
        legacy = deepcopy(ontology)
        del legacy["concepts"][0]["search_terms"]
        old_query = next(q for q in plan_queries(context, legacy) if q["lane"] == "contextual")
        self.assertIn('"restraint stress"[tiab]', old_query["query"])
        self.assertNotEqual(contextual["query_id"], old_query["query_id"])

    def test_search_subsets_do_not_change_direct_phenotype_lane(self):
        ontology = normalize_ontology({"test": {"stress": ["stress", "restraint stress"]}})
        context = deepcopy(CONTEXT)
        context["phenotype_terms"] = ["stress", "restraint stress"]
        context = validate_context(context, ontology)
        direct_before = next(q for q in plan_queries(context, ontology) if q["lane"] == "direct")
        ontology["concepts"][0]["search_terms"] = ["stress"]
        direct_after = next(q for q in plan_queries(context, ontology) if q["lane"] == "direct")
        self.assertEqual(direct_before, direct_after)
        self.assertIn('"restraint stress"[tiab]', direct_after["query"])

    def test_curated_search_roles_preserve_variants_and_specificity(self):
        root = Path(__file__).resolve().parents[1]
        ontology = normalize_ontology(root / "resources/addiction_ontology.json")
        concepts = {c["id"]: c for c in ontology["concepts"]}
        for c in concepts.values():
            search = c.get("search_terms", c["terms"])
            self.assertTrue(search)
            self.assertTrue(set(search) <= set(c["terms"]))
            for term in set(c["terms"]) - set(search):
                self.assertTrue(any(re.search(r"(?<![\w-])" + re.escape(anchor.casefold()) +
                                             r"(?![\w-])", term.casefold()) for anchor in search),
                                (c["id"], term))
        accumbens = concepts["brain/accumbens"]
        self.assertIn("accumbens core", accumbens["terms"])
        self.assertNotIn("accumbens core", accumbens["search_terms"])
        self.assertTrue({"accumbens", "accumbal", "NAc", "AcbC", "AcbS", "NAcSh"} <=
                        set(accumbens["search_terms"]))
        aversion = concepts["addiction/aversion"]
        self.assertIn("conditioned odor aversion", aversion["terms"])
        self.assertEqual(aversion["search_terms"], ["aversion", "aversive"])
        neuron = concepts["cell/neuron"]
        self.assertTrue({"neuron", "neurons", "interneuron", "interneurons", "RGC"} <=
                        set(neuron["search_terms"]))
        nicotine = concepts["drug/nicotine"]
        self.assertTrue({"e-cigarette", "cigarette", "cigarettes"} <= set(nicotine["search_terms"]))
        self.assertNotIn("search_terms", concepts["drug/amphetamine"])
        self.assertTrue({"amphetamine", "methamphetamine"} <= set(concepts["drug/amphetamine"]["terms"]))

    def test_legacy_workspace_queries_and_vocabulary_stay_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.init(CONTEXT, ONTOLOGY)
            manifest = load(store.base / "manifest.json")
            manifest["wasp_version"] = "0.1.0"
            atomic(store.base / "manifest.json", manifest)
            names = ("context", "ontology", "queries", "manifest")
            before = {n: (store.base / (n + ".json")).read_bytes() for n in names}
            legacy = load(store.base / "ontology.json")
            self.assertNotIn("search_terms", legacy["concepts"][0])
            Store(folder).init(CONTEXT, legacy)
            self.assertEqual(before, {n: (store.base / (n + ".json")).read_bytes() for n in names})
            changed = deepcopy(legacy)
            changed["concepts"][0]["search_terms"] = ["stress"]
            with self.assertRaisesRegex(WaspError, "different scope"):
                Store(folder).init(CONTEXT, changed)
            self.assertEqual(before, {n: (store.base / (n + ".json")).read_bytes() for n in names})
            self.assertTrue(Store(folder).audit()["ok"])

    def test_literal_does_not_execute_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dangerous.txt"
            path.write_text("__import__('os').system('false')")
            with self.assertRaises((ValueError, SyntaxError)):
                normalize_ontology(path)

    def test_queries_are_per_gene_concept_and_explicit_or(self):
        ontology = normalize_ontology({"test": {"a": ["stress", "distress"], "b": ["reward"]}})
        context = deepcopy(CONTEXT)
        context["genes"].append({"symbol": "SECOND_TEST_GENE", "aliases": [], "identity_source": "fixture"})
        context["concept_ids"] = ["test/a", "test/b"]
        context = validate_context(context, ontology)
        queries = plan_queries(context, ontology)
        self.assertEqual(len(queries), 6)
        self.assertEqual(len({q["query_id"] for q in queries}), 6)
        self.assertTrue(any(" OR " in q["query"] for q in queries))
        self.assertFalse(any("|" in q["query"] for q in queries))
        self.assertTrue(all(q["abstract_cap"] == 2 for q in queries))

    def test_missing_species_unknown_concepts_and_zero_cap_rejected(self):
        for field, value in [("reference_organism", ""), ("evidence_species", ""), ("concept_ids", ["missing/x"]),
                             ("abstract_cap", 0), ("abstract_cap", True), ("abstract_cap", 10000)]:
            context = deepcopy(CONTEXT)
            context[field] = value
            with self.assertRaises(WaspError):
                validate_context(context, normalize_ontology(ONTOLOGY))


class EnumerationTests(unittest.TestCase):
    def test_all_ids_are_independent_of_abstract_cap(self):
        data = enumerate_pmids(lambda q, n: {"count": 5, "pmids": ["5", "4", "3", "2", "1"][:n]}, "test", 2)
        self.assertEqual(data["pmids"], ["1", "2", "3", "4", "5"])
        self.assertEqual(data["selected_pmids"], ["5", "4"])
        self.assertTrue(data["capped"])
        self.assertEqual(data["coverage"], "complete_count_reconciled")

    def test_empty_exact_cap_and_below_cap(self):
        for count in (0, 1, 2):
            data = enumerate_pmids(lambda q, n: {"count": count, "pmids": [str(i + 1) for i in range(count)][:n]}, "test", 2)
            self.assertFalse(data["capped"])
            self.assertEqual(data["coverage"], "complete_count_reconciled")

    def test_partition_union_includes_missing_dates_and_overlapping_dates(self):
        dates = {"1": [date(2000, 1, 1)], "2": [date(2001, 1, 1)], "3": [date(2002, 1, 1)],
                 "4": [date(2003, 1, 1), date(2004, 1, 1)], "5": [date(2005, 1, 1)], "6": []}
        def search(query, maximum):
            ids = list(reversed(list(dates)))
            matched = re.search(r'\("(\d{4}/\d{2}/\d{2})"\[dp\] : "(\d{4}/\d{2}/\d{2})"\[dp\]\)', query)
            if matched:
                low, high = [date.fromisoformat(d.replace("/", "-")) for d in matched.groups()]
                in_range = lambda p: any(low <= day <= high for day in dates[p])
                ids = [p for p in ids if (not in_range(p) if " NOT " in query else in_range(p))]
            return {"count": len(ids), "pmids": ids[:maximum]}
        data = enumerate_pmids(search, "test", 2, uid_limit=2)
        self.assertEqual(data["pmids"], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(data["coverage"], "complete_count_reconciled")
        self.assertGreater(data["partition_requests"], 3)

    def test_network_failure_is_incomplete_not_zero_hits(self):
        def fail(q, n):
            raise RuntimeError("synthetic network failure")
        data = enumerate_pmids(fail, "test")
        self.assertEqual(data["coverage"], "incomplete")
        self.assertIsNone(data["count"])
        self.assertTrue(data["errors"])

    def test_partial_short_or_duplicate_response_rejected(self):
        for ids in (["1"], ["1", "1"]):
            data = enumerate_pmids(lambda q, n: {"count": 2, "pmids": ids}, "test")
            self.assertEqual(data["coverage"], "incomplete")

    def test_request_bound_preserves_partial_pmids(self):
        data = enumerate_pmids(lambda q, n: {"count": 10, "pmids": ["10", "9"][:n]}, "test",
                               cap=2, uid_limit=2, max_requests=1)
        self.assertEqual(data["coverage"], "incomplete")
        self.assertEqual(data["pmids"], ["9", "10"])
        self.assertTrue(data["errors"])


JATS_XML = '''<?xml version="1.0"?><article article-type="research-article"><front><article-meta>
<article-id pub-id-type="pmcid">PMC900000001</article-id><article-id pub-id-type="pmid">900000001</article-id>
<permissions><license license-type="open-access"><license-p>Synthetic licence statement for fixtures only.</license-p></license></permissions>
</article-meta></front><body><sec><title>Synthetic section</title><p>Synthetic JATS body text.</p>
<p>Second synthetic paragraph.</p></sec></body></article>'''

JATS_NO_BODY = '''<?xml version="1.0"?><article><front><article-meta>
<article-id pub-id-type="pmcid">PMC900000001</article-id><article-id pub-id-type="pmid">900000001</article-id>
</article-meta></front></article>'''

XML = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>900000001</PMID><Article>
<ArticleTitle>Title with <i>inline text</i>.</ArticleTitle><Journal><Title>Fixture</Title>
<JournalIssue><PubDate><MedlineDate>2026 Spring</MedlineDate></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="RESULTS">A non-normalized self-administration result with <i>inline</i> text.</AbstractText>
<AbstractText>No effect was detected.</AbstractText></Abstract><PublicationTypeList><PublicationType>Preprint</PublicationType>
</PublicationTypeList></Article><CommentsCorrectionsList><CommentsCorrections RefType="UpdateIn"><PMID>900000002</PMID>
</CommentsCorrections></CommentsCorrectionsList></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.test/fixture</ArticleId><ArticleId IdType="pmc">PMC900000001</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


class BoundaryEnumerationTests(unittest.TestCase):
    def partition_search(self, change_count=False, single_day=False):
        dates = {str(i): date(2020 if single_day else 2000 + i, 1, 1) for i in range(1, 6)}
        def search(query, maximum):
            ids = list(reversed(list(dates)))
            match = re.search(r'\("(\d{4}/\d{2}/\d{2})"\[dp\] : "(\d{4}/\d{2}/\d{2})"\[dp\]\)', query)
            if match:
                low, high = [date.fromisoformat(d.replace("/", "-")) for d in match.groups()]
                ids = [p for p in ids if (not low <= dates[p] <= high if " NOT " in query else low <= dates[p] <= high)]
            return {"count": len(ids) + int(change_count and maximum == 0), "pmids": ids[:maximum]}
        return search

    def test_overloaded_single_day_stays_incomplete(self):
        value = enumerate_pmids(self.partition_search(single_day=True), "test", cap=2, uid_limit=2)
        self.assertEqual(value["coverage"], "incomplete")
        self.assertIn("Single publication day", value["errors"][0])

    def test_changing_root_count_stays_incomplete(self):
        value = enumerate_pmids(self.partition_search(change_count=True), "test", cap=2, uid_limit=2)
        self.assertEqual(value["coverage"], "incomplete")
        self.assertIn("count changed", value["errors"][0])

    def test_nonlist_pmid_response_is_not_complete(self):
        value = enumerate_pmids(lambda q, n: {"count": 3, "pmids": "321"}, "test")
        self.assertEqual(value["coverage"], "incomplete")

    def test_negative_count_rejected(self):
        value = enumerate_pmids(lambda q, n: {"count": -1, "pmids": []}, "test")
        self.assertEqual(value["coverage"], "incomplete")


class ParserTests(unittest.TestCase):
    def test_complete_inline_text_structured_abstract_preprint_relations_dates(self):
        item = parse_records(XML)[0]
        self.assertEqual(item["title"], "Title with inline text.")
        self.assertEqual(item["abstract"], "RESULTS: A non-normalized self-administration result with inline text.\nNo effect was detected.")
        self.assertTrue(item["is_preprint"])
        self.assertEqual(item["publication_date"], {"MedlineDate": "2026 Spring"})
        self.assertEqual(item["relationships"][0]["pmid"], "900000002")
        self.assertEqual(item["doi"], "10.test/fixture")
        self.assertEqual(item["publication_status_check"], "not checked")

    def test_history_set_is_referenced_by_query_key_not_term(self):
        # Live ESearch rejected term="#1" with "Wrong subquery #1" and count 0.
        backend = object.__new__(PubmedBackend)
        captured = {}

        class Api:
            def _env_params(self):
                return {"tool": "wasp-lit"}

            def cache_results_history(self, pmids):
                return {"webenv": "MCID_TEST", "query_key": "7"}

        backend.api = Api()
        backend.checked = lambda data: data

        def request(endpoint, params, raw=False):
            captured.update(params)
            return {"esearchresult": {"count": "2", "idlist": ["900000002", "900000001"],
                                      "querytranslation": "fixture[UID]"}}

        backend.request = request
        result = backend.order_ids(["900000001", "900000002"])
        self.assertEqual(captured.get("query_key"), "7")
        self.assertEqual(captured.get("WebEnv"), "MCID_TEST")
        self.assertNotIn("term", captured)
        self.assertEqual(result["pmids"], ["900000002", "900000001"])

    def test_ordinary_search_still_sends_term(self):
        backend = object.__new__(PubmedBackend)
        captured = {}

        class Api:
            def _env_params(self):
                return {}

        backend.api = Api()
        backend.checked = lambda data: data

        def request(endpoint, params, raw=False):
            captured.update(params)
            return {"esearchresult": {"count": "1", "idlist": ["900000001"]}}

        backend.request = request
        backend.search('(CACNA1C[tiab])', 5)
        self.assertEqual(captured.get("term"), "(CACNA1C[tiab])")
        self.assertNotIn("query_key", captured)

    def test_book_record_and_missing_abstract(self):
        xml = '<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>900000008</PMID><ArticleTitle>Fixture book</ArticleTitle></BookDocument></PubmedBookArticle></PubmedArticleSet>'
        self.assertIsNone(parse_records(xml)[0]["abstract"])

    def test_empty_structured_abstract_is_missing_not_a_label_only_abstract(self):
        xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>900000001</PMID><Article><ArticleTitle>Fixture</ArticleTitle><Abstract><AbstractText Label="BACKGROUND"> </AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
        self.assertIsNone(parse_records(xml)[0]["abstract"])

    def test_xml_error_rejected(self):
        with self.assertRaises(BackendError):
            parse_records("<eFetchResult><ERROR>test failure</ERROR></eFetchResult>")

    def test_bioc_identity_empty_and_mismatch(self):
        def bioc(pmid="900000001", text="Synthetic full text.", pmcid="900000001"):
            return [{"documents": [{"id": pmcid, "infons": {}, "passages": [{"text": text,
                       "infons": {"article-id_pmid": pmid, "section_type": "RESULTS"}}]}]}]
        parsed = parse_bioc(bioc(), "900000001", ["900000001"])
        self.assertEqual(parsed["pmcid"], "PMC900000001")
        self.assertEqual(parsed["license"], "not checked")
        for data in (bioc("900000002"), bioc(text=""), bioc(pmcid="900000002")):
            with self.assertRaises(BackendError):
                parse_bioc(data, "900000001", ["900000001"])

    def test_bioc_verified_by_linked_pmc_without_reported_pmid(self):
        data = [{"documents": [{"id": "900000001", "passages": [{"text": "Synthetic full text."}]}]}]
        self.assertEqual(parse_bioc(data, "900000001", ["900000001"])["identity_basis"], "linked PMCID")
        with self.assertRaises(BackendError):
            parse_bioc(data, "900000001", ["900000002"])

    def test_search_extension_reuses_wrapper_and_keeps_count(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        class Api:
            EUTILS_BASE = "synthetic://no-network"
            def _env_params(self):
                return {}
            def _get(self, url, params):
                self.last_params = params
                return {"esearchresult": {"count": "5", "idlist": ["5", "4"], "querytranslation": "translated"}}
        backend.api = Api()
        data = backend.search("test", 2)
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["query_translation"], "translated")
        self.assertEqual(backend.api.last_params["sort"], "pub_date")
        with self.assertRaises(BackendError):
            backend.search("test", 10000)

    def test_other_abstract_is_retained_and_used_when_primary_missing(self):
        xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>900000001</PMID><Article><ArticleTitle>Fixture</ArticleTitle></Article><OtherAbstract Language="eng" Type="Publisher"><AbstractText>Full alternative abstract, with self-administration intact.</AbstractText></OtherAbstract></MedlineCitation></PubmedArticle></PubmedArticleSet>'
        item = parse_records(xml)[0]
        self.assertEqual(item["abstract"], "Full alternative abstract, with self-administration intact.")
        self.assertEqual(item["abstract_source"], "OtherAbstract:eng")
        self.assertEqual(len(item["other_abstracts"]), 1)

    def test_long_queries_use_installed_wrapper_post(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        class Api:
            EUTILS_BASE = "synthetic://no-network"
            def _env_params(self):
                return {}
            def _get(self, *args, **kwargs):
                raise AssertionError("Oversized query used GET")
            def _post(self, url, params):
                self.last_params = params
                return json.dumps({"esearchresult": {"count": "0", "idlist": []}})
        backend.api = Api()
        self.assertEqual(backend.search("synthetic " * 500)["count"], 0)
        self.assertEqual(backend.api.last_params["sort"], "pub_date")

    def test_malformed_xml_is_preserved_for_audit(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        class Api:
            EUTILS_BASE = "synthetic://no-network"
            def _env_params(self):
                return {}
            def _get(self, *args, **kwargs):
                return "<malformed synthetic XML"
        backend.api = Api()
        result = backend.fetch(["900000001"])
        self.assertEqual(result["raw_xml"], "<malformed synthetic XML")
        self.assertTrue(result["parse_error"])

    def test_unverified_bioc_response_is_preserved_but_not_accepted(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        backend.providers = ("pmc-bioc",)
        data = [{"documents": [{"id": "900000002", "passages": [{"text": "Synthetic text."}]}]}]

        class Api:
            PMC_BIOC_BASE = "synthetic://no-network"

            def get_pmc_client(self):
                return None

            def _get(self, *args, **kwargs):
                return data

        backend.api = Api()
        backend.pmc_fulltext_client = lambda: None
        result = backend.fulltext("900000001", {"candidate_pmcids": ["900000001"]})
        self.assertEqual(result["status"], "failed")
        attempt = result["attempts"][0]
        self.assertEqual(attempt["status"], "error")
        self.assertEqual(attempt["raw_response"], data)
        self.assertIn("identity", attempt["error"])

    def test_fulltext_clients_use_bounded_retry_policy_without_mutating_wrapper_clients(self):
        constructed = []

        class FakeHttpClient:
            def __init__(self, base_url, **kwargs):
                self.base_url = base_url
                self.kwargs = kwargs
                constructed.append(self)

        class HttpModule:
            HttpClient = FakeHttpClient

        class Api:
            EUTILS_BASE = "https://eutils.test"
            PMC_BIOC_BASE = "https://bioc.test"
            http_client = HttpModule()

        backend = PubmedBackend.__new__(PubmedBackend)
        backend.api = Api()
        clients = [backend.eutils_fulltext_client(), backend.ebi_fulltext_client(),
                   backend.pmc_fulltext_client()]
        self.assertEqual(clients, constructed)
        self.assertIs(backend.ebi_fulltext_client(), clients[1])
        self.assertEqual([client.base_url for client in clients],
                         ["https://eutils.test", EUROPEPMC_BASE, "https://bioc.test"])
        for client in clients:
            self.assertEqual(client.kwargs["max_retries"], 2)
            self.assertEqual(client.kwargs["timeout"], 30)
            self.assertEqual(client.kwargs["backoff_base"], 1)
            self.assertEqual(client.kwargs["backoff_max"], 180)
            self.assertIn(client.kwargs["qps"], (3, 10))
        self.assertEqual(backend.fulltext_retry_policy["attempts_per_route"], 3)

    def test_provider_chain_tries_efetch_first_then_falls_through(self):
        self.assertEqual(PubmedBackend.providers, ("pmc-efetch", "europepmc", "pmc-bioc"))
        backend = PubmedBackend.__new__(PubmedBackend)
        backend.providers = PubmedBackend.providers
        calls = []

        class Api:
            EUTILS_BASE = "synthetic://eutils"
            PMC_BIOC_BASE = "synthetic://bioc"

            def _env_params(self):
                return {}

            def get_pmc_client(self):
                return None

            def get_eutils_client(self):
                return None

            def _get(self, url, params=None, raw=False, client=None):
                calls.append(url)
                if "eutils" in url:
                    return {"error": "HTTP Error 500: synthetic outage"}
                return JATS_XML

        backend.api = Api()
        backend.ebi_fulltext_client = lambda: None
        backend.eutils_fulltext_client = lambda: None
        result = backend.fulltext("900000001", {"candidate_pmcids": ["900000001"]})
        self.assertEqual(result["status"], "retrieved")
        self.assertEqual(result["provider"], "europepmc")
        self.assertEqual([a["provider"] for a in result["attempts"]], ["pmc-efetch", "europepmc"])
        self.assertEqual([a["status"] for a in result["attempts"]], ["error", "retrieved"])
        self.assertEqual(result["document"]["pmid"], "900000001")
        self.assertEqual(result["document"]["identity_basis"], "reported PMID")
        self.assertIn("Synthetic JATS body", result["document"]["full_text"])
        self.assertEqual(len(calls), 2)

    def test_provider_chain_reports_absence_only_when_a_route_confirms_it(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        backend.providers = ("pmc-efetch", "europepmc")

        class Api:
            EUTILS_BASE = "synthetic://eutils"
            PMC_BIOC_BASE = "synthetic://bioc"

            def _env_params(self):
                return {}

            def get_pmc_client(self):
                return None

            def get_eutils_client(self):
                return None

            def _get(self, url, params=None, raw=False, client=None):
                if "eutils" in url:
                    return {"error": "HTTP Error 404: synthetic absence"}
                return {"error": "HTTP Error 500: synthetic outage"}

        backend.api = Api()
        backend.ebi_fulltext_client = lambda: None
        backend.eutils_fulltext_client = lambda: None
        result = backend.fulltext("900000001", {"candidate_pmcids": ["900000001"]})
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["confirmed_by"], ["pmc-efetch"])
        self.assertEqual(result["errored"], ["europepmc"])

    def test_provider_chain_fails_when_every_route_errors(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        backend.providers = ("pmc-efetch", "europepmc")

        class Api:
            EUTILS_BASE = "synthetic://eutils"
            PMC_BIOC_BASE = "synthetic://bioc"

            def _env_params(self):
                return {}

            def get_pmc_client(self):
                return None

            def get_eutils_client(self):
                return None

            def _get(self, url, params=None, raw=False, client=None):
                return {"error": "HTTP Error 500: synthetic outage"}

        backend.api = Api()
        backend.ebi_fulltext_client = lambda: None
        backend.eutils_fulltext_client = lambda: None
        result = backend.fulltext("900000001", {"candidate_pmcids": ["900000001"]})
        self.assertEqual(result["status"], "failed")
        self.assertIn("pmc-efetch", result["error"])
        self.assertIn("europepmc", result["error"])

    def test_jats_parser_rejects_mismatched_identity_and_empty_body(self):
        with self.assertRaises(BackendError):
            parse_jats(JATS_XML, "900000099", ["900000001"], "synthetic", "synthetic://jats")
        with self.assertRaises(BackendError):
            parse_jats(JATS_XML, "900000001", ["900000999"], "synthetic", "synthetic://jats")
        with self.assertRaises(BackendError):
            parse_jats(JATS_NO_BODY, "900000001", ["900000001"], "synthetic", "synthetic://jats")

    def test_jats_parser_keeps_licence_and_section_order(self):
        parsed = parse_jats(JATS_XML, "900000001", ["900000001"], "synthetic", "synthetic://jats")
        self.assertEqual(parsed["pmcid"], "PMC900000001")
        self.assertEqual(parsed["license_type"], "open-access")
        self.assertIn("Synthetic licence statement", parsed["license"])
        self.assertFalse(parsed["figures_reviewed"])
        self.assertEqual([p["tag"] for p in parsed["passages"]][:2], ["title", "p"])

    def test_redact_credentials(self):
        backend = PubmedBackend.__new__(PubmedBackend)
        with patch.dict("os.environ", {"NCBI_API_KEY": "synthetic-key", "USER_EMAIL": "fixture@example.test"}):
            output = backend.redact("api_key=synthetic-key&email=fixture@example.test")
            self.assertNotIn("synthetic-key", output)
            self.assertNotIn("fixture@example.test", output)


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.init(CONTEXT, ONTOLOGY)
        self.backend = FakeBackend()

    def collect(self, backend=None, run_id="offline-test"):
        return self.store.collect(backend or self.backend, run_id)

    def job(self):
        result = self.store.jobs("offline-test", batch_size=2)
        return load(result["jobs"][0]["path"]), result["jobs"][0]["path"]

    def include_all(self):
        result = self.store.jobs("offline-test", batch_size=2)
        for item in result["jobs"]:
            job = load(item["path"])
            output = response(self.store, job)
            self.store.import_evidence(item["path"], output, "synthetic-test-run")

    def test_screening_and_followup_keep_full_interpretation_vocabulary(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            ontology = normalize_ontology({"test": {"stress": ["stress", "restraint stress"]}})
            ontology["concepts"][0]["search_terms"] = ["stress"]
            store.init(CONTEXT, ontology)
            run = store.collect(FakeBackend(), "term-roles")
            self.assertEqual(run["status"], "collected")
            contextual = next(q for q in run["searches"].values() if q["lane"] == "contextual")
            self.assertNotIn('"restraint stress"[tiab]', contextual["query"])
            jobs = store.jobs("term-roles")
            for item in jobs["jobs"]:
                job = load(item["path"])
                if job["concept"]["id"] == "test/stress":
                    self.assertEqual(job["concept"]["terms"], ["restraint stress", "stress"])
                    self.assertEqual(job["concept"]["search_terms"], ["stress"])
            self.assertTrue(any(load(item["path"])["concept"]["id"] == "test/stress"
                                for item in jobs["jobs"]))
            packet = Store(folder).packet(concept_id="test/stress", limit=1)
            self.assertEqual(len(packet["concepts"]), 1)
            self.assertEqual(packet["concepts"][0]["terms"], ["restraint stress", "stress"])
            self.assertEqual(packet["concepts"][0]["search_terms"], ["stress"])
            self.assertEqual(len(packet["records"]), 1)
            self.assertTrue(store.audit()["ok"])

    def test_discovery_membership_caps_dedup_and_resume_cache(self):
        run = self.collect()
        self.assertEqual(run["status"], "collected")
        self.assertIn("record_hashes", run)
        self.assertNotIn("versions", run)
        articles = self.store.table("articles")
        self.assertEqual(len(articles), 2)
        self.assertTrue(all("abstract" in row and "source_snapshot" in row and "version_path" not in row
                            for row in articles))
        self.assertFalse((self.store.base / "versions").exists())
        self.assertEqual(len(self.store.table("membership")), 6)
        self.assertEqual(len({m["pmid"] for m in self.store.table("membership")}), 3)
        self.assertTrue(all(s["capped"] for s in run["searches"].values()))
        calls = len(self.backend.calls)
        self.collect()
        self.assertEqual(len(self.backend.calls), calls)
        self.assertTrue(self.store.audit()["ok"])

    def test_missing_records_retried_and_resume(self):
        self.backend.omit.add("900000002")
        run = self.collect()
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(run["missing_records"], ["900000002"])
        self.assertEqual(len([c for c in self.backend.calls if c[0] == "fetch"]), 2)
        self.backend.omit.clear()
        self.assertEqual(self.collect()["status"], "collected")

    def test_network_error_does_not_create_empty_success(self):
        self.backend.fail_fetch = True
        run = self.collect()
        self.assertEqual(run["status"], "incomplete")
        self.assertTrue(run["missing_records"])
        self.assertFalse(self.store.table("articles"))
        self.assertTrue(self.store.table("sources"))

    def test_missing_abstract_is_recorded_not_excluded(self):
        self.backend.records[0]["abstract"] = None
        self.collect()
        self.assertEqual(self.store.overview()["missing_abstracts"], 1)
        result = self.store.jobs("offline-test")
        self.assertTrue(all("900000003" not in load(j["path"])["assigned_pmids"] for j in result["jobs"]))
        self.assertEqual(self.store.overview()["assessment_records"], 0)

    def test_worker_waves_bounded_and_packet_complete(self):
        self.collect()
        result = self.store.jobs("offline-test", batch_size=1, wave_size=1)
        self.assertEqual(result["job_count"], 4)
        self.assertEqual(len(result["wave_paths"]), 4)
        for item in result["jobs"]:
            job = load(item["path"])
            self.assertEqual(len(job["assigned_pmids"]), 1)
            self.assertTrue(self.store.path(job["packet_path"]).exists())
        code = Path(result["wave_paths"][0]).read_text()
        self.assertIn("await runs.all", code)
        self.assertIn('"outputMode": "file-only"', code)
        self.assertNotIn("runs.host", code)
        with self.assertRaises(WaspError):
            self.store.jobs("offline-test", wave_size=257)

    def test_worker_wave_records_an_explicit_model_only_when_requested(self):
        self.collect()
        default = self.store.jobs("offline-test", batch_size=1, wave_size=1)
        self.assertIsNone(default["model"])
        self.assertNotIn('"model":', Path(default["wave_paths"][0]).read_text())
        pinned = self.store.jobs("offline-test", batch_size=1, wave_size=1,
                                 model="openai-codex/gpt-6.1-sol")
        self.assertEqual(pinned["model"], "openai-codex/gpt-6.1-sol")
        code = Path(pinned["wave_paths"][0]).read_text()
        self.assertIn('"model": "openai-codex/gpt-6.1-sol"', code)
        with self.assertRaises(WaspError):
            self.store.jobs("offline-test", model="   ")

    def test_worker_task_distinguishes_source_truncation_from_packet_failure(self):
        self.collect()
        code = Path(self.store.jobs("offline-test", batch_size=1, wave_size=1)["wave_paths"][0]).read_text()
        self.assertIn("SCREENING_FAILED", code)
        self.assertIn("ABSTRACT TRUNCATED AT 250 WORDS", code)
        self.assertIn("property of the PubMed record rather than a packet defect", code)
        self.assertNotIn("If any assigned text is truncated or unreadable, stop and report the failure", code)

    @unittest.skipUnless(shutil.which("node"), "Optional JavaScript workflow check needs Node")
    def test_dispatch_batches_preserve_order_and_stop_after_failure(self):
        self.collect()
        result = self.store.jobs("offline-test", batch_size=1, dispatch_size=2)
        code = Path(result["wave_paths"][0]).read_text()
        harness = '''
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const code = JSON.parse(process.argv[1]);
const fail = process.argv[2] === "fail";
const groups = [];
const logs = [];
const runs = { all: async function(items) {
  groups.push(items.length);
  return items.map((item, i) => ({ok: !(fail && i === 0), runId: item.key, outputReference: "synthetic-output"}));
}};
const output = await new AsyncFunction("runs", "console", code)(runs, {log: (...args) => logs.push(args.join(" "))});
console.log(JSON.stringify({groups, output, logs}));
'''
        for mode, expected in [("ok", [2, 2]), ("fail", [2])]:
            process = subprocess.run(["node", "--input-type=module", "-e", harness, json.dumps(code), mode],
                                     check=True, capture_output=True, text=True)
            value = json.loads(process.stdout)
            self.assertEqual(value["groups"], expected)
            self.assertEqual([row["key"] for row in value["output"]],
                             [item["job_id"] for item in result["jobs"][:sum(expected)]])
            self.assertIn("screening wave started", value["logs"][0])
            self.assertRegex(value["logs"][0], r"^\[\d{4}-\d{2}-\d{2}T.*[+-]\d{2}:\d{2} America/Chicago\]")
            self.assertIn("screening wave finished", value["logs"][-1])

    def test_oversize_abstract_not_truncated(self):
        self.backend.records[0]["abstract"] = "synthetic " * 10000
        self.collect()
        self.assertEqual(self.store.table("articles")[1]["abstract"], "synthetic " * 10000)
        with self.assertRaises(WaspError):
            self.store.jobs("offline-test")

    def test_exact_quote_and_runtime_provenance_import_idempotence(self):
        self.collect()
        job, path = self.job()
        output = response(self.store, job)
        first = self.store.import_evidence(path, output, "synthetic-run-001")
        second = self.store.import_evidence(path, output, "synthetic-run-001")
        self.assertEqual(first["imported"], 2)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(self.store.table("evidence")[0]["runtime_run_id"], "synthetic-run-001")
        self.assertTrue(self.store.audit()["ok"])

    def test_missing_duplicate_reordered_pmids_rejected(self):
        self.collect()
        job, path = self.job()
        rows = [assessment(p) for p in job["assigned_pmids"]]
        for invalid in (rows[:1], [rows[0], rows[0]], list(reversed(rows))):
            with self.assertRaises(WaspError):
                self.store.validate_assessments(path, response(self.store, job, invalid))

    def test_quote_normalization_unknown_enum_and_ambiguous_identity_rejected(self):
        self.collect()
        job, path = self.job()
        for changes in ({"quotation": "A paraphrase."}, {"direction": "probably"},
                        {"gene_identity": "ambiguous"}, {"direction_target": None}, {"finding": ""}):
            rows = [assessment(p) for p in job["assigned_pmids"]]
            rows[0].update(changes)
            with self.assertRaises(WaspError):
                self.store.validate_assessments(path, response(self.store, job, rows))

    def test_null_findings_and_needs_review_preserved(self):
        self.backend.records[0]["abstract"] = "No effect was detected in the synthetic experiment."
        self.collect()
        job, path = self.job()
        rows = [assessment(p) for p in job["assigned_pmids"]]
        rows[0].update(direction="none", quotation=self.backend.records[0]["abstract"])
        rows[1].update(decision="needs_review", gene_identity="ambiguous", direction="unclear", direction_target=None)
        self.store.import_evidence(path, response(self.store, job, rows), "synthetic-run-002")
        stored = self.store.table("evidence")
        self.assertEqual(stored[0]["direction"], "none")
        self.assertEqual(stored[1]["decision"], "needs_review")
        next_jobs = self.store.jobs("offline-test")
        self.assertTrue(any(rows[1]["pmid"] in load(j["path"])["assigned_pmids"] for j in next_jobs["jobs"]))

    def test_record_hashes_survive_refresh_and_new_session(self):
        first = self.collect()
        old = first["record_hashes"]["900000003"]
        self.backend.records[0]["abstract"] = "A revised synthetic abstract."
        second = self.store.collect(self.backend, "refresh-test", refresh=True)
        self.assertNotEqual(old, second["record_hashes"]["900000003"])
        self.assertEqual(self.store.article("900000003", old)["abstract"], record("900000003")["abstract"])
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.packet(pmids=["900000003"])["records"][0]["article"]["abstract"], "A revised synthetic abstract.")
        self.assertTrue(reopened.audit()["ok"])

    def test_corrupt_snapshot_or_packet_is_rejected(self):
        self.collect()
        job, path = self.job()
        output = response(self.store, job)
        self.store.path(job["packet_path"]).write_text("tampered")
        with self.assertRaises(WaspError):
            self.store.validate_assessments(path, output)
        ref = self.store.table("sources")[0]
        self.store.path(ref["path"]).write_text("{}")
        self.assertFalse(self.store.audit()["ok"])

    def test_fulltext_quota_per_run_cache_and_newest_unresolved_stop(self):
        self.collect()
        self.include_all()
        self.backend.fail_fulltext.add("900000003")
        state = self.store.fulltext(self.backend, "offline-test")
        self.assertEqual(state["retrieved"], 0)
        self.assertEqual(state["blocked"], "900000003")
        self.assertFalse(any(c[0] == "fulltext" and c[1] == "900000002" for c in self.backend.calls))
        self.backend.fail_fulltext.clear()
        state = self.store.fulltext(self.backend, "offline-test")
        self.assertEqual(state["retrieved"], 2)
        self.assertTrue(state["target_met"])
        calls = len(self.backend.calls)
        self.store.fulltext(self.backend, "offline-test")
        self.assertEqual(len(self.backend.calls), calls)
        self.assertTrue(self.store.audit()["ok"])

    def test_fulltext_order_prioritizes_nicotine_specific_candidates(self):
        self.collect()
        self.include_all()
        evidence = self.store.table("evidence")
        selected = set(load(self.store.base / "runs" / "offline-test.json")["record_hashes"])
        ids = sorted(selected, key=int)
        nicotine_pmid, other_pmid = ids[0], ids[-1]
        for row in evidence:
            if row["pmid"] == nicotine_pmid:
                row["concept_id"] = "drug/nicotine"
                row["phenotype_relevance"] = "indirect"
            elif row["pmid"] == other_pmid:
                row["concept_id"] = "test/stress"
                row["phenotype_relevance"] = "direct"
        self.store.save_table("evidence", evidence)

        state = self.store.fulltext(self.backend, "offline-test")
        self.assertEqual(state["priority_groups"]["nicotine_specific"], [nicotine_pmid])
        self.assertEqual(state["order"][0], nicotine_pmid)
        self.assertEqual(state["priority_groups"]["other_direct_phenotype_relevance"], [other_pmid])
        self.assertIn("PubMed pub_date order within each group", state["priority_policy"])

    def test_fulltext_explicit_pmid_list_bypasses_priority_and_filters(self):
        self.collect()
        self.include_all()
        ids = sorted(set(load(self.store.base / "runs" / "offline-test.json")["record_hashes"]), key=int)
        first, second = ids[1], ids[0]
        state = self.store.fulltext(self.backend, "offline-test", pmids=[first, second])
        self.assertEqual(state["selection_mode"], "explicit")
        self.assertEqual(state["quota"], 2)
        self.assertEqual(state["order"], [first, second])
        self.assertEqual(state["priority_groups"], {"explicit": [first, second]})
        self.assertEqual(state["retrieved"], 2)
        self.assertTrue(state["target_met"])
        self.assertFalse(any(call[0] == "order_ids" for call in self.backend.calls))
        self.assertEqual([call[1] for call in self.backend.calls if call[0] == "fulltext"], [first, second])
        self.assertTrue(self.store.audit()["ok"])

    def test_fulltext_explicit_target_tries_full_list_until_successes_and_allows_next_category(self):
        self.collect()
        self.include_all()
        ids = sorted(set(load(self.store.base / "runs" / "offline-test.json")["record_hashes"]), key=int)
        self.backend.unavailable.add(ids[0])
        first = self.store.fulltext(self.backend, "offline-test", pmids=ids, target=1)
        self.assertEqual(first["quota"], 1)
        self.assertEqual(first["retrieved"], 1)
        self.assertTrue(first["target_met"])
        self.assertEqual(first["outcomes"][ids[0]]["status"], "not available from any route")
        self.assertEqual([call[1] for call in self.backend.calls if call[0] == "fulltext"], ids)

        second = self.store.fulltext(self.backend, "offline-test", pmids=[ids[1], ids[0]], target=1)
        self.assertEqual(second["retrieved"], 1)
        self.assertEqual(second["order"], [ids[1], ids[0]])
        self.assertTrue(self.store.audit()["ok"])

    def test_fulltext_explicit_target_does_not_precount_a_cached_later_candidate(self):
        self.collect()
        self.include_all()
        ids = sorted(load(self.store.base / "runs" / "offline-test.json")["record_hashes"], key=int)
        self.store.fulltext(self.backend, "offline-test", pmids=[ids[1]], target=1)
        state = self.store.fulltext(self.backend, "offline-test", pmids=ids, target=1)
        self.assertEqual(state["retrieved"], 1)
        self.assertTrue(state["target_met"])
        self.assertEqual([call[1] for call in self.backend.calls if call[0] == "fulltext"], [ids[1], ids[0]])
        self.assertTrue(self.store.audit()["ok"])

    def test_fulltext_explicit_selection_ignores_decision_and_relevance_filters(self):
        self.collect()
        self.include_all()
        evidence = self.store.table("evidence")
        for row in evidence:
            row["decision"] = "exclude"
            row["phenotype_relevance"] = "none"
        self.store.save_table("evidence", evidence)
        ids = sorted(set(load(self.store.base / "runs" / "offline-test.json")["record_hashes"]), key=int)
        state = self.store.fulltext(self.backend, "offline-test", pmids=[ids[0]])
        self.assertEqual(state["order"], [ids[0]])
        self.assertEqual(state["retrieved"], 1)

    def test_fulltext_explicit_selection_rejects_unknown_or_empty_lists(self):
        self.collect()
        self.include_all()
        with self.assertRaises(WaspError):
            self.store.fulltext(self.backend, "offline-test", pmids=["999999999"])
        with self.assertRaises(WaspError):
            self.store.fulltext(self.backend, "offline-test", pmids=["", "   "])

    def test_fulltext_explicit_selection_cannot_replace_a_started_priority_order(self):
        self.collect()
        self.include_all()
        ids = sorted(set(load(self.store.base / "runs" / "offline-test.json")["record_hashes"]), key=int)
        self.store.fulltext(self.backend, "offline-test")
        with self.assertRaises(WaspError):
            self.store.fulltext(self.backend, "offline-test", pmids=[ids[0]])

    def test_route_confirmed_absence_is_terminal_and_does_not_block(self):
        self.collect()
        self.include_all()
        self.backend.unavailable.add("900000003")
        state = self.store.fulltext(self.backend, "offline-test")
        outcome = state["outcomes"]["900000003"]
        self.assertEqual(outcome["status"], "not available from any route")
        self.assertEqual(outcome["confirmed_by"], ["synthetic"])
        self.assertIsNone(state["blocked"])
        self.assertEqual(state["order"], ["900000003", "900000002"])
        self.assertEqual(state["retrieved"], 1)
        self.assertFalse(state["target_met"])
        self.assertTrue(state["candidate_pool_exhausted"])
        self.assertTrue(any(c[0] == "fulltext" and c[1] == "900000002" for c in self.backend.calls))

    def test_fulltext_attempt_limit_explicit_and_pmc_link_not_availability(self):
        self.collect()
        self.include_all()
        self.backend.available.remove("900000003")
        state = self.store.fulltext(self.backend, "offline-test", max_attempts=1)
        self.assertFalse(state["target_met"])
        self.assertFalse(state["candidate_pool_exhausted"])
        self.assertEqual(state["outcomes"]["900000003"]["status"], "no PMCID known")
        state = self.store.fulltext(self.backend, "offline-test")
        self.assertEqual(state["retrieved"], 1)
        self.assertTrue(state["candidate_pool_exhausted"])

    def test_import_recovers_after_import_ledger_checkpoint_loss(self):
        self.collect()
        job, path = self.job()
        output = response(self.store, job)
        self.store.import_evidence(path, output, "synthetic-runtime")
        self.store.save_table("assessment_imports", [])
        result = self.store.import_evidence(path, output, "synthetic-runtime")
        self.assertTrue(result["reused"])
        self.assertEqual(len(self.store.table("evidence")), 2)
        self.assertEqual(len(self.store.table("assessment_imports")), 1)

    def test_latest_needs_review_overrides_old_include_for_resumption(self):
        self.collect()
        job, path = self.job()
        self.store.import_evidence(path, response(self.store, job), "synthetic-runtime")
        rows = [assessment(p) for p in job["assigned_pmids"]]
        rows[0].update(decision="needs_review", gene_identity="ambiguous", direction="unclear", direction_target=None)
        self.store.import_evidence(path, response(self.store, job, rows), "synthetic-runtime-2")
        pending = self.store.jobs("offline-test")
        self.assertTrue(any(rows[0]["pmid"] in load(j["path"])["assigned_pmids"] for j in pending["jobs"]))

    def test_summary_boolean_and_manifest_identity_are_checked(self):
        self.collect()
        job, path = self.job()
        output = response(self.store, job)
        values = [json.loads(line) for line in output.read_text().splitlines()]
        values[-1]["summary"]["capped"] = 1
        atomic(output, values, jsonl=True)
        with self.assertRaises(WaspError):
            self.store.validate_assessments(path, output)
        output = response(self.store, job)
        job["capped"] = False
        atomic(path, job)
        with self.assertRaises(WaspError):
            self.store.validate_assessments(path, output)

    def test_audit_detects_changed_finding_and_changed_abstract_version(self):
        self.collect()
        job, path = self.job()
        self.store.import_evidence(path, response(self.store, job), "synthetic-runtime")
        evidence = self.store.table("evidence")
        evidence[0]["finding"] = "An unsupported altered interpretation"
        self.store.save_table("evidence", evidence)
        self.assertFalse(self.store.audit()["ok"])
        articles = self.store.table("articles")
        articles[0]["abstract"] = "Altered synthetic abstract"
        self.store.save_table("articles", articles)
        self.assertFalse(self.store.audit()["ok"])

    def test_screening_coverage_distinguishes_complete_ids_from_complete_assessment(self):
        backend = FakeBackend(records=[record(900000003), record(900000002)])
        self.collect(backend)
        self.assertFalse(any(s["scope_screening_complete"] for s in self.store.overview()["runs"][0]["strata"]))
        self.include_all()
        self.assertTrue(all(s["scope_screening_complete"] for s in self.store.overview()["runs"][0]["strata"]))

    def test_reviews_can_be_read_but_remain_nonprimary_evidence(self):
        self.collect()
        result = self.store.jobs("offline-test")
        for item in result["jobs"]:
            job = load(item["path"])
            rows = [assessment(p) for p in job["assigned_pmids"]]
            for row in rows:
                row["study_design"] = "review"
            self.store.import_evidence(item["path"], response(self.store, job, rows), "synthetic-runtime")
        self.assertFalse(any(e["primary_evidence"] for e in self.store.table("evidence")))
        self.assertEqual(self.store.fulltext(self.backend, "offline-test")["retrieved"], 2)

    def test_native_screener_output_fixture_round_trip(self):
        from wasp import FixtureBackend
        fixtures = Path(__file__).resolve().parent / "fixtures"
        store = Store(Path(self.temp.name) / "native-fixture")
        store.init(load(fixtures / "context.json"), fixtures / "ontology.json")
        store.collect(FixtureBackend(fixtures / "retrieval.json"), "native-fixture")
        jobs = store.jobs("native-fixture")
        item = next(j for j in jobs["jobs"] if load(j["path"])["concept"]["id"] == "test/stress")
        imported = store.import_evidence(item["path"], fixtures / "screener-response.jsonl", "synthetic-fixture-validation")
        self.assertEqual(imported["imported"], 6)
        self.assertEqual(store.overview()["missing_abstracts"], 1)
        self.assertTrue(store.audit()["ok"])
        packet = Store(store.root).packet(pmids=["900000005"])
        self.assertTrue(packet["records"][0]["article"]["is_preprint"])
        self.assertEqual(packet["records"][0]["assessments"][0]["direction"], "none")

    def test_missing_exclusion_quotation_field_is_rejected_before_import(self):
        self.collect()
        job, path = self.job()
        rows = [assessment(p) for p in job["assigned_pmids"]]
        rows[0]["decision"] = "exclude"
        del rows[0]["quotation"]
        with self.assertRaises(WaspError):
            self.store.validate_assessments(path, response(self.store, job, rows))

    def test_fulltext_license_index_tampering_is_detected(self):
        self.collect()
        self.include_all()
        self.store.fulltext(self.backend, "offline-test")
        records = self.store.table("fulltexts")
        records[0]["license"] = "invented permission"
        self.store.save_table("fulltexts", records)
        self.assertFalse(self.store.audit()["ok"])

    def test_workspace_scope_and_path_escape_rejected(self):
        other = deepcopy(CONTEXT)
        other["phenotype"] = "different question"
        with self.assertRaises(WaspError):
            self.store.init(other, ONTOLOGY)
        with self.assertRaises(WaspError):
            self.store.path("../../outside.json")

    def test_lock_prevents_concurrent_coordinators(self):
        with self.store.lock():
            with self.assertRaises(WaspError):
                with Store(self.temp.name).lock():
                    pass


if __name__ == "__main__":
    unittest.main()
