#!/usr/bin/env python3
"""Retrieve WikiGenes gene pages for human, mouse, and rat records.

WikiGenes does not document a public gene-record REST API. This script uses its
public HTML search page and gene article pages, with a low request rate and a
local response cache. It does not infer orthology: results are returned only
when WikiGenes search lists the requested symbol and one of the selected taxa.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://www.wikigenes.org"
SPECIES = {
    "human": "Homo sapiens",
    "mouse": "Mus musculus",
    "rat": "Rattus norvegicus",
}
FUNCTION_HEADING = re.compile(
    r"\b(function|biological context|molecular|cellular role|regulat|pathway|interaction|mechanis)\b",
    re.IGNORECASE,
)


class SearchResultsParser(HTMLParser):
    """Extract gene rows from WikiGenes' HTML search results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self.row: dict[str, object] | None = None
        self.stack: list[tuple[str, set[str]]] = []
        self.row_depth: int | None = None
        self.anchor: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        classes = set((attrs_d.get("class") or "").split())
        if tag == "div" and "queryResult" in classes and self.row is None:
            self.row = {"anchors": [], "species": ""}
            self.row_depth = len(self.stack) + 1
        if self.row is not None:
            self.stack.append((tag, classes))
            if tag == "a" and any("queryResultLeft" in cs for _, cs in self.stack):
                self.anchor = {"href": attrs_d.get("href") or "", "text": ""}

    def handle_endtag(self, tag: str) -> None:
        if self.row is None:
            return
        if tag == "a" and self.anchor is not None:
            anchors = self.row["anchors"]
            assert isinstance(anchors, list)
            anchors.append(self.anchor)
            self.anchor = None
        closing_classes: set[str] = set()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                closing_classes = self.stack[i][1]
                del self.stack[i:]
                break
        if tag == "div" and self.row_depth == len(self.stack) + 1 and "queryResult" in closing_classes:
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self.row is None:
            return
        if self.anchor is not None:
            self.anchor["text"] = str(self.anchor["text"]) + data
        if any("queryResultRight" in classes for _, classes in self.stack):
            self.row["species"] = str(self.row["species"]) + data

    def _finish_row(self) -> None:
        assert self.row is not None
        anchors = self.row["anchors"]
        assert isinstance(anchors, list)
        gene_anchors = [a for a in anchors if isinstance(a, dict) and "/e/gene/e/" in str(a.get("href", ""))]
        if gene_anchors:
            first = gene_anchors[0]
            href = str(first.get("href", ""))
            match = re.search(r"/e/gene/e/(\d+)\.html", href)
            if match:
                self.rows.append({
                    "wikigenes_id": match.group(1),
                    "symbol": " ".join(str(first.get("text", "")).split()),
                    "description": " ".join(str(gene_anchors[1].get("text", "")).split()) if len(gene_anchors) > 1 else "",
                    "species": " ".join(str(self.row.get("species", "")).split()),
                    "url": urljoin(BASE_URL, href),
                })
        self.row = None
        self.row_depth = None
        self.anchor = None
        self.stack.clear()


