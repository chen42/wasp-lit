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
    DEFAULT_INSTRUCTIONS,
    DEFAULT_JEV_MODEL,
    DEFAULT_JEV_URL,
    JevCaptureError,
    JevClient,
    JevError,
    build_questions,
    build_state,
    load_instructions,
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
        art = record("900000001") | {"source_version": "sha-test", "publication_types": ["Journal Article", "Review"]}
        state = build_state(gene, concept, CONTEXT, art)
        self.assertEqual(state["gene"]["symbol"], "WASP_TEST_GENE")
        self.assertEqual(state["concept"]["id"], "test/stress")
        self.assertEqual(state["article"]["pmid"], "900000001")
        self.assertEqual(state["article"]["publication_types"], ["Journal Article", "Review"])
        self.assertEqual(state["scope"], {"evidence_species": CONTEXT["evidence_species"]})
        self.assertEqual(load_instructions(), DEFAULT_INSTRUCTIONS)
        questions = build_questions()
        self.assertEqual(list(questions.keys()),
                         ["gene_identity", "concept_addressed", "species_in_scope", "decision"])
        self.assertEqual(questions["gene_identity"]["type"], "choice")
        self.assertEqual(questions["concept_addressed"]["type"], "noul")

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

        out_of_scope = {
            "pmid": "900000001",
            "gene": "WASP_TEST_GENE",
            "concept_id": "test/stress",
            "source_version": "v1",
            "answers": {
                "gene_identity": {"choice": "confirmed"},
                "concept_addressed": {"noul": 0.95},
                "species_in_scope": {"choice": "no"},
                "decision": {"choice": "include", "probability": 0.61},
            },
        }
        self.assertEqual(normalize_triage_row(out_of_scope, policy="raw")["species_in_scope"], "no")
        self.assertEqual(normalize_triage_row(out_of_scope, policy="raw")["raw_decision"], "exclude")
        self.assertEqual(normalize_triage_row(out_of_scope, policy="raw")["effective_decision"], "exclude")
        self.assertEqual(normalize_triage_row(out_of_scope, policy="never-hard-exclude")["effective_decision"], "needs_review")

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

    def test_resolve_jev_config_uses_hardcoded_typesafe_systemone_url_and_reads_dotenv_key(self):
        with tempfile.TemporaryDirectory() as fake_home:
            env_file = Path(fake_home) / ".env"
            with patch.dict(os.environ, {"WASP_JEV_API_KEY": "", "TYPESAFE_API_KEY": ""}, clear=False):
                with self.assertRaises(JevError):
                    resolve_jev_config(env_path=env_file)
            env_file.write_text('TYPESAFE_API_KEY=dotenv-secret\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                for k in ("WASP_JEV_API_KEY", "TYPESAFE_API_KEY"):
                    os.environ.pop(k, None)
                cfg = resolve_jev_config(env_path=env_file)
                self.assertEqual(cfg["url"], DEFAULT_JEV_URL)
                self.assertEqual(cfg["api_key"], "dotenv-secret")
                self.assertEqual(cfg["model"], DEFAULT_JEV_MODEL)
                cfg_base = resolve_jev_config(explicit_url="https://api.typesafe.ai/v1/", env_path=env_file)
                self.assertEqual(cfg_base["url"], DEFAULT_JEV_URL)

    def test_classify_batch_runs_in_parallel_and_preserves_order(self):
        gene = CONTEXT["genes"][0]
        concept = {"id": "test/stress", "category": "test", "name": "stress", "terms": ["stress"]}
        tasks = [
            (gene, concept, CONTEXT, record(f"90000000{i}") | {"source_version": f"v{i}"})
            for i in range(1, 7)
        ]

        def opener(payload):
            pmid = payload["state"]["article"]["pmid"]
            return json.dumps({
                "answers": {
                    "gene_identity": {"type": "choice", "choice": "confirmed", "probabilities": {"confirmed": 0.99}, "confidence": 0.99},
                    "concept_addressed": {"type": "noul", "noul": 0.91 if int(pmid) % 2 == 0 else 0.12},
                    "species_in_scope": {"type": "choice", "choice": "yes", "probabilities": {"yes": 0.98}, "confidence": 0.98},
                    "decision": {"type": "choice", "choice": "include" if int(pmid) % 2 == 0 else "exclude",
                                 "probabilities": {"include": 0.9, "exclude": 0.1}, "confidence": 0.9},
                }
            })

        client = JevClient(DEFAULT_JEV_URL, "secret-token-123", opener=opener)
        results = client.classify_batch(tasks, max_workers=4)
        self.assertEqual([r["pmid"] for r in results], [f"90000000{i}" for i in range(1, 7)])
        normalized = [normalize_triage_row(r, policy="never-hard-exclude") for r in results]
        self.assertEqual([n["effective_decision"] for n in normalized],
                         ["needs_review", "include", "needs_review", "include", "needs_review", "include"])


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

    def test_audit_markdown_rejects_file_uris_md_tld_traps_and_backtick_concepts(self):
        notes_dir = Path(self.temp.name) / "references" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        synthesis_path = notes_dir / "synthesis.md"
        synthesis_path.write_text(
            "# Synthesis\n\n"
            "See [NCBI Gene summary](../gene-function/GENE-ncbi.json) and "
            "[selected concept domains](../selected-concept-domains.md) for CACNA1C "
            "in the nicotine and reward domains.\n",
            encoding="utf-8",
        )
        self.assertTrue(self.store.audit()["ok"], self.store.audit()["errors"])

        synthesis_path.write_text(
            "# Synthesis\n\n"
            "Bad [selected-concept-domains.md](file:///home/user/selected-concept-domains.md) "
            "and bare notes.md with `drug/nicotine` in prose.\n",
            encoding="utf-8",
        )
        audit_result = self.store.audit()
        self.assertFalse(audit_result["ok"])
        self.assertEqual(len(audit_result["errors"]), 4)

    def test_top_level_corpus_layout_and_separated_human_ai_decisions(self):
        self.assertEqual(self.store.base, self.store.root / "corpus")
        self.assertTrue((self.store.root / "README.md").is_file())
        self.assertTrue((self.store.root / "human-decisions.md").is_file())
        self.assertTrue((self.store.root / "ai-decisions.md").is_file())
        self.assertEqual(len(list(self.store.root.glob("*.json"))), 0)
        self.assertEqual(len(list(self.store.root.glob("*.jsonl"))), 0)

        ai_path = self.store.root / "ai-decisions.md"
        ai_text = ai_path.read_text(encoding="utf-8")
        ai_path.write_text(
            ai_text.replace(
                "<!-- AI-RATIONALE-START -->",
                "<!-- AI-RATIONALE-START -->\nCustom AI concept rationale for stress signaling.",
            ),
            encoding="utf-8",
        )
        res = self.cli(
            "human-decision",
            self.temp.name,
            "--stage",
            "screening_override",
            "--decision",
            "Approved manual review of PMID 900000003",
            "--rationale",
            "Confirmed genotype in full text",
            "--pmids",
            "900000003",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        human_md = (self.store.root / "human-decisions.md").read_text(encoding="utf-8")
        self.assertIn("Approved manual review of PMID 900000003", human_md)
        self.assertIn("screening_override", human_md)
        self.assertEqual(len(self.store.table("human_decisions")), 2)

        jobs = self.store.jobs("offline-test", batch_size=2)
        item = jobs["jobs"][0]
        job = load(item["path"])
        rows = [assessment(p) for p in job["assigned_pmids"]]
        summary = {"summary": {"concept": job["concept"]["name"], "gene": job["gene"]["symbol"],
                               "assigned": len(rows), "include": len(rows), "exclude": 0,
                               "needs_review": 0, "capped": job["capped"]}}
        raw_jsonl = "\n".join(json.dumps(r) for r in rows + [summary]) + "\n"
        self.store.record_assessments(item["path"], raw_jsonl, "worker-run-1")

        updated_ai_md = ai_path.read_text(encoding="utf-8")
        self.assertIn("Custom AI concept rationale for stress signaling.", updated_ai_md)
        self.assertIn("Included Records (2)", updated_ai_md)
        self.assertIn("900000003", updated_ai_md)
        self.assertTrue(self.store.audit()["ok"], self.store.audit()["errors"])

    def test_legacy_references_wasp_workspace_is_auto_detected(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            legacy_base = Path(legacy_dir) / "references" / "wasp"
            legacy_base.mkdir(parents=True, exist_ok=True)
            (legacy_base / "manifest.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
            legacy_store = Store(legacy_dir)
            self.assertEqual(legacy_store.base, legacy_base.resolve())


if __name__ == "__main__":
    unittest.main()
