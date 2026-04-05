#!/usr/bin/env python3
"""
County Records Index Scraper
=============================
Local server + browser tools for scraping county clerk search results
from two different platforms:

  - Freestone County (Neumo/GovOS) — use the bookmarklet
  - Limestone County (KoFile CountyFusion) — use the console snippet

Usage:
    1. Run:  python3 tools/county_scraper.py
    2. Open the control panel at http://localhost:8765
    3. Follow the per-county instructions on that page
    4. Repeat for each page / surname search
    5. Click "Finish & Export" when done

Records are deduplicated by county + doc number. The final output is a
CSV file saved to the working directory.
"""

import http.server
import json
import csv
import io
import os
import re
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from collections import OrderedDict

HOST = "127.0.0.1"
PORT = 8765

# ── Global state ──────────────────────────────────────────────────
records: OrderedDict[str, dict] = OrderedDict()   # keyed by "county:doc_number"
search_log: list[str] = []                          # log of scrape events


# ══════════════════════════════════════════════════════════════════
#  FREESTONE parser (Neumo/GovOS)
#  Simple <table> with <td class="col-N"> and <span> content.
#  Columns: col-3=Grantor, col-4=Grantee, col-5=Doc Type,
#           col-6=Recorded Date, col-7=Doc Number,
#           col-8=Book/Volume/Page, col-9=Legal Description
# ══════════════════════════════════════════════════════════════════

class FreestoneParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._in_data_row = False
        self._current_col: str | None = None
        self._current_text: list[str] = []
        self._current_row: dict = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "tr" and d.get("role") == "row":
            self._in_data_row = True
            self._current_row = {}
        if tag == "td" and self._in_data_row:
            cls = d.get("class", "")
            m = re.search(r'col-(\d+)', cls)
            if m:
                self._current_col = m.group(1)
                self._current_text = []

    def handle_data(self, data):
        if self._current_col is not None:
            stripped = data.strip()
            if stripped:
                self._current_text.append(stripped)

    def handle_endtag(self, tag):
        if tag == "td" and self._current_col is not None:
            text = " ".join(self._current_text).strip()
            col = self._current_col
            if col == "3":
                self._current_row["grantor"] = text
            elif col == "4":
                self._current_row["grantee"] = text
            elif col == "5":
                self._current_row["doc_type"] = text
            elif col == "6":
                self._current_row["recorded"] = text
            elif col == "7":
                self._current_row["doc_number"] = text
            elif col == "8":
                self._current_row["book_page"] = text
            elif col == "9":
                self._current_row["legal"] = text
            self._current_col = None

        if tag == "tr" and self._in_data_row:
            if self._current_row.get("doc_number"):
                self.rows.append(self._current_row)
            self._current_row = {}
            self._in_data_row = False


# ══════════════════════════════════════════════════════════════════
#  LIMESTONE parser (KoFile CountyFusion)
#  EasyUI datagrid with <td field="N"> inside nested <tr> wrappers.
#  Fields: 20=row#, 2=Instrument#, 4=Book/Page, 5=Doc Type,
#          6=name role, 7=Name (title attr has full list with ::),
#          8=other role, 9=Other Name, 10=Recorded, additionalData
# ══════════════════════════════════════════════════════════════════

class LimestoneParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._current_field: str | None = None
        self._current_text: list[str] = []
        self._current_row: dict = {}
        self._in_row = False
        self._title_attr: str | None = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "tr" and "datagrid-row-index" in d:
            self._in_row = True
            self._current_row = {}
        if tag == "td" and "field" in d and self._in_row:
            self._current_field = d["field"]
            self._current_text = []
            self._title_attr = None
        if tag == "span" and self._current_field in ("7", "9"):
            title = d.get("title", "")
            if title and "::" in title:
                self._title_attr = title

    def handle_data(self, data):
        if self._current_field is not None:
            stripped = data.strip()
            if stripped:
                self._current_text.append(stripped)

    def handle_endtag(self, tag):
        if tag == "td" and self._current_field is not None and self._in_row:
            text = " ".join(self._current_text).strip()
            field = self._current_field

            if field == "20":
                self._current_row["row_num"] = text.replace("\xa0", "").strip()
            elif field == "2":
                self._current_row["doc_number"] = text
            elif field == "4":
                self._current_row["book_page"] = text
            elif field == "5":
                self._current_row["doc_type"] = text
            elif field == "6":
                self._current_row["name_role"] = text
            elif field == "7":
                self._current_row["grantor_or_name"] = text
                if self._title_attr:
                    self._current_row["all_names"] = self._title_attr.replace("::", ";")
                else:
                    self._current_row["all_names"] = text
            elif field == "8":
                self._current_row["other_role"] = text
            elif field == "9":
                self._current_row["other_name"] = text
                if self._title_attr:
                    self._current_row["all_other_names"] = self._title_attr.replace("::", ";")
                else:
                    self._current_row["all_other_names"] = text
            elif field == "10":
                self._current_row["recorded"] = text
            elif field == "additionalData":
                self._current_row["legal"] = text.strip("| ").strip()

            self._current_field = None
            self._title_attr = None

        if tag == "tr" and self._in_row and self._current_row.get("doc_number"):
            row = self._current_row
            name_role = row.get("name_role", "").upper()
            name = row.get("grantor_or_name", "")
            all_names = row.get("all_names", "")
            other_name = row.get("other_name", "")
            all_other_names = row.get("all_other_names", "")

            if name_role == "GTOR":
                row["grantor"] = name
                row["all_grantors"] = all_names
                row["grantee"] = other_name
                row["all_grantees"] = all_other_names
            elif name_role == "GTEE":
                row["grantee"] = name
                row["all_grantees"] = all_names
                row["grantor"] = other_name
                row["all_grantors"] = all_other_names
            else:
                row["grantor"] = name
                row["all_grantors"] = all_names
                row["grantee"] = other_name
                row["all_grantees"] = all_other_names

            self.rows.append(row)
            self._current_row = {}
            self._in_row = False