class ArticleTextParser(HTMLParser):
    """Extract article headings and paragraphs/list items from main_content."""

    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.main_depth = 0
        self.hidden_depth = 0
        self.current: dict[str, object] | None = None
        self.blocks: list[dict[str, str]] = []
        self.links: list[str] = []
        self._block_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "div" and attrs_d.get("id") == "main_content" and not self.in_main:
            self.in_main = True
            self.main_depth = 1
            return
        if not self.in_main:
            return
        if tag == "div":
            self.main_depth += 1
        if tag in {"script", "style", "noscript"}:
            self.hidden_depth += 1
        if tag == "a":
            href = attrs_d.get("href")
            previous_heading = next(
                (block["text"] for block in reversed(self.blocks) if block["tag"].startswith("h")),
                "",
            )
            if href and self.current is not None and not str(self.current["tag"]).startswith("h") and FUNCTION_HEADING.search(previous_heading):
                self.links.append(urljoin(BASE_URL, href))
        if self.current is None and tag in self.BLOCK_TAGS and self.hidden_depth == 0:
            self.current = {"tag": tag, "text": ""}
            self._block_depth = 1
        elif self.current is not None:
            self._block_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.in_main:
            return
        if self.current is not None:
            self._block_depth -= 1
            if tag == str(self.current["tag"]) and self._block_depth <= 0:
                text = " ".join(str(self.current["text"]).split())
                if text:
                    self.blocks.append({"tag": str(self.current["tag"]), "text": text})
                self.current = None
                self._block_depth = 0
        if tag in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1
        if tag == "div":
            self.main_depth -= 1
            if self.main_depth <= 0:
                self.in_main = False

    def handle_data(self, data: str) -> None:
        if self.in_main and self.current is not None and self.hidden_depth == 0:
            self.current["text"] = str(self.current["text"]) + data

    def sections(self) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        current: dict[str, object] | None = None
        for block in self.blocks:
            if block["tag"].startswith("h"):
                current = {"heading": block["text"], "items": []}
                sections.append(current)
            else:
                if current is None:
                    current = {"heading": "Article text", "items": []}
                    sections.append(current)
                items = current["items"]
                assert isinstance(items, list)
                items.append(block["text"])
        return sections


def cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.html"


def fetch_html(url: str, cache_dir: Path, delay: float, timeout: float, retries: int, refresh: bool) -> tuple[bytes, Path, bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, url)
    if path.exists() and not refresh:
        return path.read_bytes(), path, True
    request = Request(url, headers={
        "User-Agent": "wasp-lit-wikigenes-fetch/1.0 (polite research retrieval)",
        "Accept": "text/html,application/xhtml+xml",
    })
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(60.0, delay * (2 ** (attempt - 1))))
        else:
            time.sleep(max(0.0, delay))
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get_content_type()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise ValueError(f"Expected HTML, got {content_type} from {url}")
                payload = response.read()
            path.write_bytes(payload)
            return payload, path, False
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= retries:
                break
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    time.sleep(min(60.0, float(retry_after)))
                except ValueError:
                    pass
        except (URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
    raise RuntimeError(f"Could not retrieve {url}: {last_error}") from last_error


def read_genes(args: argparse.Namespace) -> list[str]:
    genes = list(args.genes)
    if args.input:
        genes.extend(line.strip() for line in Path(args.input).read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))
    cleaned = list(dict.fromkeys(g.strip() for g in genes if g.strip()))
    if not cleaned:
        raise ValueError("Provide one or more gene symbols or --input file")
    return cleaned


