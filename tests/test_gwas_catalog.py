"""Offline tests for the GWAS Catalog MCP association lane."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from gwas_catalog import (CatalogError, CatalogMCP, CaptureError, assess_group, infer_tool,  # noqa: E402
                          normalize_association, page_info, resolve_endpoint, unwrap, valid_phenotype_id)
from wasp_core import WaspError, Store  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKILL = Path(__file__).resolve().parents[1]
CAPTURES = json.loads((FIXTURES / "gwas_catalog.json").read_text(encoding="utf-8"))["captures"]
HUMAN_CONTEXT = json.loads((FIXTURES / "context.human.json").read_text(encoding="utf-8"))


def envelope(name, **overrides):
    value = json.loads(json.dumps(CAPTURES[name]))
    value.update(overrides)
    return value


class FakeTransport:
    """Deterministic MCP transport. Never a fallback for a failed live call."""

    def __init__(self, pages=(), traits=None, fail_first=0):
        self.pages = list(pages)
        self.traits = traits
        self.fail_first = fail_first
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload.get("method"))
        if self.fail_first:
            self.fail_first -= 1
            return "data: " + json.dumps({"jsonrpc": "2.0", "id": payload["id"],
                                          "error": {"code": -32000, "message": "temporary"}})
        if payload["method"] == "initialize":
            envelope = {"protocolVersion": "2025-06-18", "capabilities": {},
                        "serverInfo": {"name": "fake", "version": "0"}}
        else:
            arguments = payload["params"]["arguments"]
            name = payload["params"]["name"]
            if name == "gwascatalog_get_associations":
                envelope = next(item for item in self.pages
                                if item["pagination"]["page"] == arguments["page"])
            else:
                envelope = dict(self.traits)
            envelope = envelope | {"tool": name}
        return "data: " + json.dumps({"jsonrpc": "2.0", "id": payload["id"],
                                      "result": {"content": [{"type": "text", "text": json.dumps(envelope)}],
                                                 "structuredContent": envelope, "isError": False}})


class ParsingTests(unittest.TestCase):
    def test_valid_phenotype_id(self):
        for value in ("EFO_0000001", "MONDO_0008575", "OBA_1001087", "EFO_1"):
            self.assertTrue(valid_phenotype_id(value), value)
        for value in ("opioid use disorder", "EFO_", "1EFO_0000001", "", None):
            self.assertFalse(valid_phenotype_id(value), value)

    def test_unwrap_accepts_tool_result_and_bare_envelope(self):
        value = envelope("traits")
        self.assertEqual(unwrap(value)[1]["data"], value["data"])
        wrapped = {"tool": "gwascatalog_get_traits", "structuredContent": value,
                   "content": [{"type": "text", "text": json.dumps(value)}]}
        self.assertEqual(unwrap(wrapped), ("gwascatalog_get_traits", value))
        text_only = {"content": [{"type": "text", "text": json.dumps(value)}]}
        self.assertEqual(unwrap(text_only)[1], value)

    def test_unwrap_rejects_unknown_shape(self):
        with self.assertRaises(CaptureError):
            unwrap({"not": "a capture"})

    def test_infer_tool_from_row_shape(self):
        self.assertEqual(infer_tool(envelope("traits")), "gwascatalog_get_traits")
        self.assertEqual(infer_tool(envelope("test_gene_page_0")), "gwascatalog_get_associations")
        self.assertEqual(infer_tool(envelope("studies")), "gwascatalog_get_studies")

    def test_page_info_requires_integer_pagination(self):
        with self.assertRaises(CaptureError):
            page_info({"data": []})
        with self.assertRaises(CaptureError):
            page_info({"data": [], "pagination": {"page": 0}})

    def test_normalize_association_requires_integer_id(self):
        with self.assertRaises(CaptureError):
            normalize_association({"association_id": "9000001"})

    def test_normalize_association_stringifies_pubmed_id(self):
        value = normalize_association(CAPTURES["test_gene_page_1"]["data"][0])
        self.assertEqual(value["pubmed_id"], "900000011")
        self.assertEqual(value["snp_effect_allele"], ["rs9000003-T"])


class GroupAssessmentTests(unittest.TestCase):
    def test_complete_two_page_group(self):
        value = assess_group([envelope("test_gene_page_0"), envelope("test_gene_page_1")])
        self.assertTrue(value["complete"], value["incomplete_reasons"])
        self.assertEqual((value["row_count"], value["total_results"], value["pages_returned"]),
                         (3, 3, [0, 1]))

    def test_empty_group_is_complete(self):
        value = assess_group([envelope("other_gene_empty")])
        self.assertTrue(value["complete"], value["incomplete_reasons"])
        self.assertEqual(value["row_count"], 0)

    def test_missing_page_is_incomplete(self):
        value = assess_group([envelope("test_gene_page_0")])
        self.assertFalse(value["complete"])
        self.assertEqual(value["missing_pages"], [1])
        self.assertTrue(any("missing pages" in reason for reason in value["incomplete_reasons"]))

    def test_duplicate_association_id_is_incomplete(self):
        second = envelope("test_gene_page_1")
        second["data"][0]["association_id"] = 9000001
        value = assess_group([envelope("test_gene_page_0"), second])
        self.assertFalse(value["complete"])
        self.assertTrue(any("duplicate association_id" in reason for reason in value["incomplete_reasons"]))

    def test_row_count_mismatch_is_incomplete(self):
        page = envelope("test_gene_page_1")
        page["data"] = []
        value = assess_group([envelope("test_gene_page_0"), page])
        self.assertFalse(value["complete"])
        self.assertTrue(any("does not match total_results" in reason for reason in value["incomplete_reasons"]))

    def test_inconsistent_totals_are_incomplete(self):
        page = envelope("test_gene_page_1")
        page["pagination"]["total_results"] = 9
        value = assess_group([envelope("test_gene_page_0"), page])
        self.assertFalse(value["complete"])
        self.assertTrue(any("inconsistent" in reason for reason in value["incomplete_reasons"]))

    def test_truncated_page_is_incomplete(self):
        page = envelope("test_gene_page_1")
        page["pagination"]["truncated"] = True
        value = assess_group([envelope("test_gene_page_0"), page])
        self.assertFalse(value["complete"])
        self.assertTrue(any("truncated" in reason for reason in value["incomplete_reasons"]))


class ClientTests(unittest.TestCase):
    def client(self, transport, **options):
        return CatalogMCP("http://example.invalid/mcp", retries=1, opener=transport, **options)

    def test_pages_until_no_next_page(self):
        transport = FakeTransport(pages=[envelope("test_gene_page_0"), envelope("test_gene_page_1")])
        pages = self.client(transport).associations("EFO_0000001", "WASP_TEST_GENE", size=2)
        self.assertEqual([page_info(page)["page"] for page in pages], [0, 1])
        self.assertEqual(transport.calls.count("initialize"), 1)

    def test_max_pages_bound_leaves_group_incomplete(self):
        transport = FakeTransport(pages=[envelope("test_gene_page_0"), envelope("test_gene_page_1")])
        pages = self.client(transport).associations("EFO_0000001", "WASP_TEST_GENE", size=2, max_pages=1)
        self.assertEqual(len(pages), 1)
        self.assertFalse(assess_group(pages)["complete"])

    def test_transient_error_is_retried(self):
        import gwas_catalog
        original, gwas_catalog.time.sleep = gwas_catalog.time.sleep, lambda _seconds: None
        try:
            transport = FakeTransport(pages=[envelope("other_gene_empty")], fail_first=1)
            pages = self.client(transport).associations("EFO_0000001", "WASP_OTHER_GENE", size=2)
        finally:
            gwas_catalog.time.sleep = original
        self.assertEqual(len(pages), 1)
        self.assertEqual(assess_group(pages)["row_count"], 0)

    def test_server_error_is_raised(self):
        transport = FakeTransport(traits=envelope("traits"), fail_first=3)
        with self.assertRaises(CatalogError):
            self.client(transport).traits(efo_trait="synthetic")

    def test_tool_error_text_is_raised_without_retry(self):
        calls = []

        def opener(payload):
            calls.append(payload["method"])
            if payload["method"] == "initialize":
                result = {"protocolVersion": "2025-06-18"}
            else:
                result = {"content": [{"type": "text",
                                        "text": "Error executing tool gwascatalog_get_associations: size must be <= 50"}],
                          "isError": True}
            return "data: " + json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result})

        with self.assertRaises(CatalogError) as caught:
            CatalogMCP("http://example.invalid/mcp", retries=2, opener=opener).\
                associations("EFO_0000001", "WASP_TEST_GENE", size=2)
        self.assertIn("size must be <= 50", str(caught.exception))
        self.assertEqual(calls.count("tools/call"), 1)

    def test_page_size_is_clamped_to_the_server_maximum(self):
        seen = []

        def opener(payload):
            if payload["method"] == "tools/call":
                seen.append(payload["params"]["arguments"]["size"])
                result = {"structuredContent": envelope("other_gene_empty"), "isError": False}
            else:
                result = {"protocolVersion": "2025-06-18"}
            return "data: " + json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result})

        CatalogMCP("http://example.invalid/mcp", opener=opener).\
            associations("EFO_0000001", "WASP_OTHER_GENE", size=5000)
        self.assertEqual(seen, [50])

    def test_unreachable_endpoint_raises(self):
        client = CatalogMCP("http://127.0.0.1:1/mcp", retries=0, timeout=1)
        with self.assertRaises(CatalogError):
            client.traits(efo_trait="synthetic")

    def test_resolve_endpoint_from_mcp_json(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / ".pi"
            config.mkdir()
            (config / "mcp.json").write_text(json.dumps(
                {"mcpServers": {"gwas-mcp": {"url": "https://example.invalid/mcp"}}}), encoding="utf-8")
            self.assertEqual(resolve_endpoint(project_root=folder), "https://example.invalid/mcp")
        with tempfile.TemporaryDirectory() as home:
            with unittest.mock.patch.dict(os.environ, {"HOME": home, "WASP_GWAS_MCP_URL": ""}):
                with self.assertRaises(CatalogError):
                    resolve_endpoint(project_root="/nonexistent")
        self.assertEqual(resolve_endpoint(explicit="https://explicit.invalid/mcp"),
                         "https://explicit.invalid/mcp")


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.store.init(dict(HUMAN_CONTEXT), FIXTURES / "ontology.json")

    def tearDown(self):
        self.temp.cleanup()

    def captures(self, names):
        return [{"name": name + ".json", "payload": envelope(name)} for name in names]

    def ingest(self, names=("test_gene_page_0", "test_gene_page_1", "other_gene_empty"), **options):
        options.setdefault("run_id", "gwas-1")
        options.setdefault("phenotype_ids", ["EFO_0000001"])
        return self.store.ingest_associations(self.captures(names), **options)

    def test_records_pairs_evidence_and_report(self):
        result = self.ingest()
        self.assertEqual(result["state"], "collected")
        self.assertEqual(result["pairs"], 2)
        rows = {(row["gene"], row["phenotype_id"]): row for row in self.store.table("associations")}
        gene = rows[("WASP_TEST_GENE", "EFO_0000001")]
        self.assertTrue(gene["complete"])
        self.assertEqual(gene["association_count"], 3)
        self.assertEqual(gene["phenotype_name"], "synthetic behavioral phenotype")
        self.assertEqual(gene["strongest_p_value"], 5e-12)
        self.assertEqual(len(gene["sources"]), 2)
        other = rows[("WASP_OTHER_GENE", "EFO_0000001")]
        self.assertEqual(other["association_count"], 0)
        self.assertIsNone(other["strongest_p_value"])
        self.assertEqual(len(self.store.table("association_evidence")), 3)
        report = self.store.association_report(run_id="gwas-1")
        pair = next(item for item in report["pairs"] if item["gene"] == "WASP_TEST_GENE")
        self.assertEqual(pair["pmids"], ["900000010", "900000011"])
        self.assertEqual(pair["accessions"], ["GCST90000001", "GCST90000002"])
        self.assertEqual(pair["strongest_association"]["association_id"], 9000003)
        self.assertEqual(pair["effect_alleles"], ["rs9000001-C", "rs9000002-A", "rs9000003-T"])
        self.assertEqual(report["evidence_records"], 3)
        self.assertTrue(self.store.audit()["ok"], self.store.audit()["errors"])

    def test_incomplete_group_is_recorded_not_hidden(self):
        result = self.ingest(("test_gene_page_0", "other_gene_empty"))
        self.assertEqual(result["state"], "incomplete")
        self.assertTrue(result["incomplete_pairs"])
        report = self.store.association_report(run_id="gwas-1")
        self.assertTrue(any("Incomplete capture coverage" in item for item in report["warnings"]))

    def test_missing_gene_group_is_recorded(self):
        result = self.ingest(("test_gene_page_0", "test_gene_page_1"))
        self.assertEqual(result["missing_groups"], ["WASP_OTHER_GENE EFO_0000001"])
        self.assertEqual(result["state"], "incomplete")

    def test_capture_gene_must_be_in_frozen_context(self):
        value = envelope("test_gene_page_0")
        value["query"]["mapped_gene"] = "NOT_IN_CONTEXT"
        with self.assertRaises(WaspError) as caught:
            self.store.ingest_associations([{"name": "x.json", "payload": value}], "gwas-1", ["EFO_0000001"])
        self.assertIn("not in the frozen context", str(caught.exception))

    def test_capture_phenotype_must_be_requested(self):
        value = envelope("test_gene_page_0")
        value["query"]["efo_id"] = "EFO_0000002"
        with self.assertRaises(WaspError) as caught:
            self.store.ingest_associations([{"name": "x.json", "payload": value}], "gwas-1", ["EFO_0000001"])
        self.assertIn("not requested for this run", str(caught.exception))

    def test_trait_capture_is_rejected_for_associations(self):
        with self.assertRaises(WaspError) as caught:
            self.store.ingest_associations([{"name": "traits.json", "payload": envelope("traits")}],
                                           "gwas-1", ["EFO_0000001"])
        self.assertIn("is not a gwascatalog_get_associations result", str(caught.exception))

    def test_duplicate_page_capture_is_rejected(self):
        with self.assertRaises(WaspError) as caught:
            self.ingest(("test_gene_page_0", "test_gene_page_0", "test_gene_page_1", "other_gene_empty"))
        self.assertIn("Duplicate page capture", str(caught.exception))

    def test_invalid_phenotype_id_is_rejected(self):
        with self.assertRaises(WaspError) as caught:
            self.store.ingest_associations([], "gwas-1", ["opioid use disorder"])
        self.assertIn("Invalid phenotype ID", str(caught.exception))

    def test_empty_group_uses_a_resolved_trait_label(self):
        self.store.save_trait_labels({"EFO_0000001": "synthetic behavioral phenotype"})
        second = envelope("other_gene_empty")
        second["query"]["efo_id"] = "EFO_0000001"
        self.ingest()
        report = self.store.association_report(run_id="gwas-1")
        labels = {item["phenotype_id"]: item["phenotype_name"] for item in report["pairs"]}
        self.assertEqual(labels["EFO_0000001"], "synthetic behavioral phenotype")
        rows = self.store.table("associations")
        self.assertTrue(all(row["phenotype_name"] for row in rows), rows)

    def test_trait_labels_reject_non_object_input(self):
        with self.assertRaises(WaspError):
            self.store.save_trait_labels(["EFO_0000001"])

    def test_rerun_is_idempotent_and_scope_change_is_rejected(self):
        self.ingest()
        first = len(self.store.table("associations"))
        self.ingest()
        self.assertEqual(len(self.store.table("associations")), first)
        self.assertEqual(len(self.store.table("association_evidence")), 3)
        with self.assertRaises(WaspError) as caught:
            self.ingest(phenotype_ids=["EFO_0000001", "EFO_0000002"])
        self.assertIn("scope changed", str(caught.exception))

    def test_nonhuman_workspace_requires_explicit_transfer(self):
        context = json.loads((FIXTURES / "context.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.init(dict(context), FIXTURES / "ontology.json")
            captures = self.captures(("test_gene_page_0", "test_gene_page_1"))
            with self.assertRaises(WaspError) as caught:
                store.ingest_associations(captures, "gwas-1", ["EFO_0000001"])
            self.assertIn("cross-species-transfer", str(caught.exception))
            store.ingest_associations(captures, "gwas-1", ["EFO_0000001"], cross_species_transfer=True)
            report = store.association_report(run_id="gwas-1")
            self.assertTrue(any("Cross-species transfer claimed" in item for item in report["warnings"]))

    def test_audit_detects_tampered_evidence_row(self):
        self.ingest()
        rows = self.store.table("association_evidence")
        rows[0]["p_value"] = 0.5
        self.store.save_table("association_evidence", rows)
        self.assertFalse(self.store.audit()["ok"])

    def test_audit_detects_changed_capture(self):
        self.ingest()
        ref = self.store.table("association_evidence")[0]["source"]
        path = self.store.path(ref["path"])
        path.chmod(0o644)
        path.write_text(json.dumps({"tampered": True}), encoding="utf-8")
        self.assertFalse(self.store.audit()["ok"])


class CliTests(unittest.TestCase):
    """Subprocess smoke test of the documented association commands."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments):
        return subprocess.run([sys.executable, str(SKILL / "scripts" / "wasp.py"), *arguments],
                              capture_output=True, text=True, check=False)

    def capture_file(self, name, content):
        path = self.root / name
        path.write_text(json.dumps(content), encoding="utf-8")
        return str(path)

    def test_documented_association_flow(self):
        result = self.cli("init", str(self.root), "--context", str(FIXTURES / "context.human.json"),
                          "--ontology", str(FIXTURES / "ontology.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("acknowledge-license", str(self.root), "--source", "gwas_catalog")
        self.assertEqual(result.returncode, 0, result.stderr)
        traits = self.capture_file("traits.json", envelope("traits"))
        result = self.cli("phenotype-search", str(self.root), "--capture", traits)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["traits"][0]["efo_id"], "EFO_0000001")
        captures = [self.capture_file(name + ".json", envelope(name))
                    for name in ("test_gene_page_0", "test_gene_page_1", "other_gene_empty")]
        command = ["associations", str(self.root), "--run-id", "gwas-cli", "--phenotype", "EFO_0000001"]
        for path in captures:
            command += ["--capture", path]
        result = self.cli(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "collected")
        report = self.root / "genetic-associations.json"
        result = self.cli("association-report", str(self.root), "--run-id", "gwas-cli",
                          "--output", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["pairs"], 2)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["pair_count"], 2)
        result = self.cli("audit", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("status", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["association_evidence_records"], 3)

    def test_associations_requires_the_license_notification(self):
        self.cli("init", str(self.root), "--context", str(FIXTURES / "context.human.json"),
                 "--ontology", str(FIXTURES / "ontology.json"))
        result = self.cli("associations", str(self.root), "--run-id", "gwas-cli",
                          "--phenotype", "EFO_0000001", "--endpoint", "http://127.0.0.1:1/mcp")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GWAS Catalog terms", result.stderr)

    def test_phenotype_search_needs_query_id_or_capture(self):
        self.cli("init", str(self.root), "--context", str(FIXTURES / "context.human.json"),
                 "--ontology", str(FIXTURES / "ontology.json"))
        result = self.cli("phenotype-search", str(self.root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--query, --efo-id or --capture", result.stderr)


if __name__ == "__main__":
    unittest.main()
