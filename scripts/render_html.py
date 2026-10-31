#!/usr/bin/env python3
"""Render wasp-lit workspace Markdown files as interactive HTML documents with dark theme and PubMed tooltips."""

import argparse
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
import markdown

SOURCECERY_NORD_CSS = """
:root {
  /* High-Contrast Dark Theme Palette */
  --bg-color: #14171d;
  --panel-bg-color: #1d212a;
  --card-bg-color: #1d212a;
  --text-color: #ebcb8b;
  --text-muted: #c5b89a;
  --header-color: #f8f8f2;
  --border-color: #3b4252;
  --border-light: #2a303c;
  --control-bg-color: #2e3440;
  --accent-color: #88c0d0;
  --accent-hover-color: #a3e8ff;
  --accent-bg-color: rgba(136, 192, 208, 0.14);
  --accent-bg-hover-color: rgba(136, 192, 208, 0.28);
  --authoryear-color: #d8dee9;
  --authoryear-bg-color: #2e3440;
  --code-bg: #101217;
  --table-stripe: #232833;
  --badge-bg: #2e3440;
  --badge-text: #ebcb8b;
  --shadow: 0 8px 32px rgba(0, 0, 0, 0.7);
  --tooltip-shadow: 0 12px 36px rgba(0, 0, 0, 0.85);
}

* {
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  margin: 0;
  padding: 0;
  background-color: var(--bg-color);
  color: var(--text-color);
  line-height: 1.65;
  font-size: 15px;
}

/* Header & Top Navigation Bar */
.top-nav {
  position: sticky;
  top: 0;
  z-index: 1000;
  background-color: var(--panel-bg-color);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
  padding: 10px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.nav-brand {
  font-weight: 700;
  font-size: 1.15em;
  color: var(--header-color);
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-brand .tag {
  font-size: 0.72em;
  background-color: var(--accent-color);
  color: #2e3440;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.nav-link {
  color: var(--text-color);
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 5px;
  font-size: 0.88em;
  font-weight: 500;
  transition: all 0.15s ease;
  background-color: transparent;
  border: 1px solid transparent;
}

.nav-link:hover {
  background-color: var(--control-bg-color);
  color: var(--header-color);
}

.nav-link.active {
  background-color: var(--accent-bg-color);
  color: var(--accent-color);
  border-color: rgba(136, 192, 208, 0.4);
  font-weight: 600;
}

/* Main Layout Container */
.container {
  max-width: 1060px;
  margin: 32px auto;
  padding: 0 24px 64px 24px;
}

.content-card {
  background-color: var(--card-bg-color);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 40px 48px;
  box-shadow: var(--shadow);
}

/* Typography */
h1, h2, h3, h4, h5, h6 {
  color: var(--header-color);
  font-weight: 700;
  line-height: 1.3;
}

h1 {
  font-size: 1.85em;
  margin-top: 0;
  margin-bottom: 0.5em;
  padding-bottom: 0.4em;
  border-bottom: 1px solid var(--border-color);
}

h2 {
  font-size: 1.35em;
  margin-top: 1.8em;
  margin-bottom: 0.6em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--border-light);
}

h3 {
  font-size: 1.15em;
  margin-top: 1.4em;
  margin-bottom: 0.4em;
}

p, ul, ol {
  margin-top: 0;
  margin-bottom: 1em;
}

ul, ol {
  padding-left: 26px;
}

li {
  margin-bottom: 6px;
}

strong {
  color: #fff9e6;
  font-weight: 600;
}

/* Links */
a {
  color: var(--accent-color);
  text-decoration: none;
  transition: color 0.15s, background-color 0.15s;
}

a:hover {
  color: #ffffff;
  text-decoration: underline;
}

/* PMID Links with Tooltip triggers */
a.pmid-link {
  display: inline-block;
  color: var(--accent-color);
  background-color: var(--accent-bg-color);
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.9em;
  padding: 1px 6px;
  margin: 1px 2px;
  border-radius: 4px;
  border: 1px solid rgba(136, 192, 208, 0.28);
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

a.pmid-link:hover {
  background-color: var(--accent-bg-hover-color);
  border-color: var(--accent-color);
  color: #eceff4;
  text-decoration: none;
  box-shadow: 0 0 8px rgba(136, 192, 208, 0.35);
  transform: translateY(-1px);
}

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 24px 0;
  font-size: 0.9em;
  background-color: var(--card-bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  display: table;
}

th {
  background-color: var(--control-bg-color);
  color: var(--header-color);
  font-weight: 600;
  text-align: left;
  padding: 10px 14px;
  border-bottom: 2px solid var(--border-color);
}

td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-color);
  vertical-align: top;
}

tr:nth-child(even) td {
  background-color: var(--table-stripe);
}

tr:hover td {
  background-color: rgba(136, 192, 208, 0.08);
}

/* Code & Preformatted Text */
code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  background-color: var(--code-bg);
  color: #ebcb8b;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
}

pre {
  background-color: var(--code-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 14px 18px;
  overflow-x: auto;
}

pre code {
  background-color: transparent;
  padding: 0;
  color: #e5e9f0;
}

hr {
  border: 0;
  height: 1px;
  background-color: var(--border-color);
  margin: 28px 0;
}

/* SourceCery Tooltip */
#tooltip {
  display: none;
  position: absolute;
  background-color: #171b22;
  border: 1px solid var(--accent-color);
  border-radius: 8px;
  box-shadow: var(--tooltip-shadow);
  padding: 18px 20px;
  z-index: 10000;
  pointer-events: none;
  line-height: 1.55;
  color: var(--text-color);
  max-width: 540px;
  font-size: 13.5px;
  backdrop-filter: blur(6px);
  transition: opacity 0.15s ease;
}

#tooltip .pmid-badge {
  display: inline-block;
  background-color: var(--accent-color);
  color: #14171d;
  font-size: 0.75em;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  margin-bottom: 8px;
  font-family: monospace;
}

#tooltip .title {
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 6px;
  font-size: 1.05em;
  line-height: 1.35;
}

#tooltip .authors {
  font-style: italic;
  color: var(--authoryear-color);
  margin-bottom: 6px;
  font-size: 0.92em;
}

#tooltip .journal {
  font-size: 0.9em;
  color: var(--accent-color);
  margin-bottom: 12px;
  font-weight: 500;
}

#tooltip .abstract {
  font-size: 0.92em;
  max-height: 320px;
  overflow-y: auto;
  border-top: 1px solid var(--border-color);
  padding-top: 10px;
  color: var(--text-color);
  line-height: 1.55;
}

#tooltip .abstract p {
  margin: 0 0 8px 0;
}

#tooltip .loading {
  font-style: italic;
  color: var(--text-muted);
}
"""

