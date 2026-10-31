#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["polite-http", "python-dotenv"]
# ///
"""wasp-lit coordinator. Offline commands require only Python's stdlib."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from gwas_catalog import (CaptureError, CatalogError, CatalogMCP, infer_tool, page_info,
                          resolve_endpoint, unwrap)
from jev_classifier import (DEFAULT_TRIAGE_WORKERS, JevClient, JevError, TRIAGE_POLICIES, resolve_jev_config)
from wasp_core import (WaspError, Store, VERSION, atomic, load, normalize_ontology,
                          now, progress, SKILL_ROOT)
from pubmed_extension import PubmedBackend


def default_pubmed_wrapper():
    """Locate the sibling pubmed_database wrapper across common skill directories."""
    candidates = [
        SKILL_ROOT.parent / "pubmed_database" / "scripts" / "pubmed_api.py",
        Path.home() / ".agents" / "skills" / "pubmed_database" / "scripts" / "pubmed_api.py",
        Path.home() / ".pi" / "agent" / "skills" / "pubmed_database" / "scripts" / "pubmed_api.py",
        Path.home() / ".claude" / "skills" / "pubmed_database" / "scripts" / "pubmed_api.py",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return str(candidates[1])


class FixtureBackend:
    """Explicit synthetic fixtures, never a fallback for failed live retrieval."""

    def __init__(self, path):
        self.data = load(path)
        if self.data.get("synthetic") is not True:
            raise WaspError("Fixture must be explicitly labeled synthetic")
        self.records = {r["pmid"]: r for r in self.data["records"]}

    def search(self, query, max_results=9999):
        if query not in self.data["searches"]:
            raise WaspError("No fixture for this exact query")
        ids = self.data["searches"][query]
        return {"count": len(ids), "pmids": ids[:max_results], "query_translation": query,
                "warnings": {}, "sort": "pub_date", "synthetic": True}

    def fetch(self, pmids):
        return {"records": [self.records[i] for i in pmids if i in self.records], "synthetic": True}

    def order_ids(self, pmids):
        order = self.data.get("publication_date_order", list(self.records))
        return {"count": len(pmids), "pmids": [p for p in order if p in pmids], "synthetic": True}

    def links(self, pmid):
        pmcids = ["TEST" + pmid] if pmid in self.data.get("fulltexts", {}) else []
        return {"pmid": str(pmid), "pubmed_pmcids": pmcids, "candidate_pmcids": pmcids,
                "europepmc": {"status": "not found"}}

    def fulltext(self, pmid, links):
        document = self.data["fulltexts"][pmid]
        if isinstance(document, dict) and document.get("status") in ("unavailable", "failed"):
            return document
        return {"status": "retrieved", "provider": "synthetic fixture", "pmid": str(pmid),
                "candidate_pmcids": list(links.get("candidate_pmcids") or []),
                "attempts": [{"provider": "synthetic fixture", "status": "retrieved"}],
                "document": document}


def notification(store):
    path = store.root / ".licenses" / "pubmed_database_LICENSE.txt"
    if not path.exists():
        raise WaspError("Notify the user of https://pubmed.ncbi.nlm.nih.gov/disclaimer/ and "
                           "https://www.ncbi.nlm.nih.gov/home/about/policies/ and paper-specific licenses, "
                           "then run acknowledge-license to record that notification")


def gwas_catalog_notification(store):
    path = store.root / ".licenses" / "gwas_catalog_LICENSE.txt"
    if not path.exists():
        raise WaspError("Notify the user of the GWAS Catalog terms of use at "
                           "https://www.ebi.ac.uk/gwas/docs/about and to cite the Catalog and the source "
                           "study, then run acknowledge-license --source gwas_catalog")


def gwas_client(args, store):
    """Build the live GWAS Catalog MCP client for this workspace."""
    try:
        url = resolve_endpoint(project_root=store.root, explicit=getattr(args, "endpoint", None),
                               default_fallback=not getattr(args, "strict_mcp_config", False))
    except CatalogError as error:
        raise WaspError(str(error)) from None
    return CatalogMCP(url, timeout=args.timeout)


def capture_envelope(payload, expected, name):
    """Validate a saved MCP response for one tool and return its envelope."""
    try:
        declared, envelope = unwrap(payload)
        tool = infer_tool(envelope, declared)
        page_info(envelope)
    except CaptureError as error:
        raise WaspError("Capture " + name + ": " + str(error)) from None
    if tool != expected:
        raise WaspError("Capture " + name + " is not a " + expected + " result")
    return envelope


def backend(args, store):
    if args.fixture:
        if load(store.base / "context.json").get("synthetic") is not True:
            raise WaspError("Fixture collection is allowed only in a synthetic test workspace")
        return FixtureBackend(args.fixture)
    context = load(store.base / "context.json")
    if context.get("synthetic") or context.get("_template"):
        raise WaspError("Synthetic and unfilled template workspaces cannot run live retrieval")
    notification(store)
    api = PubmedBackend(args.pubmed_wrapper)
    # Only names are reported. Never print values or include them in corpus files.
    missing = [key for key in ("NCBI_API_KEY", "USER_EMAIL") if not os.environ.get(key)]
    if missing:
        raise WaspError("Safe credential setup required in ~/.env for: " + ", ".join(missing)
                           + "; add locally using hidden terminal input, never in chat")
    return api


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--version", action="version", version=VERSION)
    commands = result.add_subparsers(dest="command", required=True)
    command = commands.add_parser("normalize-ontology", help="Convert the original literal without eval")
    command.add_argument("source")
    command.add_argument("output")
    command = commands.add_parser("doctor", help="Offline dependency and agent checks")
    command.add_argument("--pubmed-wrapper", default=default_pubmed_wrapper())
    command.add_argument("--agent-path", default=None,
                         help="Optional installed agent copy path (defaults to ~/.pi/agent/agents/concept-screener.md when present, otherwise canonical)")
    for name in ("init", "plan-search", "collect", "jobs", "evidence-validate", "evidence-import",
                 "evidence-record", "triage", "triage-report", "human-decision", "packet", "fulltext", "audit",
                 "status", "acknowledge-license", "phenotype-search", "associations", "association-report"):
        command = commands.add_parser(name)
        command.add_argument("workspace")
        if name == "init":
            command.add_argument("--context", required=True)
            command.add_argument("--ontology", default=str(SKILL_ROOT / "resources/addiction_ontology.json"))
        if name in ("collect", "fulltext"):
            command.add_argument("--run-id", required=name == "fulltext")
            command.add_argument("--fixture")
            command.add_argument("--pubmed-wrapper", default=default_pubmed_wrapper())
        if name == "phenotype-search":
            command.add_argument("--query", help="Trait name to search")
            command.add_argument("--efo-id", help="Ontology shortform to look up")
            command.add_argument("--capture", help="Saved gwascatalog_get_traits MCP response instead of a live call")
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--size", type=int, default=25)
            command.add_argument("--endpoint", help="Override the gwas-mcp URL")
            command.add_argument("--strict-mcp-config", action="store_true",
                                 help="Require an explicit mcp.json or env entry without falling back to the public EBI endpoint")
            command.add_argument("--timeout", type=int, default=60)
            command.add_argument("--output")
        if name == "associations":
            command.add_argument("--run-id", required=True)
            command.add_argument("--phenotype", action="append", required=True, help="EFO, MONDO or other ontology ID")
            command.add_argument("--capture", action="append",
                                 help="Saved gwascatalog_get_associations MCP response; repeat per page, "
                                      "and omit to page live over MCP")
            command.add_argument("--cross-species-transfer", action="store_true")
            command.add_argument("--endpoint", help="Override the gwas-mcp URL")
            command.add_argument("--strict-mcp-config", action="store_true",
                                 help="Require an explicit mcp.json or env entry without falling back to the public EBI endpoint")
            command.add_argument("--timeout", type=int, default=60)
            command.add_argument("--page-size", type=int, default=50,
                                 help="Rows per MCP page; the server maximum is 50")
            command.add_argument("--max-pages", type=int, default=50)
            command.add_argument("--output")
        if name == "association-report":
            command.add_argument("--run-id")
            command.add_argument("--phenotype")
            command.add_argument("--output")
        if name == "acknowledge-license":
            command.add_argument("--source", choices=("pubmed", "gwas_catalog"), default="pubmed")
        if name == "collect":
            command.add_argument("--refresh", action="store_true")
            command.add_argument("--batch-size", type=int, default=200)
            command.add_argument("--search-workers", type=int, default=4,
                                 help="Concurrent ESearch workers (1-8, default: 4; rate-limited by polite-http)")
        if name == "jobs":
            command.add_argument("--run-id", required=True)
            command.add_argument("--batch-size", type=int, default=20)
            command.add_argument("--max-bytes", type=int, default=40000)
            command.add_argument("--wave-size", type=int, default=64)
            command.add_argument("--dispatch-size", type=int, default=6, help="Workers per awaited dispatch group")
            command.add_argument("--model", help="Explicit provider/model for each screening worker; omit to use the "
                                                  "configured subagent default")
        if name in ("evidence-validate", "evidence-import"):
            command.add_argument("--job", required=True)
            command.add_argument("--response", required=True)
        if name == "evidence-import":
            command.add_argument("--runtime-run-id", required=True)
        if name == "evidence-record":
            command.add_argument("--job", required=True)
            command.add_argument("--response", help="File containing worker JSONL response lines")
            command.add_argument("--stdin", action="store_true", help="Read worker JSONL response lines from stdin")
            command.add_argument("--runtime-run-id", help="Optional runtime run ID to import immediately after validation")
        if name == "triage":
            command.add_argument("--run-id", required=True)
            command.add_argument("--capture", action="append",
                                 help="Saved Jev classification capture file; omit to classify live via HTTP")
            command.add_argument("--policy", choices=TRIAGE_POLICIES, default="never-hard-exclude",
                                 help="Triage policy (default: never-hard-exclude, which reroutes exclusions to needs_review)")
            command.add_argument("--endpoint", help="Override the Jev classification API URL (default: https://api.typesafe.ai/v1/systemone)")
            command.add_argument("--model", help="Override the Jev model identifier (default: typesafe/jev-latest)")
            command.add_argument("--workers", type=int, default=DEFAULT_TRIAGE_WORKERS,
                                 help="Concurrent Jev classification workers (1-16, default: 8)")
            command.add_argument("--timeout", type=int, default=60)
            command.add_argument("--output")
        if name == "triage-report":
            command.add_argument("--run-id")
            command.add_argument("--output")
        if name == "human-decision":
            command.add_argument("--stage", required=True, help="Workflow stage (e.g., scope_approval, concept_prioritization, screening_override)")
            command.add_argument("--decision", required=True, help="Summary of the human decision or approval")
            command.add_argument("--rationale", help="Optional rationale or notes provided by the human user")
            command.add_argument("--pmids", help="Optional comma-separated PMIDs affected by this decision")
        if name == "packet":
            command.add_argument("--pmids", help="Comma-separated, verified PMIDs")
            command.add_argument("--gene")
            command.add_argument("--concept-id")
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--output", required=True)
        if name == "fulltext":
            command.add_argument("--max-attempts", type=int, help="Optional explicit attempt bound, not a default")
            command.add_argument("--pmids", help="Comma-separated PMIDs to retrieve in the given order; bypasses the default priority selection")
            command.add_argument("--target", type=int, help="Stop after this many successful retrievals from --pmids (default: all listed PMIDs)")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "normalize-ontology":
        if Path(args.output).exists():
            raise WaspError("Refusing to overwrite an existing ontology")
        ontology = normalize_ontology(args.source)
        atomic(args.output, ontology)
        return {"concepts": len(ontology["concepts"]), "output": str(Path(args.output).resolve())}
    if args.command == "doctor":
        original = SKILL_ROOT / "agents/concept-screener.md"
        pi_default = Path.home() / ".pi/agent/agents/concept-screener.md"
        if args.agent_path is not None:
            installed = Path(args.agent_path).expanduser()
            mode = "explicit_agent_path"
        elif pi_default.exists():
            installed = pi_default
            mode = "pi_installed"
        else:
            installed = original
            mode = "canonical_bundle"
        return {"python": sys.version.split()[0], "uv": shutil.which("uv"),
                "pubmed_wrapper": str(Path(args.pubmed_wrapper).expanduser()),
                "pubmed_wrapper_exists": Path(args.pubmed_wrapper).expanduser().is_file(),
                "canonical_agent": str(original),
                "canonical_agent_exists": original.is_file(),
                "agent_mode": mode,
                "agent_exists": installed.is_file(),
                "agent_matches_canonical": installed.is_file() and installed.read_bytes() == original.read_bytes(),
                "note": "No network calls or model launches; use the host harness subagent tools for runtime execution"}
    store = Store(args.workspace)
    with store.lock():
        if args.command == "init":
            context = load(args.context)
            if context.get("_template"):
                raise WaspError("Fill the context template and remove _template before initialization")
            store.init(context, args.ontology)
            return {"workspace": str(store.root), "status": "initialized"}
        store.require()
        if args.command == "acknowledge-license":
            if args.source == "gwas_catalog":
                path = store.root / ".licenses/gwas_catalog_LICENSE.txt"
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"User notified at {now()} to check GWAS Catalog terms of use at "
                                    "https://www.ebi.ac.uk/gwas/docs/about and to cite the Catalog and the "
                                    "source study.\n", encoding="utf-8")
                return {"notification_record": str(path), "source": args.source}
            path = store.root / ".licenses/pubmed_database_LICENSE.txt"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"User notified at {now()} to check PubMed terms at "
                                "https://pubmed.ncbi.nlm.nih.gov/disclaimer/ and NCBI policies at "
                                "https://www.ncbi.nlm.nih.gov/home/about/policies/ and each paper's license.\n",
                                encoding="utf-8")
            return {"notification_record": str(path), "source": args.source}
        if args.command == "phenotype-search":
            if args.capture:
                payload = load(args.capture)
                envelope = capture_envelope(payload, "gwascatalog_get_traits", Path(args.capture).name)
                provenance = {"capture_file": Path(args.capture).name}
            elif args.query or args.efo_id:
                gwas_catalog_notification(store)
                client = gwas_client(args, store)
                envelope = client.traits(efo_trait=args.query, efo_id=args.efo_id, size=args.size)
                payload, provenance = envelope, {"endpoint": client.url}
            else:
                raise WaspError("Pass --query, --efo-id or --capture")
            ref = store.source("gwas-traits", "gwas_catalog_traits", payload,
                               {"tool": "gwascatalog_get_traits"} | provenance)
            traits = [{"efo_id": row.get("efo_id"), "efo_trait": row.get("efo_trait")}
                      for row in envelope.get("data") or []]
            labels = store.save_trait_labels({row["efo_id"]: row["efo_trait"] for row in traits if row.get("efo_id")})
            value = {"traits": traits[:args.limit], "count": len(traits), "pagination": page_info(envelope),
                     "query": envelope.get("query"), "source": ref, "trait_labels": len(labels),
                     "note": "Confirm the returned trait name, then pass its ontology ID to associations."}
            if args.output:
                if Path(args.output).exists():
                    raise WaspError("Choose a new phenotype search output path")
                atomic(args.output, value)
            return value
        if args.command == "associations":
            if args.capture:
                values = [{"name": Path(path).name, "payload": load(path)} for path in args.capture]
            else:
                gwas_catalog_notification(store)
                client = gwas_client(args, store)
                values = []
                for gene in load(store.base / "context.json")["genes"]:
                    for phenotype_id in args.phenotype:
                        pages = client.associations(phenotype_id, gene["symbol"], size=args.page_size,
                                                    max_pages=args.max_pages)
                        for page, envelope in enumerate(pages):
                            values.append({"name": f"{gene['symbol']}/{phenotype_id}/page-{page}",
                                           "payload": envelope})
            result = store.ingest_associations(values, args.run_id, args.phenotype,
                                              cross_species_transfer=args.cross_species_transfer)
            if args.output:
                if Path(args.output).exists():
                    raise WaspError("Choose a new associations output path")
                atomic(args.output, result)
                return {"output": str(Path(args.output).resolve()), "pairs": result["pairs"],
                        "evidence_records": result["evidence_records"], "state": result["state"]}
            return result
        if args.command == "association-report":
            value = store.association_report(args.run_id, args.phenotype)
            if args.output:
                if Path(args.output).exists():
                    raise WaspError("Choose a new association report output path")
                atomic(args.output, value)
                return {"output": str(Path(args.output).resolve()), "pairs": value["pair_count"],
                        "evidence_records": value["evidence_records"], "warnings": value["warnings"]}
            return value
        if args.command == "plan-search":
            return {"queries": str(store.base / "queries.json"), "query_count": len(load(store.base / "queries.json"))}
        if args.command == "collect":
            run = store.collect(backend(args, store), args.run_id, args.refresh, args.batch_size, args.search_workers)
            return {"run_id": run["run_id"], "status": run["status"], "retrieved_records": len(run.get("record_hashes", run.get("versions", {}))),
                    "missing_records": run["missing_records"], "run_path": str(store.base / "runs" / (run["run_id"] + ".json"))}
        if args.command == "jobs":
            result = store.jobs(args.run_id, args.batch_size, args.max_bytes, args.wave_size, args.dispatch_size,
                                args.model)
            return {"job_count": result["job_count"], "dispatch_size": result["dispatch_size"],
                    "model": result["model"], "wave_paths": result["wave_paths"],
                    "wave_json_paths": result["wave_json_paths"],
                    "jobs_index": str(store.base / "jobs-index.json"), "launched": False}
        if args.command == "evidence-validate":
            job, rows = store.validate_assessments(args.job, args.response)
            return {"valid": True, "job_id": job["job_id"], "records": len(rows)}
        if args.command == "evidence-import":
            return store.import_evidence(args.job, args.response, args.runtime_run_id)
        if args.command == "evidence-record":
            if bool(args.response) == bool(args.stdin):
                raise WaspError("Pass either --response <path> or --stdin")
            raw_text = sys.stdin.read() if args.stdin else Path(args.response).read_text(encoding="utf-8")
            return store.record_assessments(args.job, raw_text, args.runtime_run_id)
        if args.command == "triage":
            if args.capture:
                captures = [{"name": Path(path).name, "payload": load(path)} for path in args.capture]
            else:
                try:
                    cfg = resolve_jev_config(explicit_url=args.endpoint, model=args.model)
                except JevError as error:
                    raise WaspError(str(error)) from None
                client = JevClient(cfg["url"], cfg["api_key"], model=cfg["model"], timeout=args.timeout)
                run_data = load(store.base / "runs" / (args.run_id + ".json"))
                context_data = load(store.base / "context.json")
                record_hashes = run_data.get("record_hashes", run_data.get("versions", {}))
                tasks = []
                seen_pairs = set()
                for search in run_data["searches"].values():
                    gene = next(g for g in context_data["genes"] if g["symbol"] == search["gene"])
                    for pmid in search["selected_pmids"]:
                        pair_key = (gene["symbol"], search["concept"]["id"], pmid)
                        if pair_key in seen_pairs:
                            continue
                        version = record_hashes.get(pmid)
                        if not version:
                            continue
                        article = store.article(pmid, version)
                        if not article.get("abstract") or not article["abstract"].strip():
                            continue
                        seen_pairs.add(pair_key)
                        tasks.append((gene, search["concept"], context_data, article | {"source_version": version}))
                progress(f"Jev triage started; run={args.run_id}; pairs={len(tasks)}; workers={args.workers}; endpoint={cfg['url']}")
                try:
                    rows = client.classify_batch(tasks, max_workers=args.workers, progress_fn=progress)
                except JevError as error:
                    raise WaspError(str(error)) from None
                captures = [{"name": f"live-jev-{args.run_id}.json", "payload": {"classifications": rows}}]
            result = store.ingest_triage(captures, args.run_id, policy=args.policy)
            if args.output:
                if Path(args.output).exists():
                    raise WaspError("Choose a new triage output path")
                atomic(args.output, result)
            return result
        if args.command == "triage-report":
            value = store.triage_report(args.run_id)
            if args.output:
                if Path(args.output).exists():
                    raise WaspError("Choose a new triage report output path")
                atomic(args.output, value)
            return value
        if args.command == "human-decision":
            pmids = args.pmids.split(",") if args.pmids else []
            entry = store.log_human_decision(args.stage, args.decision, args.rationale, pmids)
            return {"decision_id": entry["decision_id"], "stage": entry["stage"],
                    "human_decisions_md": str(store.root / "human-decisions.md")}
        if args.command == "packet":
            if Path(args.output).exists():
                raise WaspError("Choose a new packet output path")
            value = store.packet(args.pmids.split(",") if args.pmids else None, args.gene, args.concept_id, args.limit)
            atomic(args.output, value)
            return {"output": str(Path(args.output).resolve()), "records": len(value["records"])}
        if args.command == "fulltext":
            state = store.fulltext(backend(args, store), args.run_id, args.max_attempts,
                                   args.pmids.split(",") if args.pmids else None, args.target)
            return {key: state[key] for key in ("quota", "retrieved", "attempts_this_call", "target_met",
                    "candidate_pool_exhausted", "blocked", "selection_mode")} | {
                    "run_path": str(store.base / "runs" / (args.run_id + ".json"))}
        if args.command == "audit":
            value = store.audit()
            atomic(store.base / "audit.json", value)
            print(json.dumps({"ok": value["ok"], "errors": value["errors"], "audit": str(store.base / "audit.json")}, indent=2))
            return None if value["ok"] else 1
        if args.command == "status":
            value = store.overview()
            return {key: value[key] for key in ("article_count", "available_abstracts", "missing_abstracts",
                    "unique_discovered_pmids", "assessment_records", "fulltext_count", "association_pairs",
                    "association_evidence_records")} | {
                    "runs": [{"run_id": r["run_id"], "status": r["status"], "strata": len(r["strata"])} for r in value["runs"]],
                    "association_runs": value["association_runs"],
                    "overview": str(store.base / "overview.json")}
    raise WaspError("Unknown command")


if __name__ == "__main__":
    try:
        result = main()
        if isinstance(result, int):
            sys.exit(result)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (WaspError, OSError, ValueError, KeyError, TypeError) as error:
        print("wasp-lit: " + str(error), file=sys.stderr)
        sys.exit(2)
