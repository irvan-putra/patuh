#!/usr/bin/env python3
"""Render a patuh JSON report as a static HTML page: every check for every
project in one table.

Usage: python3 tools/render_report.py report.json site/index.html [projects.json]

The page is static, self-contained (no external assets) and safe to publish:
it only carries what the report carries (repo names, versions, check
results) - all public repository facts.
"""
import datetime
import html
import json
import os
import sys

SEVERITIES = ["FAIL", "WARN", "REVIEW", "SKIP", "INFO", "PASS"]
SEV_CLASS = {
    "FAIL": "fail", "WARN": "warn", "REVIEW": "review",
    "SKIP": "skip", "INFO": "info", "PASS": "pass",
}
SEV_SHORT = {
    "FAIL": "F", "WARN": "W", "REVIEW": "R", "SKIP": "S", "INFO": "i", "PASS": "\u2713",
}
SEV_MEANING = {
    "FAIL": "a check ran and found drift - needs fixing",
    "WARN": "worth a look, not blocking",
    "REVIEW": "patuh cannot judge this; a human should look (never auto-passes)",
    "SKIP": "the check could not run, so that fact is unverified",
    "INFO": "context, not a verdict",
    "PASS": "the check ran and passed",
}

# Preferred column order; anything else appends alphabetically.
CHECK_ORDER = [
    "registry-coverage", "registry-missing", "registry-stale", "registry-private",
    "backup", "backup-missing", "backup-coverage",
    "package", "version", "label", "permissions", "naming",
    "readme", "commit-author", "patuh-json",
    "icon-single", "icon-variants", "icon-size", "icon-resource",
    "icon-adaptive", "icon-monochrome", "icon-fullcolor",
    "icon-corner", "icon-strip-top", "icon-strip-width",
    "icon-badge-text", "icon-badge-version", "icon-safe-circle", "icon-note",
    "release", "release-tag", "release-apk-name", "release-digest",
    "gallery-fetch", "gallery-card", "gallery-version", "gallery-sha256",
    "coverage", "source-type",
]
KIND_ORDER = {"family": 0, "android-app": 1, "web-site": 2, "inventory": 3}


def worst(rows):
    for sev in SEVERITIES:
        if any(r["severity"] == sev for r in rows):
            return sev
    return "PASS"


def esc(s):
    return html.escape(str(s), quote=True)


