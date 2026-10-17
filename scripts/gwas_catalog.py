"""GWAS Catalog MCP client and capture handling for the wasp-lit association lane.

The GWAS Catalog is reached through the configured `gwas-mcp` Model Context
Protocol server. This module speaks the MCP JSON-RPC transport directly so the
coordinator can page results, retry, and persist every response verbatim without
routing large payloads through a model turn. The native `mcp__gwas_mcp__*` tools
remain available for interactive questions.

Recognized tools:

- `gwascatalog_get_traits`: resolve a trait name to an ontology ID.
- `gwascatalog_get_associations`: variant-trait associations for a gene, trait,
  study accession, or rsID.
- `gwascatalog_get_studies`: study-level metadata such as sample size and
  ancestry.

Every envelope carries a `query`, a `data` list and a `pagination` object with
`page`, `total_pages`, `total_results`, `truncated` and `has_next_page`. Offline
callers may supply a saved envelope instead of a live call; nothing in the
validation and normalization code opens a connection.
"""

import json
import os
from pathlib import Path
import re
import time
import urllib.request

PHENOTYPE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[0-9]+$")
TOOLS = ("gwascatalog_get_traits", "gwascatalog_get_associations", "gwascatalog_get_studies")
DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 2
# The server rejects size above this with a validation error.
MAX_PAGE_SIZE = 50

# Evidence fields copied verbatim from an association row. Everything else stays
# in the immutable source snapshot.
_ASSOCIATION_FIELDS = ("association_id", "accession_id", "pubmed_id", "first_author", "p_value",
                       "pvalue_description", "pvalue_mantissa", "pvalue_exponent", "beta", "or_value",
                       "range", "risk_frequency", "efo_traits", "reported_trait", "mapped_genes",
                       "locations", "snp_effect_allele")


class CatalogError(RuntimeError):
    """The MCP server could not be reached or returned an error."""


class CaptureError(ValueError):
    """A saved MCP response is missing or malformed."""


def valid_phenotype_id(value):
    """True for EFO-, MONDO- or OBA-style ontology shortforms."""
    return isinstance(value, str) and bool(PHENOTYPE_ID.fullmatch(value))


def resolve_endpoint(project_root=None, explicit=None):
    """Resolve the GWAS Catalog MCP URL from the environment or mcp.json."""
    if explicit:
        return explicit
    if os.environ.get("WASP_GWAS_MCP_URL"):
        return os.environ["WASP_GWAS_MCP_URL"]
    candidates = []
    if project_root is not None:
        candidates.append(Path(project_root) / ".pi" / "mcp.json")
    candidates.append(Path.home() / ".pi" / "agent" / "mcp.json")
    for path in candidates:
        try:
            servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, ValueError):
            continue
        for name, entry in servers.items():
            if name.replace("-", "_") == "gwas_mcp" and isinstance(entry, dict) and entry.get("url"):
                return entry["url"]
    raise CatalogError("No GWAS Catalog MCP server configured. Add a gwas-mcp entry with a url to "
                       "mcp.json, set WASP_GWAS_MCP_URL, or pass --endpoint")