# ── Unified parser dispatch ───────────────────────────────────────

def detect_site(html: str) -> str:
    if 'role="row"' in html and 'col-3' in html:
        return "freestone"
    if "datagrid-row-index" in html or "datagrid-btable" in html:
        return "limestone"
    return "unknown"


def detect_county(html: str, url: str) -> str:
    combined = (html + url).lower()
    if "freestone" in combined:
        return "Freestone"
    if "limestone" in combined:
        return "Limestone"
    return "Unknown"


def parse_results_html(html: str) -> tuple[list[dict], str]:
    site = detect_site(html)
    if site == "freestone":
        parser = FreestoneParser()
        parser.feed(html)
        return parser.rows, site
    elif site == "limestone":
        parser = LimestoneParser()
        parser.feed(html)
        return parser.rows, site
    return [], "unknown"


# ── Bookmarklet JS (Freestone only) ──────────────────────────────
BOOKMARKLET_CODE = r"""
(function(){
    var html = '';
    try {
        var t = document.querySelector('table[style] caption');
        if (t) {
            html = t.parentElement.outerHTML;
        }
        if (!html) { alert('No results table found.\n\nThis bookmarklet works on the Freestone County site.\nFor Limestone, use the console snippet from the control panel.'); return; }
    } catch(e) { alert('Error: ' + e); return; }
    var x = new XMLHttpRequest();
    x.open('POST', 'http://127.0.0.1:PORT/scrape', true);
    x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    x.onload = function(){
        var r = JSON.parse(x.responseText);
        alert('Captured ' + r.new_count + ' new records (' + r.dup_count + ' duplicates skipped).\nTotal: ' + r.total);
    };
    x.onerror = function(){ alert('Could not reach scraper server.\nIs it running on port PORT?'); };
    x.send('html=' + encodeURIComponent(html) + '&url=' + encodeURIComponent(window.location.href));
})();
""".replace("PORT", str(PORT)).strip()

BOOKMARKLET = "javascript:" + urllib.parse.quote(BOOKMARKLET_CODE, safe="")

# ── Console snippet for Limestone (KoFile nested frames) ─────────
# The user pastes this into the browser console. It must be run in the
# top-level frame context. It walks the known frame path to reach the
# results iframe and sends the rendered datagrid HTML.
LIMESTONE_SNIPPET = r"""
(function(){
    var html = null;
    /* Walk all frames recursively looking for the results datagrid */
    function find(w, depth) {
        if (depth > 6) return null;
        try {
            var tbls = w.document.querySelectorAll('table.datagrid-btable');
            for (var i = 0; i < tbls.length; i++) {
                if (tbls[i].querySelector('td[field="2"]')) return tbls[i].outerHTML;
            }
        } catch(e) {}
        try {
            for (var i = 0; i < w.frames.length; i++) {
                var r = find(w.frames[i], depth + 1);
                if (r) return r;
            }
        } catch(e) {}
        return null;
    }
    html = find(window, 0);
    if (!html) { console.log('ERROR: No results table found. Make sure search results are visible.'); return; }
    var x = new XMLHttpRequest();
    x.open('POST', 'http://127.0.0.1:PORT/scrape', true);
    x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    x.onload = function(){
        var r = JSON.parse(x.responseText);
        console.log('Captured ' + r.new_count + ' new, ' + r.dup_count + ' dups. Total: ' + r.total);
    };
    x.onerror = function(){ console.log('ERROR: Could not reach scraper on port PORT'); };
    x.send('html=' + encodeURIComponent(html) + '&url=' + encodeURIComponent(window.location.href));
})();
""".replace("PORT", str(PORT)).strip()