def main():
    report_path, out_path = sys.argv[1], sys.argv[2]
    registry_path = sys.argv[3] if len(sys.argv) > 3 else None

    with open(report_path, encoding="utf-8") as f:
        rows = json.load(f)

    kinds = {}
    if registry_path and os.path.isfile(registry_path):
        with open(registry_path, encoding="utf-8") as f:
            for p in json.load(f)["projects"]:
                kinds[p["app"]] = p.get("kind", "inventory")
                kinds.setdefault(p["repo"], p.get("kind", "inventory"))

    # matrix[project][check] = list of rows
    matrix = {}
    for r in rows:
        matrix.setdefault(r["project"], {}).setdefault(r["check"], []).append(r)

    def kind_of(project):
        if project.startswith("(") and project.endswith(")"):
            return "family"
        return kinds.get(project, "inventory")

    projects = sorted(matrix, key=lambda p: (KIND_ORDER.get(kind_of(p), 9), p.lower()))
    checks = sorted({r["check"] for r in rows},
                    key=lambda c: (CHECK_ORDER.index(c) if c in CHECK_ORDER else len(CHECK_ORDER), c))

    counts = {s: 0 for s in SEVERITIES}
    for r in rows:
        counts[r["severity"]] += 1
    if counts["FAIL"]:
        status, status_class = "NOT CLEAN", "fail"
    elif counts["SKIP"] or counts["REVIEW"]:
        status, status_class = "INCOMPLETE", "review"
    elif counts["WARN"]:
        status, status_class = "WARNINGS", "warn"
    else:
        status, status_class = "CLEAN", "pass"

    now = datetime.datetime.now(datetime.timezone.utc)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    generated_wib = (now + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M WIB")

    kind_label = {"family": "family-wide", "android-app": "app",
                  "web-site": "site", "inventory": "inventory"}

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>patuh - all checks, all projects</title>
<style>
:root { color-scheme: light; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; color: #1a1a1a; background: #fafafa; }
header { padding: 20px 24px 8px; }
h1 { font-size: 1.35rem; margin: 0 0 4px; }
.meta { color: #555; font-size: 0.85rem; }
.status { display: inline-block; padding: 2px 10px; border-radius: 12px; font-weight: 600; color: #fff; }
.counts { margin: 8px 0 0; font-size: 0.85rem; color: #444; }
.counts b { display: inline-block; min-width: 14px; text-align: center; padding: 1px 5px; border-radius: 4px; color: #fff; font-size: 0.78rem; }
.pass { background: #2e7d32; } .fail { background: #c62828; } .warn { background: #ef6c00; }
.review { background: #6a1b9a; } .skip { background: #546e7a; } .info { background: #1565c0; }
.wrap { overflow: auto; padding: 8px 24px 24px; max-height: calc(100vh - 16px); }
.chips { display: none; }
#detail { display: none; }
@media (max-width: 700px) {
  header { padding: 10px 12px 4px; }
  h1 { font-size: 1.1rem; }
  .meta { font-size: 0.75rem; }
  html, body { height: 100%; overflow: hidden; }
  body { height: 100vh; height: 100dvh; display: flex; flex-direction: column; }
  header, .chips, #detail { flex: none; }
  header > .meta { display: none; }
  .wrap { flex: 1 1 auto; min-height: 0; max-height: none; padding: 0; -webkit-overflow-scrolling: touch; }
  section, footer { display: none; }
  table { font-size: 0.75rem; }
  thead th.check { height: 105px; }
  thead th.check span { font-size: 0.7rem; padding: 4px 0; }
  td.proj, th.proj { padding: 2px 6px; max-width: 34vw; overflow: hidden; text-overflow: ellipsis; border-right: 2px solid #b0bec5; }
  td.cell { width: 22px; height: 28px; }
  td.cell span { width: 20px; height: 20px; line-height: 20px; }
  tr.kind td { font-size: 0.68rem; padding: 3px 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px 8px; padding: 4px 12px; font-size: 0.72rem; color: #444; }
  .chips b { padding: 0 5px; border-radius: 3px; color: #fff; }
  section { padding: 0 12px 16px; }
  footer { padding: 0 12px 24px; }
  #detail { display: block; position: static; height: 20vh; max-height: 20vh; overflow: auto; background: #fff; border-top: 3px solid #455a64; padding: 8px 12px; font-size: 0.85rem; z-index: 10; box-shadow: 0 -2px 8px rgba(0,0,0,.2); }
  #detail .hint { color: #666; }
  #detail .sev { display: inline-block; padding: 0 6px; border-radius: 3px; color: #fff; font-size: 0.72rem; font-weight: 700; margin-right: 6px; }
  #detail p { margin: 4px 0; }
  td.cell:not(.na) { cursor: pointer; }
  td.cell.sel { outline: 3px solid #1a1a1a; outline-offset: -3px; }
}
table { border-collapse: collapse; font-size: 0.8rem; background: #fff; }
th, td { border: 1px solid #e0e0e0; padding: 0; }
thead th { position: sticky; top: 0; background: #fff; z-index: 2; }
thead th.check { vertical-align: bottom; height: 150px; }
thead th.check span { writing-mode: vertical-rl; transform: rotate(180deg); display: inline-block; padding: 6px 2px; font-weight: 500; white-space: nowrap; }
td.proj, th.proj { text-align: left; padding: 3px 10px; white-space: nowrap; position: sticky; left: 0; background: #fff; z-index: 1; font-weight: 500; }
thead th.proj { z-index: 3; }
td.cell { width: 26px; height: 24px; text-align: center; }
td.cell span { display: inline-block; width: 18px; height: 18px; line-height: 18px; border-radius: 3px; color: #fff; font-size: 0.7rem; font-weight: 700; }
td.na { background: #f5f5f5; }
td.cell { position: relative; }
td.cell.hit::after { content: ""; position: absolute; inset: 0; border: 2px solid #f9a825; pointer-events: none; }
td.cell.cur::after { border-width: 3px; border-color: #ad1457; }
[data-sev] { cursor: pointer; }
[data-sev]:hover { text-decoration: underline; }
.legend li.on, .chips span.on, .counts span.on { outline: 2px solid #1a1a1a; outline-offset: 1px; border-radius: 4px; font-weight: 700; }
#jump { display: none; align-items: center; gap: 8px; font-size: 0.85rem; background: #fff; color: #1a1a1a; }
#jump.show { display: flex; }
#jump #jump-label { font-weight: 600; }
#jump button { min-width: 44px; min-height: 38px; font-size: 1rem; border: 1px solid #90a4ae; border-radius: 4px; background: #eceff1; cursor: pointer; }
@media (min-width: 701px) {
  #jump.show { position: fixed; right: 16px; bottom: 16px; padding: 8px 12px; border: 1px solid #90a4ae; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,.25); z-index: 20; }
}
@media (max-width: 700px) {
  #jump.show { flex: none; padding: 4px 12px; border-top: 1px solid #b0bec5; }
}
tr.kind td { background: #eceff1; text-align: left; padding: 4px 10px; font-size: 0.75rem; font-weight: 600; color: #455a64; letter-spacing: 0.04em; text-transform: uppercase; position: sticky; left: 0; }
section { padding: 0 24px 24px; max-width: 1000px; }
h2 { font-size: 1.05rem; margin: 20px 0 8px; }
details { margin: 4px 0; }
summary { cursor: pointer; font-size: 0.9rem; }
ul.findings { margin: 6px 0 10px 18px; padding: 0; font-size: 0.85rem; }
ul.findings li { margin: 3px 0; list-style: none; }
ul.findings .sev { display: inline-block; min-width: 52px; padding: 0 6px; border-radius: 3px; color: #fff; font-size: 0.72rem; font-weight: 700; text-align: center; margin-right: 6px; }
ul.findings code { background: #eee; padding: 0 4px; border-radius: 3px; font-size: 0.78rem; }
.legend { font-size: 0.82rem; color: #444; }
.legend li { margin: 2px 0; }
footer { padding: 0 24px 32px; color: #666; font-size: 0.8rem; }
a { color: #1565c0; }
</style>
</head>
<body>
<header>
<h1>patuh &mdash; all checks, all projects</h1>
<div class="meta">Cross-project consistency report for
<a href="https://github.com/irvan-putra/patuh">irvan-putra/patuh</a>.
Generated """ + esc(generated) + " (" + esc(generated_wib) + """).</div>
<div class="counts">Status: <span class="status """ + status_class + '">' + status + "</span> &nbsp; ")
    for sev in SEVERITIES:
        if counts[sev]:
            parts.append('<span data-sev="%s" role="button" tabindex="0" title="jump to %s cells"><b class="%s">%d</b> %s &nbsp; </span>'
                         % (sev, sev.lower(), SEV_CLASS[sev], counts[sev], sev.lower()))
    parts.append("""</div>
</header>
<div class="chips"><span data-sev="FAIL" role="button" tabindex="0"><b class="fail">F</b> fail</span><span data-sev="WARN" role="button" tabindex="0"><b class="warn">W</b> warn</span><span data-sev="REVIEW" role="button" tabindex="0"><b class="review">R</b> review</span><span data-sev="SKIP" role="button" tabindex="0"><b class="skip">S</b> skip</span><span data-sev="INFO" role="button" tabindex="0"><b class="info">i</b> info</span><span data-sev="PASS" role="button" tabindex="0"><b class="pass">\u2713</b> pass</span><span>tap a label to find its cells</span></div>
<div class="wrap">
<table>
<thead><tr><th class="proj">project</th>""")
    for c in checks:
        parts.append('<th class="check"><span>%s</span></th>' % esc(c))
    parts.append("</tr></thead>\n<tbody>")

    last_kind = None
    for proj in projects:
        k = kind_of(proj)
        if k != last_kind:
            parts.append('<tr class="kind"><td colspan="%d">%s</td></tr>' % (len(checks) + 1, esc(kind_label.get(k, k))))
            last_kind = k
        parts.append('<tr><td class="proj"><a href="https://github.com/irvan-putra/%s">%s</a></td>' % (esc(proj), esc(proj)))
        pm = matrix[proj]
        for c in checks:
            if c not in pm:
                parts.append('<td class="cell na"></td>')
                continue
            sev = worst(pm[c])
            tip = "\n".join("%s: %s" % (r["severity"], r["message"]) for r in pm[c])
            parts.append('<td class="cell" title="%s" data-p="%s" data-c="%s" data-s="%s"><span class="%s">%s</span></td>'
                         % (esc(tip), esc(proj), esc(c), esc(sev), SEV_CLASS[sev], esc(SEV_SHORT[sev])))
        parts.append("</tr>")
    parts.append("""</tbody>
</table>
</div>
<section>
<h2>Legend</h2>
<p class="legend">Click a severity to highlight its cells and jump to the
first one; the bar that appears steps through the rest and Esc clears.
Tap the same severity again to step to the next cell.</p>
<ul class="legend">""")
    for sev in SEVERITIES:
        parts.append('<li data-sev="%s" role="button" tabindex="0"><b class="%s" style="padding:0 6px;border-radius:3px;color:#fff">%s</b> %s</li>'
                     % (sev, SEV_CLASS[sev], sev, esc(SEV_MEANING[sev])))
    parts.append("""</ul>
<p class="legend">A blank cell means the check does not apply to that project.
CLEAN only means every check that ran passed: patuh compares structure,
metadata and pixels. It cannot judge that art looks right, that an app works
or that wording is good - those stay REVIEW items for a human.</p>
</section>
<section>
<h2>Findings that are not a pass</h2>""")
    any_listed = False
    for proj in projects:
        bad = [r for r in rows if r["project"] == proj and r["severity"] != "PASS"]
        if not bad:
            continue
        any_listed = True
        worst_sev = worst(bad)
        parts.append('<details%s><summary><b class="%s" style="padding:0 6px;border-radius:3px;color:#fff">%s</b> %s &mdash; %d item%s</summary>'
                     % (" open" if worst_sev in ("FAIL", "WARN") else "",
                        SEV_CLASS[worst_sev], worst_sev, esc(proj), len(bad), "s" if len(bad) != 1 else ""))
        parts.append('<ul class="findings">')
        for r in sorted(bad, key=lambda r: SEVERITIES.index(r["severity"])):
            parts.append('<li><span class="sev %s">%s</span><code>%s</code> %s</li>'
                         % (SEV_CLASS[r["severity"]], r["severity"], esc(r["check"]), esc(r["message"])))
        parts.append("</ul></details>")
    if not any_listed:
        parts.append("<p>None - every check that ran, passed.</p>")
    parts.append("""</section>
<footer>
<p>Generated by <a href="https://github.com/irvan-putra/patuh">patuh</a>'s
Pages workflow from the machine-readable report (<code>patuh.py --json</code>).
patuh reports; it never modifies a project. Re-runs weekly after the Monday
audit and on every push to this repo.</p>
</footer>
<div id="jump"><span id="jump-label"></span>
<button type="button" id="jump-prev" aria-label="previous matching cell">&#9664;</button>
<button type="button" id="jump-next" aria-label="next matching cell">&#9654;</button>
<button type="button" id="jump-clear" aria-label="clear highlight">&#10005;</button>
</div>
<div id="detail"><span class="hint">Tap a cell to see the check and its findings.</span></div>
<script>
(function () {
  var d = document.getElementById("detail"), sel = null;
  var cls = {FAIL:"fail",WARN:"warn",REVIEW:"review",SKIP:"skip",INFO:"info",PASS:"pass"};
  function showCell(td) {
    if (sel) sel.classList.remove("sel");
    sel = td; td.classList.add("sel");
    d.textContent = "";
    var h = document.createElement("p");
    var b = document.createElement("b");
    b.textContent = td.dataset.p + " \u00b7 " + td.dataset.c;
    h.appendChild(b); d.appendChild(h);
    (td.getAttribute("title") || "").split("\\n").forEach(function (line) {
      var i = line.indexOf(": "), p = document.createElement("p");
      var sev = i > 0 ? line.slice(0, i) : "", sp = document.createElement("span");
      sp.className = "sev " + (cls[sev] || "skip"); sp.textContent = sev;
      p.appendChild(sp); p.appendChild(document.createTextNode(i > 0 ? line.slice(i + 2) : line));
      d.appendChild(p);
    });
  }
  var jump = document.getElementById("jump"), jl = document.getElementById("jump-label");
  var hits = [], hi = -1, hsev = null;
  function label() {
    jl.textContent = hsev + (hits.length ? " cell " + (hi + 1) + " of " + hits.length : ": no cells");
  }
  function markLegend() {
    var on = hits.length > 0;
    document.querySelectorAll("[data-sev]").forEach(function (el) {
      el.classList.toggle("on", on && el.getAttribute("data-sev") === hsev);
    });
  }
  function step(dir) {
    if (!hits.length) { label(); return; }
    hi = (hi + dir + hits.length) % hits.length;
    hits.forEach(function (td, i) { td.classList.toggle("cur", i === hi); });
    var td = hits[hi];
    td.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    showCell(td);
    label();
  }
  function clearJump() {
    hits.forEach(function (td) { td.classList.remove("hit", "cur"); });
    hits = []; hi = -1; hsev = null;
    jump.classList.remove("show");
    markLegend();
  }
  function focusSev(sev) {
    if (hsev === sev && hits.length) { step(1); return; }
    clearJump();
    hsev = sev;
    hits = [].slice.call(document.querySelectorAll('td.cell[data-s="' + sev + '"]'));
    hits.forEach(function (td) { td.classList.add("hit"); });
    jump.classList.add("show");
    markLegend();
    step(1);
  }
  document.addEventListener("click", function (e) {
    var td = e.target.closest ? e.target.closest("td.cell[data-p]") : null;
    if (td) {
      showCell(td);
      var i = hits.indexOf(td);
      if (i >= 0) {
        hi = i;
        hits.forEach(function (t, j) { t.classList.toggle("cur", j === i); });
        label();
      }
      return;
    }
    var lg = e.target.closest ? e.target.closest("[data-sev]") : null;
    if (lg) { e.preventDefault(); focusSev(lg.getAttribute("data-sev")); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { clearJump(); return; }
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-sev]")) {
      e.preventDefault();
      focusSev(e.target.getAttribute("data-sev"));
    }
  });
  document.getElementById("jump-prev").addEventListener("click", function () { step(-1); });
  document.getElementById("jump-next").addEventListener("click", function () { step(1); });
  document.getElementById("jump-clear").addEventListener("click", clearJump);
})();
</script>
<p class="ai-note" style="text-align:center;font:12px/1.4 system-ui,sans-serif;opacity:.7;margin:24px 12px">Built with AI assistance (Instinct and others). Not everything has been reviewed by Irvan.</p>
</body>
</html>
""")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print("wrote %s (%d projects, %d checks, status %s)" % (out_path, len(projects), len(checks), status))


if __name__ == "__main__":
    main()