SOURCECERY_JS = """
// SourceCery Tooltip and Dynamic Retrieval Logic
(function() {
  const tooltip = document.getElementById("tooltip");
  let currentHoverPmid = null;
  const fetchingPmids = new Set();

  function formatAuthors(authorsArr) {
    if (!authorsArr || authorsArr.length === 0) return "Unknown authors";
    if (authorsArr.length > 3) {
      return `${authorsArr[0]}, ..., ${authorsArr[authorsArr.length - 1]}`;
    }
    return authorsArr.join(", ");
  }

  function positionTooltip(e) {
    if (!tooltip || tooltip.style.display !== "block") return;
    const pad = 16;
    const tipWidth = tooltip.offsetWidth || 480;
    const tipHeight = tooltip.offsetHeight || 260;
    let left = e.pageX + pad;
    let top = e.pageY + pad;

    // Viewport collision handling
    if (e.clientX + pad + tipWidth > window.innerWidth) {
      left = Math.max(10, e.pageX - tipWidth - pad);
    }
    if (e.clientY + pad + tipHeight > window.innerHeight) {
      top = Math.max(10, e.pageY - tipHeight - pad);
    }
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  async function fetchBatchPmidData(pmids) {
    const toFetch = pmids.filter(p => !window.pmidCache[p]);
    if (toFetch.length === 0) return;
    try {
      const response = await fetch(
        `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id=${toFetch.join(",")}`
      );
      const xmlText = await response.text();
      const xmlDoc = new DOMParser().parseFromString(xmlText, "text/xml");
      xmlDoc.querySelectorAll("PubmedArticle").forEach((article) => {
        const pmid = article.querySelector("PMID")?.textContent;
        if (!pmid) return;

        const firstAuthorLastName =
          article.querySelector("Author LastName")?.textContent || "N/A";
        const year =
          article.querySelector("PubDate Year")?.textContent || "N/A";
        const title =
          article.querySelector("ArticleTitle")?.textContent ||
          "No Title Found";
        const abstractText =
          Array.from(article.querySelectorAll("AbstractText"))
            .map((el) => {
              const label = el.getAttribute("Label");
              return (label ? "<strong>" + label + ":</strong> " : "") + el.textContent;
            })
            .join("<br><br>") || "No Abstract Found.";

        const authorsArray = Array.from(
          article.querySelectorAll("Author")
        ).map((author) =>
          `${author.querySelector("LastName")?.textContent || ""} ${author.querySelector("Initials")?.textContent || ""}`.trim()
        ).filter(Boolean);

        const journal =
          article.querySelector("Journal Title")?.textContent ||
          article.querySelector("Journal ISOAbbreviation")?.textContent || "";

        window.pmidCache[pmid] = {
          authorYear: `${firstAuthorLastName} ${year}`,
          tooltipData: {
            title,
            authors: formatAuthors(authorsArray),
            journal: year !== "N/A" ? `${journal} (${year})` : journal,
            abstract: abstractText,
          },
        };
      });
    } catch (error) {
      console.error("Failed to fetch batch PMID data:", error);
    }
  }

  function showTooltip(pmid, e) {
    const entry = window.pmidCache ? window.pmidCache[pmid] : null;
    if (entry && entry.tooltipData) {
      const d = entry.tooltipData;
      tooltip.innerHTML = `
        <div class="pmid-badge">PMID: ${pmid}</div>
        <div class="title">${d.title}</div>
        <div class="authors">${d.authors}</div>
        <div class="journal">${d.journal}</div>
        <div class="abstract">${d.abstract}</div>
      `;
    } else {
      tooltip.innerHTML = `
        <div class="pmid-badge">PMID: ${pmid}</div>
        <div class="loading">Fetching PubMed details from NCBI...</div>
      `;
      if (!fetchingPmids.has(pmid)) {
        fetchingPmids.add(pmid);
        fetchBatchPmidData([pmid]).then(() => {
          if (currentHoverPmid === pmid) {
            showTooltip(pmid, e);
          }
        });
      }
    }
    tooltip.style.display = "block";
    positionTooltip(e);
  }

  document.addEventListener("mouseover", (e) => {
    const target = e.target.closest("[data-pmid]");
    if (target) {
      const pmid = target.getAttribute("data-pmid");
      if (pmid) {
        currentHoverPmid = pmid;
        showTooltip(pmid, e);
      }
    }
  });

  document.addEventListener("mouseout", (e) => {
    const target = e.target.closest("[data-pmid]");
    if (target) {
      currentHoverPmid = null;
      if (tooltip) tooltip.style.display = "none";
    }
  });

  document.addEventListener("mousemove", (e) => {
    if (currentHoverPmid) {
      positionTooltip(e);
    }
  });
})();
"""


