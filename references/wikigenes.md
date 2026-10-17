# WikiGenes gene-page retrieval

`scripts/wikigenes.py` retrieves WikiGenes gene articles for Homo sapiens, Mus musculus, and Rattus norvegicus. It is an optional contextual-source helper and does not modify the PubMed corpus or replace NCBI Gene summaries.

## Interface and limitations

WikiGenes search is a public HTML interface. The site terms mention WikiGenes APIs, but its available tutorial documents an OAuth/user API and says application libraries must be requested; it does not document a public gene-record REST API. The script therefore parses the HTML search results and linked gene pages. Page structure may change, and a server error or empty parse is reported rather than interpreted as no gene record.

Search result rows are filtered by the organism label returned by WikiGenes. The script does not infer orthology or equate genes across taxa. By default, a row must have a case-insensitive exact match to the supplied symbol. Use `--include-nonexact` only to review other search hits. Supply species-specific symbols or aliases as separate queries when needed. Multiple results are returned without silently selecting one.

WikiGenes states that contributions by registered authors are licensed under CC BY 3.0. Its terms also warn that integrated NLM material can have separate restrictions. The script records source URLs, retrieval time, checksums, cached raw HTML, and a licensing notice. Review the article's attribution, linked references, and source-specific rights before redistributing extracted text. Scrape politely; the default is sequential requests separated by two seconds, with a local response cache and retry backoff.

WikiGenes pages can contain text linked to unrelated entities or statements from different contexts. Treat the extracted sections as source text, not as a validated gene-function summary. Check cited primary literature before relying on a claim.

## Usage

```bash
python3 scripts/wikigenes.py CACNA1C --output results/cacna1c-wikigenes.json
python3 scripts/wikigenes.py Cacna1c CACNA1C --output results/cacna1c-wikigenes.json
python3 scripts/wikigenes.py --input gene_symbols.txt --output results/wikigenes.json
```

The default species filter includes human, mouse, and rat. Narrow it with `--species human,rat`. The JSON contains symbol, WikiGenes page ID and URL, organism, taxon ID, headings/items and citation links from function-related sections only, cached HTML paths, checksums, and errors. If no recognized function section is found, the script records a warning rather than substituting disease or unrelated text. The cache is under `~/.cache/wasp-lit/wikigenes/` by default. Use `--refresh` to retrieve fresh pages; `--no-fetch-pages` returns matches and URLs without requesting each gene page.

The HTML interface may be temporarily inaccessible or may change. Test live retrieval with one gene before a batch. The current execution environment returned HTTP 503 to direct shell requests, so parser tests are offline and do not establish that live batch retrieval succeeds from this environment.

## Source and terms

- WikiGenes search interface: <https://www.wikigenes.org/>
- WikiGenes tutorial: <https://www.wikigenes.org/static/pdf/tutorial/wikigenes_tutorial.pdf>
- WikiGenes terms: <https://www.wikigenes.org/app/info/docs/legal/terms.html>
- WikiGenes open-access statement: <https://www.wikigenes.org/app/info/docs/legal/openAccess.html>
