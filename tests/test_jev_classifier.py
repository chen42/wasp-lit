"""Offline tests for the harness-independent Jev triage classifier and cross-harness CLI features."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from jev_classifier import (  # noqa: E402
    DEFAULT_JEV_MODEL,
    JevCaptureError,
    JevClient,
    JevError,
    build_questions,
    build_state,
    normalize_triage_row,
    redact_jev_error,
    resolve_jev_config,
)
from wasp_core import Store, WaspError, load  # noqa: E402
from test_wasp import CONTEXT, FakeBackend, ONTOLOGY, assessment, record  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]


class JevUnitTests(unittest.TestCase):
    def test_build_state_and_questions(self):
        gene = CONTEXT["genes"][0]
        concept = {"id": "test/stress", "category": "test", "name": "stress", "terms": ["stress"]}
        art = record("900000001") | {"source_version": "sha-test"}
        state = build_state(gene, concept, CONTEXT, art)
        self.assertEqual(state["gene"]["symbol"], "WASP_TEST_GENE")
        self.assertEqual(state["concept"]["id"], "test/stress")
        self.assertEqual(state["article"]["pmid"], "900000001")
        questions = build_questions()
        self.assertEqual([q["id"] for q in questions],
                         ["gene_identity", "concept_addressed", "species_in_scope", "decision"])

    def test_never_hard_exclude_reroutes_exclude_to_needs_review(self):
        raw = {
            "pmid": "900000001",
            "gene": "WASP_TEST_GENE",
            "concept_id": "test/stress",
            "source_version": "v1",
            "answers": {
                "gene_identity": {"value": "confirmed"},
                "concept_addressed": {"value": False},
                "decision": {"value": "exclude", "probability": 0.94},
            },
        }
        safe = normalize_triage_row(raw, policy="never-hard-exclude")
        self.assertEqual(safe["raw_decision"], "exclude")
        self.assertEqual(safe["effective_decision"], "needs_review")
        self.assertEqual(safe["confidence"], 0.94)
        self.assertEqual(safe["model"], DEFAULT_JEV_MODEL)

        unfiltered = normalize_triage_row(raw, policy="raw")
        self.assertEqual(unfiltered["effective_decision"], "exclude")

    def test_ambiguous_gene_identity_always_requires_review(self):
        raw = {
            "pmid": "900000001",
            "gene": "WASP_TEST_GENE",
            "concept_id": "test/stress",
            "source_version": "v1",
            "gene_identity": "ambiguous",
            "concept_addressed": True,
            "decision": "include",
            "confidence": 0.85,
        }
        for policy in ("never-hard-exclude", "raw"):
            normalized = normalize_triage_row(raw, policy=policy)
            self.assertEqual(normalized["effective_decision"], "needs_review")

    def test_invalid_triage_rows_rejected(self):
        base = {
            "pmid": "900000001",
            "gene": "WASP_TEST_GENE",
            "concept_id": "test/stress",
            "source_version": "v1",
            "gene_identity": "confirmed",
            "concept_addressed": True,
            "decision": "include",
        }
        for bad in (
            {"pmid": "abc"},
            {"gene_identity": "unknown"},
            {"concept_addressed": "yes"},
            {"decision": "maybe"},
            {"confidence": 1.5},
            {"confidence": True},
        ):
            row = deepcopy(base)
            row.update(bad)
            with self.assertRaises(JevCaptureError):
                normalize_triage_row(row)

    def test_client_retries_and_redacts_secrets(self):
        calls = []

        def opener(payload):
            calls.append(payload["model"])
            if len(calls) == 1:
                raise OSError("temporary failure with Bearer secret-token-123")
            return json.dumps({
                "model": "typesafe/jev-latest",
                "answers": {
                    "gene_identity": "confirmed",
                    "concept_addressed": True,
                    "decision": {"value": "include", "probability": 0.91},
                },
            })

        import jev_classifier
        original_sleep = jev_classifier.time.sleep
        jev_classifier.time.sleep = lambda _s: None
        try:
            client = JevClient("https://jev.invalid/classify", "secret-token-123", retries=1, opener=opener)
            result = client.classify_one(
                CONTEXT["genes"][0],
                {"id": "test/stress", "category": "test", "name": "stress", "terms": ["stress"]},
                CONTEXT,
                record("900000001") | {"source_version": "v1"},
            )
        finally:
            jev_classifier.time.sleep = original_sleep
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["pmid"], "900000001")
        with patch.dict(os.environ, {"WASP_JEV_API_KEY": "secret-token-123"}):
            redacted = redact_jev_error("failed with secret-token-123 and token=abc")
            self.assertNotIn("secret-token-123", redacted)
            self.assertIn("<redacted>", redacted)

    def test_resolve_jev_config_requires_url_and_key_and_reads_dotenv(self):
        with tempfile.TemporaryDirectory() as fake_home:
            env_file = Path(fake_home) / ".env"
            with patch.dict(os.environ, {"WASP_JEV_API_URL": "", "TYPESAFE_CLASSIFY_URL": "",
                                         "WASP_JEV_API_KEY": "", "TYPESAFE_API_KEY": ""}, clear=False):
                with self.assertRaises(JevError):
                    resolve_jev_config(env_path=env_file)
            env_file.write_text('WASP_JEV_API_URL="https://dotenv.invalid/v1"\nTYPESAFE_API_KEY=dotenv-secret\n',
                                encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                for k in ("WASP_JEV_API_URL", "TYPESAFE_CLASSIFY_URL", "WASP_JEV_API_KEY", "TYPESAFE_API_KEY"):
                    os.environ.pop(k, None)
                cfg = resolve_jev_config(env_path=env_file)
                self.assertEqual(cfg["url"], "https://dotenv.invalid/v1")
                self.assertEqual(cfg["api_key"], "dotenv-secret")
                self.assertEqual(cfg["model"], DEFAULT_JEV_MODEL)


class CrossHarnessStoreAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.init(CONTEXT, ONTOLOGY)
        self.backend = FakeBackend()
        self.run = self.store.collect(self.backend, "offline-test")

    def cli(self, *arguments, stdin_text=None, env=None):
        return subprocess.run(
            [sys.executable, str(SKILL / "scripts" / "wasp.py"), *arguments],
            input=stdin_text,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_triage_ingest_prioritizes_packets_without_dropping_records(self):
        hashes = self.run["record_hashes"]
        captures = [{
            "name": "triage.json",
            "payload": {
                "classifications": [
                    {
                        "pmid": "900000003",
                        "gene": "WASP_TEST_GENE",
                        "concept_id": "test/stress",
                        "source_version": hashes["900000003"],
                        "gene_identity": "confirmed",
                        "concept_addressed": False,
                        "decision": "exclude",
                        "confidence": 0.92,
                    },
                    {
                        "pmid": "900000002",
                        "gene": "WASP_TEST_GENE",
                        "concept_id": "test/stress",
                        "source_version": hashes["900000002"],
                        "gene_identity": "confirmed",
                        "concept_addressed": True,
                        "decision": "include",
                        "confidence": 0.96,
                    },
                ]
            },
        }]
        summary = self.store.ingest_triage(captures, "offline-test", policy="never-hard-exclude")
        self.assertEqual(summary["triaged_pairs"], 2)
        self.assertEqual(summary["rerouted_exclusions"], 1)
        self.assertEqual(summary["effective_decisions"], {"include": 1, "needs_review": 1})

        jobs = self.store.jobs("offline-test", batch_size=1)
        stress_jobs = [load(j["path"]) for j in jobs["jobs"] if j["concept_id"] == "test/stress"]
        # Both PMIDs remain assigned; the triage-included PMID 900000002 is scheduled first.
        self.assertEqual([j["assigned_pmids"] for j in stress_jobs], [["900000002"], ["900000003"]])
        self.assertTrue(self.store.audit()["ok"])

        # Tampering with triage table is caught by audit.
        rows = self.store.table("triage")
        rows[0]["effective_decision"] = "include"
        self.store.save_table("triage", rows)
        self.assertFalse(self.store.audit()["ok"])

    def test_jobs_writes_portable_json_wave_plans_and_enriched_index(self):
        jobs = self.store.jobs("offline-test", batch_size=2, dispatch_size=1)
        self.assertEqual(len(jobs["wave_json_paths"]), len(jobs["wave_paths"]))
        plan = load(jobs["wave_json_paths"][0])
        self.assertEqual(plan["run_id"], "offline-test")
        self.assertEqual(plan["dispatch_size"], 1)
        self.assertEqual(len(plan["groups"]), 2)
        entry = jobs["jobs"][0]
        for key in ("job_id", "path", "gene", "concept_id", "assigned_count",
                    "packet_path", "expected_output_path", "rubric_path", "task"):
            self.assertIn(key, entry)

    def test_evidence_record_cli_accepts_stdin_and_imports(self):
        jobs = self.store.jobs("offline-test", batch_size=2)
        item = jobs["jobs"][0]
        job = load(item["path"])
        rows = [assessment(p) for p in job["assigned_pmids"]]
        summary = {"summary": {"concept": job["concept"]["name"], "gene": job["gene"]["symbol"],
                               "assigned": len(rows), "include": len(rows), "exclude": 0,
                               "needs_review": 0, "capped": job["capped"]}}
        raw_jsonl = "\n".join(json.dumps(r) for r in rows + [summary]) + "\n"
        res = self.cli("evidence-record", self.temp.name, "--job", item["path"],
                       "--stdin", "--runtime-run-id", "cross-harness-worker-1", stdin_text=raw_jsonl)
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["imported"], 2)
        self.assertTrue(Path(payload["output_path"]).is_file())
        self.assertTrue(self.store.audit()["ok"])

    def test_doctor_falls_back_to_canonical_agent_when_pi_dir_absent(self):
        with tempfile.TemporaryDirectory() as fake_home:
            env = dict(os.environ, HOME=fake_home)
            res = self.cli("doctor", env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(res.stdout)
            self.assertEqual(data["agent_mode"], "canonical_bundle")
            self.assertTrue(data["agent_exists"])
            self.assertTrue(data["agent_matches_canonical"])


if __name__ == "__main__":
    unittest.main()