def extract_pubmed_cache_from_corpus(corpus_dir, extra_pmids=None):
    """Build an in-memory dictionary of PubMed metadata from corpus/articles.jsonl."""
    cache = {}
    articles_path = Path(corpus_dir) / "articles.jsonl"
    if articles_path.exists():
        with open(articles_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    art = json.loads(line)
                    pmid = str(art.get("pmid"))
                    authors = art.get("authors") or []
                    if len(authors) > 3:
                        display_authors = f"{authors[0]}, ..., {authors[-1]}"
                    elif authors:
                        display_authors = ", ".join(authors)
                    else:
                        display_authors = "Unknown authors"
                    year = (art.get("publication_date") or {}).get("Year") or "N/A"
                    first_ln = authors[0].split()[0] if authors else "N/A"
                    journal = art.get("journal") or ""
                    journal_label = f"{journal} ({year})" if journal and year != "N/A" else (journal or str(year))
                    abstract = art.get("abstract") or "No abstract recorded in corpus."
                    abstract_html = "<br><br>".join(html.escape(p) for p in abstract.split("\n") if p.strip())
                    cache[pmid] = {
                        "authorYear": f"{first_ln} {year}",
                        "tooltipData": {
                            "title": art.get("title") or "No Title Found",
                            "authors": display_authors,
                            "journal": journal_label,
                            "abstract": abstract_html,
                        },
                    }
                except Exception:
                    pass

    # Check if extra PMIDs need fetching from NCBI efetch
    missing = [str(p) for p in (extra_pmids or []) if str(p) not in cache]
    if missing:
        try:
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id={','.join(missing)}"
            req = urllib.request.Request(url, headers={"User-Agent": "wasp-lit/0.4.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for article in root.findall(".//PubmedArticle"):
                pmid = article.findtext(".//PMID")
                if not pmid:
                    continue
                title = article.findtext(".//ArticleTitle") or "No Title Found"
                journal = article.findtext(".//Journal/Title") or article.findtext(".//Journal/ISOAbbreviation") or ""
                year = article.findtext(".//JournalIssue/PubDate/Year") or article.findtext(".//PubDate/Year") or "N/A"
                first_ln = article.findtext(".//AuthorList/Author[1]/LastName") or "N/A"
                authors_list = []
                for a in article.findall(".//AuthorList/Author"):
                    ln = a.findtext("LastName") or ""
                    init = a.findtext("Initials") or ""
                    full_a = f"{ln} {init}".strip()
                    if full_a:
                        authors_list.append(full_a)
                if len(authors_list) > 3:
                    display_authors = f"{authors_list[0]}, ..., {authors_list[-1]}"
                elif authors_list:
                    display_authors = ", ".join(authors_list)
                else:
                    display_authors = "Unknown authors"
                abstract_nodes = article.findall(".//Abstract/AbstractText")
                if abstract_nodes:
                    abstract_parts = []
                    for el in abstract_nodes:
                        lbl = el.attrib.get("Label")
                        txt = el.text or ""
                        abstract_parts.append(f"<strong>{html.escape(lbl)}:</strong> {html.escape(txt)}" if lbl else html.escape(txt))
                    abstract_html = "<br><br>".join(abstract_parts)
                else:
                    abstract_html = "No abstract available."
                cache[pmid] = {
                    "authorYear": f"{first_ln} {year}",
                    "tooltipData": {
                        "title": title,
                        "authors": display_authors,
                        "journal": f"{journal} ({year})" if year != "N/A" else journal,
                        "abstract": abstract_html,
                    },
                }
        except Exception as e:
            sys.stderr.write(f"Notice: Could not pre-fetch external PMIDs ({e}); fallback will load in browser.\n")

    return cache


NAV_PAGES = [
    ("synthesis", "synthesis.html", "Synthesis"),
    ("gene-function", "gene-function.html", "Gene Function"),
    ("user-decisions", "user-decisions.html", "User Decisions"),
    ("ai-decisions", "ai-decisions.html", "AI Decisions"),
    ("gwas-associations", "gwas-associations.html", "GWAS Associations"),
    ("README", "README.html", "Overview"),
]


def render_html_page(title, body_html, active_key, gene_symbol, cache_dict):
    """Wrap body HTML in the complete dark theme layout with nav and SourceCery script."""
    nav_links = []
    for key, filename, label in NAV_PAGES:
        active_cls = " active" if key == active_key else ""
        nav_links.append(f'<a href="./{filename}" class="nav-link{active_cls}">{label}</a>')
    nav_html = "\n        ".join(nav_links)

    cache_json = json.dumps(cache_dict, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
{SOURCECERY_NORD_CSS}
  </style>
</head>
<body>
  <header class="top-nav">
    <div class="nav-brand">
      <span>wasp-lit</span>
      <span class="tag">{html.escape(gene_symbol)}</span>
    </div>
    <nav class="nav-links">
        {nav_html}
    </nav>
  </header>

  <main class="container">
    <article class="content-card">
{body_html}
    </article>
  </main>

  <div id="tooltip"></div>

  <script>
    window.pmidCache = {cache_json};
  </script>
  <script>
{SOURCECERY_JS}
  </script>
</body>
</html>
"""


def process_markdown_file(md_path, workspace_dir, gene_symbol, pmid_cache):
    """Convert one Markdown file to HTML, rewrite .md links, tag PMIDs, and write .html file."""
    md_text = md_path.read_text(encoding="utf-8")
    raw_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. Rewrite internal .md links to .html (and human-decisions to user-decisions)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "human-decisions" in href:
            href = href.replace("human-decisions", "user-decisions")
        if href.endswith(".md") or ".md#" in href:
            href = re.sub(r"\.md(\b|#)", r".html\1", href)
        a["href"] = href

    # 2. Tag existing PubMed links with class="pmid-link" and data-pmid
    for a in soup.find_all("a", href=True):
        m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", a["href"])
        if m:
            pmid = m.group(1)
            a["data-pmid"] = pmid
            classes = a.get("class", [])
            if "pmid-link" not in classes:
                classes.append("pmid-link")
            a["class"] = classes
            a["target"] = "_blank"

    # 3. Detect and tag PMIDs in text nodes (e.g. table cells, lists)
    # Check if number is in pmid_cache or in a PMID table column
    for text_node in list(soup.find_all(string=True)):
        if text_node.parent.name in ("a", "code", "pre", "script", "style", "h1"):
            continue
        # Find 7-8 digit integers
        matches = list(re.finditer(r"\b(\d{7,8})\b", str(text_node)))
        if not matches:
            continue

        # Replace matching PMIDs with links
        def _replace_pmid(match):
            val = match.group(1)
            # If it's a known PMID or parent is a table cell in a PMID column
            is_pmid = val in pmid_cache
            if not is_pmid:
                # Check context (e.g. text mentions 'PMID' nearby or inside table)
                parent = text_node.parent
                if parent.name in ("td", "th", "li", "p") and ("pmid" in str(parent).lower() or "abstract" in str(parent).lower()):
                    is_pmid = True
            if is_pmid:
                return f'<a class="pmid-link" data-pmid="{val}" href="https://pubmed.ncbi.nlm.nih.gov/{val}/" target="_blank">{val}</a>'
            return val

        new_text = re.sub(r"\b(\d{7,8})\b", _replace_pmid, str(text_node))
        if new_text != str(text_node):
            new_soup = BeautifulSoup(new_text, "html.parser")
            text_node.replace_with(new_soup)

    active_key = md_path.stem
    title = f"{gene_symbol} - {active_key.replace('-', ' ').title()}"
    h1 = soup.find("h1")
    if h1 and h1.text.strip():
        title = h1.text.strip()

    # Determine subset of cache needed for this file (or full cache)
    # For small/medium sets, full cache provides instant tooltips everywhere
    full_html = render_html_page(title, str(soup), active_key, gene_symbol, pmid_cache)

    out_path = md_path.with_suffix(".html")
    out_path.write_text(full_html, encoding="utf-8")
    return out_path


def render_workspace_html(workspace_path):
    """Render all core workspace markdown files to interactive HTML."""
    ws = Path(workspace_path).resolve()
    context_path = ws / "corpus" / "context.json"
    gene_symbol = "wasp-lit"
    if context_path.exists():
        try:
            ctx = json.loads(context_path.read_text(encoding="utf-8"))
            genes = ctx.get("genes") or []
            if genes and genes[0].get("symbol"):
                gene_symbol = genes[0]["symbol"]
        except Exception:
            pass

    # Collect any PMIDs mentioned across markdown files
    extra_pmids = set()
    for md_file in ws.glob("*.md"):
        txt = md_file.read_text(encoding="utf-8")
        for num in re.findall(r"\b\d{7,8}\b", txt):
            extra_pmids.add(num)

    corpus_dir = ws / "corpus"
    pmid_cache = extract_pubmed_cache_from_corpus(corpus_dir, extra_pmids=extra_pmids)

    # Also save pmid-cache.js in workspace for external or local asset use
    cache_js_path = ws / "pmid-cache.js"
    cache_js_path.write_text(f"window.pmidCache = {json.dumps(pmid_cache, indent=2, ensure_ascii=False)};\n", encoding="utf-8")

    generated = []
    # Render all standard workspace deliverable files
    for key, filename, _ in NAV_PAGES:
        md_file = ws / (key + ".md")
        if not md_file.exists() and key == "user-decisions":
            fallback = ws / "human-decisions.md"
            if fallback.exists():
                md_file = fallback
        if md_file.exists():
            out_file = process_markdown_file(md_file, ws, gene_symbol, pmid_cache)
            generated.append(str(out_file))
            if md_file.name == "human-decisions.md":
                user_html = ws / "user-decisions.html"
                user_html.write_text(out_file.read_text(encoding="utf-8"), encoding="utf-8")
                generated.append(str(user_html))

    return {
        "workspace": str(ws),
        "gene": gene_symbol,
        "pmids_cached": len(pmid_cache),
        "generated_html_files": generated,
        "cache_js": str(cache_js_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", help="Path to wasp-lit research workspace")
    args = parser.parse_args()
    res = render_workspace_html(args.workspace)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