# ── Common column schema for output ──────────────────────────────
OUTPUT_COLS = [
    ("county",        "County"),
    ("doc_number",    "Doc Number"),
    ("book_page",     "Book/Page"),
    ("doc_type",      "Doc Type"),
    ("grantor",       "Grantor"),
    ("all_grantors",  "All Grantors"),
    ("grantee",       "Grantee"),
    ("all_grantees",  "All Grantees"),
    ("recorded",      "Recorded"),
    ("legal",         "Legal Description"),
]


# ── Control panel HTML ────────────────────────────────────────────
def control_panel_html():
    county_counts = {}
    for r in records.values():
        c = r.get("county", "Unknown")
        county_counts[c] = county_counts.get(c, 0) + 1

    county_summary = ", ".join(f"{c}: {n}" for c, n in sorted(county_counts.items())) or "none yet"

    log_html = ""
    for entry in reversed(search_log[-20:]):
        log_html += f"<div class='log-entry'>{entry}</div>\n"

    # Escape the snippet for safe embedding in HTML
    snippet_escaped = LIMESTONE_SNIPPET.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html><head><title>County Records Scraper</title>
<style>
    body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; background: #f8f9fa; }}
    h1 {{ color: #333; margin-bottom: 0.3em; }}
    .status {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 1em 1.5em; margin: 1em 0; }}
    .count {{ font-size: 2em; font-weight: bold; color: #2563eb; }}
    .counties {{ color: #666; margin-top: 0.3em; }}
    .bookmarklet-link {{ display: inline-block; background: #2563eb; color: #fff; padding: 10px 20px;
        border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 1.1em; cursor: grab; }}
    .bookmarklet-link:hover {{ background: #1d4ed8; }}
    .section {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 1em 1.5em; margin: 1em 0; }}
    .section h3 {{ margin-top: 0; }}
    .section ol {{ padding-left: 1.5em; }}
    .section li {{ margin: 0.5em 0; }}
    .btn {{ display: inline-block; padding: 10px 24px; border-radius: 6px; border: none; font-size: 1em;
        font-weight: bold; cursor: pointer; text-decoration: none; margin-right: 8px; }}
    .btn-green {{ background: #16a34a; color: #fff; }}
    .btn-green:hover {{ background: #15803d; }}
    .btn-red {{ background: #dc2626; color: #fff; }}
    .btn-red:hover {{ background: #b91c1c; }}
    .btn-gray {{ background: #6b7280; color: #fff; }}
    .btn-gray:hover {{ background: #4b5563; }}
    .log {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 1em; margin: 1em 0;
        max-height: 300px; overflow-y: auto; font-size: 0.9em; }}
    .log-entry {{ padding: 4px 0; border-bottom: 1px solid #f0f0f0; color: #555; }}
    code {{ background: #e5e7eb; padding: 2px 6px; border-radius: 3px; }}
    .snippet-box {{ background: #1e293b; color: #e2e8f0; padding: 1em; border-radius: 6px;
        font-family: monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-all;
        max-height: 150px; overflow-y: auto; cursor: pointer; position: relative; }}
    .snippet-box:hover {{ background: #334155; }}
    .copy-hint {{ position: absolute; top: 6px; right: 10px; background: #475569; padding: 2px 8px;
        border-radius: 4px; font-size: 0.85em; }}
</style></head>
<body>
<h1>County Records Scraper</h1>

<div class="status">
    <div class="count">{len(records)} records captured</div>
    <div class="counties">{county_summary}</div>
</div>

<div class="section">
<h3>Freestone County (bookmarklet)</h3>
<p>Drag this to your bookmarks bar:</p>
<p><a class="bookmarklet-link" href='{BOOKMARKLET}'>Scrape Freestone</a></p>
<ol>
    <li>Search on the Freestone County clerk site</li>
    <li>When you see results, click <b>Scrape Freestone</b> in your bookmarks bar</li>
    <li>Navigate to the next page and repeat</li>
</ol>
</div>

<div class="section">
<h3>Limestone County (console snippet)</h3>
<p>The Limestone site uses nested frames that block the bookmarklet. Instead:</p>
<ol>
    <li>Search on the Limestone County clerk site so results are showing</li>
    <li>Press <b>F12</b> to open DevTools, click the <b>Console</b> tab</li>
    <li>Click the snippet below to copy it, then paste into the console and press Enter</li>
    <li>Navigate to the next page, press Up Arrow in console, Enter. Repeat.</li>
</ol>
<div class="snippet-box" onclick="navigator.clipboard.writeText(this.innerText.replace('Click to copy','').trim()); this.querySelector('.copy-hint').innerText='Copied!';" title="Click to copy">
<span class="copy-hint">Click to copy</span>
{snippet_escaped}</div>
</div>

<div style="margin: 1.5em 0;">
    <a class="btn btn-green" href="/export?format=csv">Finish &amp; Export CSV</a>
    <a class="btn btn-gray" href="/export?format=preview">Preview Table</a>
    <a class="btn btn-red" href="/clear" onclick="return confirm('Clear all {len(records)} records?');">Clear All</a>
</div>

<div class="log">
    <strong>Activity Log</strong>
    {log_html if log_html else "<div class='log-entry'><em>No scrapes yet.</em></div>"}
</div>

<script>setTimeout(function(){{ location.reload(); }}, 5000);</script>
</body></html>"""


def preview_html():
    if not records:
        return "<html><body><h2>No records yet.</h2><p><a href='/'>Back</a></p></body></html>"

    rows_html = ""
    for r in records.values():
        rows_html += "<tr>"
        for col_key, _ in OUTPUT_COLS:
            val = r.get(col_key, "")
            rows_html += f"<td>{val}</td>"
        rows_html += "</tr>\n"

    header_html = "".join(f"<th>{label}</th>" for _, label in OUTPUT_COLS)

    return f"""<!DOCTYPE html><html><head><title>Preview</title>
<style>
    body {{ font-family: system-ui, sans-serif; margin: 1em; }}
    table {{ border-collapse: collapse; font-size: 0.85em; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; white-space: nowrap; }}
    th {{ background: #f0f0f0; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #f9f9f9; }}
</style></head><body>
<h2>{len(records)} records</h2>
<p><a href="/">Back to control panel</a> | <a href="/export?format=csv">Export CSV</a></p>
<div style="overflow: auto; max-height: 80vh;">
<table>
<tr>{header_html}</tr>
{rows_html}
</table></div></body></html>"""


def export_csv() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in OUTPUT_COLS])
    for r in records.values():
        writer.writerow([r.get(col_key, "") for col_key, _ in OUTPUT_COLS])
    return buf.getvalue()


# ── HTTP handler ��─────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/":
            self._respond_html(control_panel_html())

        elif parsed.path == "/export":
            params = urllib.parse.parse_qs(parsed.query)
            fmt = params.get("format", ["csv"])[0]

            if fmt == "preview":
                self._respond_html(preview_html())
            else:
                csv_data = export_csv()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"county_index_{timestamp}.csv"
                filepath = os.path.join(os.getcwd(), filename)
                with open(filepath, "w", newline="") as f:
                    f.write(csv_data)
                search_log.append(f"Exported {len(records)} records to {filename}")

                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(csv_data.encode("utf-8"))

        elif parsed.path == "/clear":
            records.clear()
            search_log.append("Cleared all records")
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/scrape":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = urllib.parse.parse_qs(body)
            html = params.get("html", [""])[0]
            url = params.get("url", [""])[0]

            county = detect_county(html, url)
            rows, site = parse_results_html(html)

            print(f"[scrape] county={county} site={site} rows={len(rows)} html_len={len(html)}")

            new_count = 0
            dup_count = 0
            for row in rows:
                doc = row.get("doc_number", "")
                if not doc:
                    continue
                key = f"{county}:{doc}"
                row["county"] = county
                if key in records:
                    dup_count += 1
                else:
                    records[key] = row
                    new_count += 1

            if rows:
                first = rows[0].get("doc_number", "?")
                last = rows[-1].get("doc_number", "?")
                search_log.append(
                    f"{county} ({site}): +{new_count} new, {dup_count} dups "
                    f"(total {len(records)}) — {len(rows)} rows, "
                    f"{first} .. {last}"
                )
            else:
                search_log.append(f"{county} ({site}): no rows found in page")

            resp = json.dumps({
                "new_count": new_count,
                "dup_count": dup_count,
                "total": len(records),
                "site": site,
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _respond_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


# ── Main ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    server = http.server.HTTPServer((HOST, PORT), Handler)
    print(f"County Records Scraper running at http://{HOST}:{PORT}")
    print(f"Open that URL in your browser for instructions.")
    print(f"Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nStopped. {len(records)} records in memory (not saved).")
        if records:
            print("Run again and export to save, or records are lost.")
        server.server_close()