def run(args: argparse.Namespace) -> dict[str, object]:
    queries = read_genes(args)
    selected_species = [SPECIES[s] for s in args.species.split(",") if s]
    results: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    seen: dict[tuple[str, str], dict[str, object]] = {}

    for query in queries:
        search_url = f"{BASE_URL}/?{urlencode({'search': query})}"
        try:
            search_bytes, search_cache, cached = fetch_html(
                search_url, Path(args.cache_dir), args.delay, args.timeout, args.retries, args.refresh
            )
            parser = SearchResultsParser()
            parser.feed(search_bytes.decode("utf-8", "replace"))
            matches = [row for row in parser.rows if row["species"] in selected_species]
            exact = [row for row in matches if row["symbol"].casefold() == query.casefold()]
            chosen = matches if args.include_nonexact else exact
            for row in chosen:
                key = (row["wikigenes_id"], row["species"])
                if key in seen:
                    previous = seen[key]
                    queries_for_record = previous["matched_queries"]
                    assert isinstance(queries_for_record, list)
                    if query not in queries_for_record:
                        queries_for_record.append(query)
                    continue
                record: dict[str, object] = {
                    "query": query,
                    "matched_queries": [query],
                    **row,
                    "taxid": {"Homo sapiens": 9606, "Mus musculus": 10090, "Rattus norvegicus": 10116}[row["species"]],
                    "exact_symbol_match": row["symbol"].casefold() == query.casefold(),
                    "search_url": search_url,
                    "search_cache_path": str(search_cache),
                    "search_response_cached": cached,
                }
                if args.fetch_pages:
                    try:
                        page_bytes, page_cache, page_cached = fetch_html(
                            row["url"], Path(args.cache_dir), args.delay, args.timeout, args.retries, args.refresh
                        )
                        page_parser = ArticleTextParser()
                        page_parser.feed(page_bytes.decode("utf-8", "replace"))
                        function_sections = [
                            section for section in page_parser.sections()
                            if FUNCTION_HEADING.search(str(section.get("heading", "")))
                        ]
                        record.update({
                            "function_sections": function_sections,
                            "function_links": list(dict.fromkeys(page_parser.links)),
                            "page_sha256": hashlib.sha256(page_bytes).hexdigest(),
                            "page_cache_path": str(page_cache),
                            "page_response_cached": page_cached,
                            "content_attribution": "WikiGenes states that registered-author contributions are CC BY 3.0; check terms and source-specific rights before reuse. NLM-derived material may carry separate terms.",
                        })
                        if not page_parser.blocks:
                            record["page_parse_warning"] = "No article text blocks found in main_content; inspect the cached HTML."
                        elif not function_sections:
                            record["function_parse_warning"] = "No clearly function-related section heading was found; inspect the cached HTML and article manually."
                    except Exception as exc:
                        record["page_error"] = str(exc)
                        errors.append({"query": query, "url": row["url"], "error": str(exc)})
                results.append(record)
                seen[key] = record
            if not chosen:
                errors.append({
                    "query": query,
                    "url": search_url,
                    "error": "No exact-symbol result for the selected species" if matches and not args.include_nonexact else "No matching gene rows for selected species",
                })
        except Exception as exc:
            errors.append({"query": query, "url": search_url, "error": str(exc)})

    return {
        "source": "WikiGenes public HTML search and gene article pages",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "species_filter": selected_species,
        "queries": queries,
        "records": results,
        "errors": errors,
        "notes": [
            "WikiGenes does not document a public gene-record REST API; this script uses the public HTML interface.",
            "Species are matched by the organism label returned by WikiGenes. No orthology is inferred.",
            "Search and article HTML are cached locally. Use --refresh to retrieve fresh copies.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("genes", nargs="*", help="Gene symbols or search terms")
    parser.add_argument("--input", help="Text file with one gene symbol/search term per line")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--cache-dir", default=str(Path.home() / ".cache/wasp-lit/wikigenes"), help="HTML response cache directory")
    parser.add_argument("--species", default="human,mouse,rat", help="Comma-separated subset of human,mouse,rat")
    parser.add_argument("--include-nonexact", action="store_true", help="Include non-exact symbol search matches for review")
    parser.add_argument("--no-fetch-pages", dest="fetch_pages", action="store_false", help="Return matching page links without downloading article pages")
    parser.set_defaults(fetch_pages=True)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait before each uncached request (default: 2)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--refresh", action="store_true", help="Ignore cached responses and retrieve fresh HTML")
    args = parser.parse_args()
    allowed = {"human", "mouse", "rat"}
    args.species = ",".join(x.strip().lower() for x in args.species.split(",") if x.strip())
    if not args.species or set(args.species.split(",")) - allowed:
        parser.error("--species values must be a comma-separated subset of human,mouse,rat")
    if args.delay < 0 or args.timeout <= 0 or args.retries < 0:
        parser.error("delay/retries must be nonnegative and timeout must be positive")
    try:
        output = run(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "records": len(output["records"]), "errors": len(output["errors"])}))
    return 0 if not output["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