class CatalogMCP:
    """Minimal MCP JSON-RPC client for the GWAS Catalog server.

    `opener` may be supplied for tests; it receives the request payload and
    returns the raw response body.
    """

    def __init__(self, url, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, opener=None):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self._opener = opener
        self._request_id = 0
        self._initialized = False

    @staticmethod
    def parse(raw):
        """Return the JSON-RPC message from an SSE or plain JSON body."""
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(raw)

    def _post(self, payload):
        if self._opener is not None:
            return self._opener(payload)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "wasp-lit-gwas-catalog/1.0 (polite MCP client)"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def _rpc(self, method, params):
        self._request_id += 1
        message = self.parse(self._post({"jsonrpc": "2.0", "id": self._request_id,
                                         "method": method, "params": params}))
        if not isinstance(message, dict):
            raise CatalogError("GWAS Catalog MCP returned a non-object message")
        if "error" in message:
            error = message["error"]
            raise CatalogError("GWAS Catalog MCP error: "
                               + str(error.get("message") if isinstance(error, dict) else error))
        return message["result"]

    def _with_retry(self, label, action):
        failure = None
        for attempt in range(self.retries + 1):
            try:
                return action()
            except (OSError, ValueError, KeyError, CatalogError) as error:
                failure = error
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
        raise CatalogError(label + " failed: " + str(failure))

    def initialize(self):
        if self._initialized:
            return
        self._with_retry("GWAS Catalog MCP initialize", lambda: self._rpc(
            "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "wasp-lit", "version": "1.0"}}))
        self._initialized = True

    def call(self, tool, arguments):
        """Call one tool and return its envelope with the tool name attached.

        Transport and JSON-RPC failures are retried. A tool-level error is
        raised immediately with the server message, because it is deterministic.
        """
        if tool not in TOOLS:
            raise CatalogError("Unknown GWAS Catalog tool: " + str(tool))
        self.initialize()
        result = self._with_retry("GWAS Catalog MCP call for " + tool,
                                  lambda: self._rpc("tools/call", {"name": tool, "arguments": arguments}))
        payload = {"tool": tool}
        structured = result.get("structuredContent") if isinstance(result, dict) else None
        if isinstance(structured, dict):
            payload.update(structured)
        elif isinstance(result, dict) and result.get("content"):
            text = result["content"][0].get("text")
            if not isinstance(text, str):
                raise CatalogError("GWAS Catalog MCP returned non-text content for " + tool)
            try:
                payload.update(json.loads(text))
            except json.JSONDecodeError:
                raise CatalogError(tool + ": " + text.strip()) from None
        else:
            raise CatalogError("GWAS Catalog MCP returned no content for " + tool)
        if isinstance(result, dict) and result.get("isError"):
            raise CatalogError(tool + ": " + str(payload.get("message") or payload.get("content") or "tool error"))
        return payload

    def traits(self, efo_trait=None, efo_id=None, size=25):
        arguments = {"size": min(size, MAX_PAGE_SIZE), "page": 0}
        if efo_id:
            arguments["efo_id"] = efo_id
        if efo_trait:
            arguments["efo_trait"] = efo_trait
        return self.call("gwascatalog_get_traits", arguments)

    def associations(self, efo_id, mapped_gene, size=MAX_PAGE_SIZE, max_pages=50):
        """Page one gene-by-trait query until the server reports no next page.

        The page size is clamped to the server maximum and the page cap is a
        safety bound. Hitting the cap leaves the group incomplete rather than
        silently truncating, because the missing pages are recorded.
        """
        pages = []
        for page in range(max_pages):
            envelope = self.call("gwascatalog_get_associations",
                                 {"efo_id": efo_id, "mapped_gene": mapped_gene,
                                  "size": min(size, MAX_PAGE_SIZE), "page": page})
            pages.append(envelope)
            if not page_info(envelope)["has_next_page"]:
                break
        return pages

    def studies(self, accession_id=None, efo_id=None, mapped_gene=None, size=MAX_PAGE_SIZE, max_pages=50):
        pages = []
        arguments = {"size": min(size, MAX_PAGE_SIZE)}
        for key, value in (("accession_id", accession_id), ("efo_id", efo_id), ("mapped_gene", mapped_gene)):
            if value:
                arguments[key] = value
        for page in range(max_pages):
            envelope = self.call("gwascatalog_get_studies", arguments | {"page": page})
            pages.append(envelope)
            if not page_info(envelope)["has_next_page"]:
                break
        return pages


def unwrap(payload):
    """Return (tool, envelope) from a saved MCP tool result or a bare envelope."""
    if not isinstance(payload, dict):
        raise CaptureError("Capture is not a JSON object")
    tool = payload.get("tool")
    for key in ("structuredContent", "structured_content"):
        if isinstance(payload.get(key), dict):
            return tool, payload[key]
    content = payload.get("content")
    if isinstance(content, list) and content:
        block = content[0]
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str):
            try:
                return tool, json.loads(text)
            except json.JSONDecodeError as error:
                raise CaptureError("Capture content is not JSON: " + str(error)) from None
    if "data" in payload and "pagination" in payload:
        return tool, payload
    raise CaptureError("Unrecognized MCP capture shape; expected a tool result or an envelope "
                       "with data and pagination")


def _rows(envelope):
    rows = envelope.get("data")
    if not isinstance(rows, list):
        raise CaptureError("Capture data is not a list")
    return rows


def infer_tool(envelope, declared=None):
    """Identify the MCP tool from a declared name or the shape of the rows."""
    if declared in TOOLS:
        return declared
    if declared is not None:
        raise CaptureError("Unknown GWAS Catalog tool name: " + repr(declared))
    rows = _rows(envelope)
    keys = {key for row in rows for key in row} if rows else set()
    if "association_id" in keys:
        return "gwascatalog_get_associations"
    if "accession_id" in keys and keys & {"disease_trait", "initial_sample_size", "snp_count", "ancestries"}:
        return "gwascatalog_get_studies"
    if keys and keys <= {"efo_id", "efo_trait"}:
        return "gwascatalog_get_traits"
    raise CaptureError("Cannot identify the GWAS Catalog tool for this capture; add a 'tool' field")


def page_info(envelope):
    """Validate and return the pagination block."""
    page = envelope.get("pagination")
    if not isinstance(page, dict):
        raise CaptureError("Capture has no pagination metadata")
    for key in ("page", "total_pages", "total_results"):
        if not isinstance(page.get(key), int) or isinstance(page.get(key), bool) or page[key] < 0:
            raise CaptureError("Capture pagination lacks an integer " + key)
    return {"page": page["page"], "size": page.get("size"), "total_pages": page["total_pages"],
            "total_results": page["total_results"], "truncated": bool(page.get("truncated")),
            "has_next_page": bool(page.get("has_next_page"))}


def normalize_association(row):
    """Return the verbatim evidence fields of one association row."""
    if not isinstance(row.get("association_id"), int) or isinstance(row.get("association_id"), bool):
        raise CaptureError("Association row has no integer association_id")
    value = {key: row.get(key) for key in _ASSOCIATION_FIELDS}
    value["pubmed_id"] = str(row["pubmed_id"]) if row.get("pubmed_id") is not None else None
    value["efo_traits"] = [{"efo_id": t.get("efo_id"), "efo_trait": t.get("efo_trait")}
                           for t in row.get("efo_traits") or []]
    for key in ("reported_trait", "mapped_genes", "locations", "snp_effect_allele"):
        value[key] = [str(item) for item in row.get(key) or []]
    return value


def assess_group(envelopes):
    """Assess page completeness for one gene x trait capture group.

    Returns completeness, the concatenated rows and the reasons a group is
    incomplete. A group is complete only when the returned pages are exactly the
    reported range, no page is truncated, the last page reports no next page, the
    row count equals the reported total, and no association_id repeats. An empty
    result set (`total_pages` 0) is complete with a single empty page.
    """
    infos = [(page_info(envelope), _rows(envelope)) for envelope in envelopes]
    reasons = []
    totals_pages = {info[0]["total_pages"] for info in infos}
    totals_results = {info[0]["total_results"] for info in infos}
    if len(totals_pages) != 1 or len(totals_results) != 1:
        return {"complete": False, "row_count": sum(len(rows) for _, rows in infos),
                "total_results": None, "total_pages": None, "pages_returned": [],
                "missing_pages": [], "has_next_page": None,
                "incomplete_reasons": ["inconsistent total_pages or total_results across captures"],
                "rows": [row for _, rows in infos for row in rows]}
    total_pages = totals_pages.pop()
    total_results = totals_results.pop()
    present = [info[0]["page"] for info in infos]
    expected = list(range(total_pages)) if total_pages else [0]
    missing = [page for page in expected if page not in present]
    extra = sorted({page for page in present if page not in expected})
    if missing:
        reasons.append("missing pages: " + ", ".join(str(page) for page in missing))
    if extra:
        reasons.append("unexpected pages: " + ", ".join(str(page) for page in extra))
    if len(set(present)) != len(present):
        reasons.append("duplicate page captures")
    if any(info[0]["truncated"] for info in infos):
        reasons.append("a page was truncated by the server")
    rows = [row for _, page_rows in infos for row in page_rows]
    if len(rows) != total_results:
        reasons.append(f"row count {len(rows)} does not match total_results {total_results}")
    last = [info[0] for info in infos if info[0]["page"] == expected[-1]]
    if last and last[0]["has_next_page"]:
        reasons.append("the last page reports another page")
    seen, duplicates = set(), []
    for row in rows:
        key = row.get("association_id")
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        reasons.append("duplicate association_id values: " + ", ".join(str(key) for key in duplicates))
    return {"complete": not reasons, "row_count": len(rows), "total_results": total_results,
            "total_pages": total_pages, "pages_returned": sorted(present), "missing_pages": missing,
            "has_next_page": last[0]["has_next_page"] if last else None,
            "incomplete_reasons": reasons, "rows": rows}
