#!/usr/bin/env python3
"""patuh - cross-project consistency checker for irvan-putra's app family.

Catches drift from the conventions Irvan approved (conventions.json) and from
each project's approved baseline (projects.json, or a repo's own patuh.json).
It reports; it never modifies a project.

What it CAN check (structural, from source metadata and image pixels):
  version alignment across build config, release tag, APK filename, gallery
  card and the icon's version badge; com.vanipy.* package IDs; declared
  Android permissions vs baseline; launcher label style; launcher-icon
  geometry of the shared family (rounded corner, full-width bottom strip,
  badge text equals the version, art inside the round-mask safe circle);
  release artifacts and their sha256 sidecars; the gallery catalog agreeing
  with the releases; repo hygiene (public, LICENSE, README, commit author).

What it CANNOT check: that art looks right, that an app works, that wording
is good, or that an adaptive/custom icon renders correctly on a launcher.
Those stay REVIEW items for a human with screenshots. Pixel checks compare
geometry and text, not taste.

Exit code: 0 = no FAIL findings, 1 = at least one FAIL, 2 = usage error.
CLEAN in the report means every check that ran passed; skipped checks are
listed, so a clean run with skips says so.

Requirements: Python 3.8+, git. Icon pixel checks need Pillow exactly
12.3.0 and the pinned DejaVu Sans Bold (fonts/, sha256-checked on load);
without them those checks report SKIP, not pass.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
GH_API = "https://api.github.com"
GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


# ---------------------------------------------------------------- findings
FAIL, WARN, REVIEW, SKIP, PASS, INFO = "FAIL", "WARN", "REVIEW", "SKIP", "PASS", "INFO"


class Report:
    def __init__(self):
        self.rows = []  # (project, severity, check_id, message)

    def add(self, project, severity, check_id, message):
        self.rows.append((project, severity, check_id, message))

    def counts(self):
        c = Counter(s for _, s, _, _ in self.rows)
        return c

    def text(self):
        out = []
        cur = None
        for proj, sev, cid, msg in self.rows:
            if proj != cur:
                out.append("")
                out.append("== %s ==" % proj)
                cur = proj
            out.append("%-6s %-22s %s" % (sev, cid, msg))
        c = self.counts()
        out.append("")
        out.append("summary: %d pass, %d info, %d skip, %d review, %d warn, %d fail"
                   % (c[PASS], c[INFO], c[SKIP], c[REVIEW], c[WARN], c[FAIL]))
        out.append("NOT CLEAN" if c[FAIL] else "INCOMPLETE" if c[SKIP] or c[REVIEW] else "WARNINGS" if c[WARN] else "CLEAN")
        if c[SKIP] or c[REVIEW]:
            out.append("(skips/reviews above mean parts were not verified)")
        return "\n".join(out)


# ---------------------------------------------------------------- helpers
def api_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "patuh",
                                               "Accept": "application/vnd.github+json"})
    if GH_TOKEN:
        req.add_header("Authorization", "Bearer " + GH_TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "patuh"})
    if GH_TOKEN and "api.github.com" in url:
        req.add_header("Authorization", "Bearer " + GH_TOKEN)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def ensure_clone(owner, repo, workdir, offline, cache_repo=None):
    dest = os.path.join(workdir, repo)
    if os.path.isdir(os.path.join(dest, ".git")):
        return dest
    if offline and cache_repo:
        return cache_repo
    subprocess.run(["git", "clone", "-q", "--depth", "1",
                    "https://github.com/%s/%s" % (owner, repo), dest], check=True)
    return dest


def find_file(root, *candidates):
    for rel in candidates:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    return None


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def detect_license(clone, license_root="."):
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        p = os.path.join(clone, license_root, name)
        if os.path.isfile(p):
            head = read(p)[:400]
            if "GNU AFFERO GENERAL PUBLIC LICENSE" in head:
                return "AGPL-3.0"
            if "GNU GENERAL PUBLIC LICENSE" in head:
                return "GPL-3.0"
            if "MIT License" in head or "Permission is hereby granted, free of charge" in head:
                return "MIT"
            if "Apache License" in head:
                return "Apache-2.0"
            return "other"
    return None


def parse_gradle(path):
    """applicationId and versionName from a build.gradle(.kts)."""
    text = read(path)
    app_id = None
    m = re.search(r"applicationId\s*=?\s*\(?\s*[\"']([^\"']+)[\"']", text)
    if m:
        app_id = m.group(1)
    version = None
    m = re.search(r"versionName\s*=?\s*\(?\s*[\"']([0-9]+\.[0-9]+\.[0-9]+)[\"']", text)
    if m:
        version = m.group(1)
    else:  # versionName((project.findProperty(...) ?: '1.2.3') as String) style
        m = re.search(r"versionName.*?\?:\s*[\"']([0-9]+\.[0-9]+\.[0-9]+)[\"']", text)
        if m:
            version = m.group(1) + " (default)"
        else:  # versionName = someProperty, defined earlier in the same file
            m = re.search(r"versionName\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", text)
            if m:
                ident = re.escape(m.group(1))
                m2 = re.search(r"(?:val\s+|def\s+)?" + ident + r"\s*=\s*[\"']([0-9]+\.[0-9]+\.[0-9]+)[\"']", text)
                if m2:
                    version = m2.group(1)
    return app_id, version


def manifest_facts(path):
    text = read(path)
    perms = sorted(set(re.findall(r"uses-permission[^>]*android:name=\"([^\"]+)\"", text)))
    m = re.search(r"android:label=\"([^\"]+)\"", text)
    label = m.group(1) if m else None
    m = re.search(r"android:icon=\"([^\"]+)\"", text)
    icon = m.group(1) if m else None
    return perms, label, icon


def resolve_string(clone, module, ref):
    if not ref or not ref.startswith("@string/"):
        return ref
    name = ref.split("/", 1)[1]
    vals = os.path.join(clone, module, "src", "main", "res", "values")
    if os.path.isdir(vals):
        for fn in os.listdir(vals):
            if fn.endswith(".xml"):
                m = re.search(r"<string name=\"%s\">([^<]+)</string>" % re.escape(name),
                              read(os.path.join(vals, fn)))
                if m:
                    return m.group(1)
    return ref


# ---------------------------------------------------------------- icon pixels
_PIL = None


def pil():
    global _PIL
    if _PIL is None:
        try:
            import PIL
            from PIL import Image, ImageDraw, ImageFont
            if PIL.__version__ != "12.3.0":
                _PIL = ("bad-version", PIL.__version__)
            else:
                _PIL = ("ok", Image, ImageDraw, ImageFont)
        except ImportError:
            _PIL = ("missing", None)
    return _PIL


def _cdist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


_BADGE_CHARS = "0123456789."
_glyph_cache = {}


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _candidate_glyph(ch, size, conv, font_path):
    """One badge character rendered through the family's exact pipeline."""
    key = (ch, size)
    if key in _glyph_cache:
        return _glyph_cache[key]
    _, Image, ImageDraw, ImageFont = pil()
    big = 768
    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    f = ImageFont.truetype(font_path, int(big * conv["text_size"]))
    d.text((big / 2, (int(big * conv["strip_top"]) + big) / 2), ch, font=f, fill=255, anchor="mm")
    m = m.resize((size, size), Image.LANCZOS)
    mm = m.load()
    pts = set((x, y) for y in range(size) for x in range(size) if mm[x, y] > 100)
    _glyph_cache[key] = pts
    return pts


def _iou_centered(a, b):
    """IoU with b kept at its rendered size and its bbox center aligned to a's."""
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    dx = int(round((ax0 + ax1) / 2 - (bx0 + bx1) / 2))
    dy = int(round((ay0 + ay1) / 2 - (by0 + by1) / 2))
    bb = set((x + dx, y + dy) for (x, y) in b)
    inter = len(a & bb)
    union = len(a | bb)
    return inter / union if union else 0


def read_badge(tmask, size, conv, font_path):
    """Segment the badge text mask into glyphs and classify each against the
    pinned font's digits and period. Returns (string, min glyph IoU), or
    (None, confidence) when segmentation found no glyphs. Deterministic:
    same pixels in, same reading out."""
    cols = {}
    for (x, y) in tmask:
        cols.setdefault(x, []).append(y)
    if not cols:
        return None, 0.0
    xs = sorted(cols)
    groups = [[xs[0]]]
    for x in xs[1:]:
        if x - groups[-1][-1] <= 1:
            groups[-1].append(x)
        else:
            groups.append([x])
    out = []
    worst = 1.0
    for g in groups:
        pts = set((x, y) for x in g for y in cols[x])
        scored = [(c, _iou_centered(pts, _candidate_glyph(c, size, conv, font_path)))
                  for c in _BADGE_CHARS]
        best, score = max(scored, key=lambda cs: cs[1])
        out.append(best)
        worst = min(worst, score)
    if worst < 0.4:
        return None, worst
    return "".join(out), worst


def icon_pixel_checks(img, version, conv, font_path):
    """The family geometry suite. Returns list of (ok, check_id, message).

    Calibrated 2026-11-17 against all eleven approved family icons plus the
    rejected Tumbuh 0.1.0 icon (which this suite fails, as intended).
    """
    status = pil()
    if status[0] != "ok":
        return [(None, "icon-pixels", "SKIP: Pillow 12.3.0 not available")]
    _, Image, ImageDraw, ImageFont = status
    strip_top = conv["strip_top"]
    tol = conv["strip_top_tolerance"]
    safe_r = conv["safe_radius"]
    text_size = conv["text_size"]
    im = img.convert("RGBA")
    w, h = im.size
    px = im.load()
    out = []

    # rounded corner: measure first opaque row down the x=1 edge
    y = 0
    while y < h and px[1, y][3] < 10:
        y += 1
    r = y / h
    out.append((0.08 <= r <= 0.25 and px[1, 1][3] < 10,
                "icon-corner", "rounded corner radius %.3f (family ~0.15 at this edge)" % r))

    # strip top: strongest full-width row transition in 0.65..0.85 of height
    best = None
    for yy in range(int(h * 0.65), int(h * 0.85)):
        diff = sum(1 for x in range(2, w - 2, 2) if px[x, yy][:3] != px[x, yy - 1][:3])
        if best is None or diff > best[1]:
            best = (yy, diff)
    cols = len(range(2, w - 2, 2))
    if not best or best[1] / cols < 0.8:
        out.append((False, "icon-strip", "no full-width strip edge found - not the family badge"))
        return out
    y0 = best[0] + 1
    out.append((abs(y0 / h - strip_top) <= tol, "icon-strip-top",
                "strip top at %.3f of height (want %.2f +/- %.2f)" % (y0 / h, strip_top, tol)))
    ym = (y0 + h) // 2
    dom = Counter(px[x, yy][:3] for yy in range(y0 + 3, h - 2)
                  for x in range(0, w, 2)).most_common(1)[0][0]
    width_ok = True
    for yy in (y0 + 3, ym):
        cov = sum(1 for x in range(w) if px[x, yy][3] > 10) / w
        if cov < 0.95:
            out.append((False, "icon-strip-width", "strip row %d only %.0f%% opaque" % (yy, cov * 100)))
            width_ok = False
            break
    if width_ok:
        out.append((True, "icon-strip-width", "strip spans full width"))

    # badge text pixels: far from the strip color, clustered near one text color
    far = Counter()
    for yy in range(y0 + 3, h - 2):
        for x in range(0, w, 2):
            p = px[x, yy]
            if p[3] > 200 and _cdist(p[:3], dom) > 80:
                far[(p[0] // 48, p[1] // 48, p[2] // 48)] += 1
    if not far:
        out.append((False, "icon-badge-text", "no badge text pixels found"))
        return out
    b = far.most_common(1)[0][0]
    tc = (b[0] * 48 + 24, b[1] * 48 + 24, b[2] * 48 + 24)
    band = w * (h - y0)
    tmask = set()
    for yy in range(y0 + 3, h - 2):
        for x in range(w):
            p = px[x, yy]
            if p[3] > 200 and _cdist(p[:3], dom) > 80 and _cdist(p[:3], tc) < 100:
                tmask.add((x, yy))
    frac = len(tmask) / band
    out.append((0.002 <= frac <= 0.40, "icon-badge-text", "badge text covers %.1f%% of strip" % (frac * 100)))

    if version and w >= 144:
        # read the badge characters with the pinned font and compare to the version
        if not os.path.isfile(font_path):
            out.append((None, "icon-badge-version", "SKIP: pinned font missing at %s" % font_path))
        elif hashlib.sha256(open(font_path, "rb").read()).hexdigest() != conv["font_sha256"]:
            out.append((False, "icon-badge-version", "pinned font sha256 mismatch"))
        else:
            read_str, confidence = read_badge(tmask, w, conv, font_path)
            if read_str is None:
                out.append((None, "icon-badge-version",
                            "SKIP: badge text unreadable at this size (confidence %.2f)" % confidence))
            elif read_str == version:
                out.append((True, "icon-badge-version",
                            "badge reads %s (character confidence %.2f)" % (version, confidence)))
            else:
                out.append((False, "icon-badge-version",
                            "badge reads %r but version is %s" % (read_str, version)))

    # art above the strip stays inside the round-mask safe circle
    bg = Counter(px[x, yy][:3] for yy in range(0, y0, 3)
                 for x in range(0, w, 3)).most_common(1)[0][0]
    cx, cy = w / 2, h / 2
    rr = (safe_r * w) ** 2
    bad = 0
    for yy in range(0, y0):
        for x in range(w):
            p = px[x, yy]
            if p[3] > 8 and _cdist(p[:3], bg) > 40 and (x - cx) ** 2 + (yy - cy) ** 2 > rr:
                bad += 1
    out.append((bad == 0, "icon-safe-circle",
                "%d art pixels leave the round-mask safe circle" % bad))
    return out


# ---------------------------------------------------------------- check groups
def check_repo_hygiene(rep, proj, clone, conv, offline):
    app = proj["app"]
    if not find_file(clone, "README.md", "README"):
        rep.add(app, FAIL, "readme", "no README")
    else:
        rep.add(app, PASS, "readme", "README present")
    lic = detect_license(clone, proj.get("license_root", "."))
    base = proj.get("license_baseline")
    if lic == base:
        rep.add(app, PASS, "license", "license %s (as baselined)" % (lic or "absent"))
    else:
        rep.add(app, WARN, "license", "license now %s, baseline was %s - relicensing needs his ok"
                % (lic or "absent", base or "absent"))
    try:
        out = subprocess.run(["git", "-C", clone, "log", "-1", "--format=%an|%ae"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        out = ""
    want = conv["commit_author"]
    name, _, email = out.partition("|")
    if email == want["email"] and name in want.get("names", [want.get("name")]):
        rep.add(app, PASS, "commit-author", "last commit by %s <%s>" % (name, email))
    elif out.startswith("github-actions[bot]"):
        rep.add(app, PASS, "commit-author", "last commit by github-actions[bot] (deploy commit)")
    else:
        rep.add(app, WARN, "commit-author", "last commit by %s" % (out or "unknown"))


def check_naming(rep, proj, conv):
    app = proj["app"]
    rule = conv["naming"]
    for label, name in (("app", app), ("repo", proj["repo"])):
        low = name.lower()
        bad = [c for c in rule["forbid_chars"] if c in low]
        if name[0].lower() in rule["forbid_first_chars"]:
            bad.append("leading " + name[0])
        if bad:
            rep.add(app, WARN, "naming", "%s name %r contains %s (rule is for new names)"
                    % (label, name, ", ".join(bad)))
        else:
            rep.add(app, PASS, "naming", "%s name %r fits the no-L/no-R rule" % (label, name))


def check_module(rep, proj, clone, conv, module_path, package_expected, label_expected,
                 perms_baseline, check_id_prefix="", lenient=False):
    app = proj["app"]
    gradle = None
    for fn in ("build.gradle", "build.gradle.kts"):
        p = os.path.join(clone, module_path, fn)
        if os.path.isfile(p):
            gradle = p
            break
    cid = check_id_prefix
    if not gradle:
        rep.add(app, FAIL, cid + "module", "no build.gradle in %s" % module_path)
        return
    app_id, version = parse_gradle(gradle)
    if not app_id:
        rep.add(app, FAIL, cid + "package", "no applicationId found in %s" % os.path.basename(gradle))
    elif app_id != package_expected:
        rep.add(app, FAIL, cid + "package",
                "applicationId is %s, expected %s - never rename silently; installed identity"
                % (app_id, package_expected))
    else:
        rep.add(app, PASS, cid + "package", "applicationId %s" % app_id)
    if not app_id.startswith(conv["android"]["package_prefix"]):
        rep.add(app, FAIL, cid + "namespace", "%s is outside com.vanipy.*" % app_id)
    if version:
        clean = version.replace(" (default)", "")
        if re.match(conv["android"]["version_regex"], clean):
            rep.add(app, PASS, cid + "version", "versionName %s" % version)
        elif lenient:
            rep.add(app, INFO, cid + "version", "versionName %s (extra module, not three numbers)" % version)
        else:
            rep.add(app, FAIL, cid + "version", "versionName %s is not three numbers" % version)
    else:
        rep.add(app, INFO if lenient else WARN, cid + "version", "versionName not readable from build file")
    man = os.path.join(clone, module_path, "src", "main", "AndroidManifest.xml")
    if not os.path.isfile(man):
        rep.add(app, FAIL, cid + "manifest", "no AndroidManifest.xml in %s" % module_path)
        return version
    perms, label, icon_ref = manifest_facts(man)
    if perms_baseline is not None:
        if perms == sorted(perms_baseline):
            rep.add(app, PASS, cid + "permissions",
                    "%d permissions match baseline" % len(perms) if perms else "no permissions, matches baseline")
        else:
            added = [p for p in perms if p not in perms_baseline]
            gone = [p for p in perms_baseline if p not in perms]
            rep.add(app, FAIL, cid + "permissions", "permission drift: +%s -%s" % (added, gone))
    if label_expected is not None:
        actual = resolve_string(clone, module_path, label)
        if actual is None:
            rep.add(app, WARN, cid + "label", "no android:label found")
        elif actual != label_expected:
            rep.add(app, WARN, cid + "label",
                    "launcher label %r, expected %r" % (actual, label_expected))
        else:
            rep.add(app, PASS, cid + "label", "launcher label %r" % actual)
    return version


def check_icon(rep, proj, clone, conv, version):
    app = proj["app"]
    mode = proj.get("icon_mode", "family")
    module = proj["module"]
    resdir = os.path.join(clone, module, "src", "main", "res")
    note = proj.get("icon_note")
    if note:
        rep.add(app, INFO, "icon-note", note)
    if mode == "custom":
        rep.add(app, REVIEW, "icon-custom",
                "custom icon: family geometry not applicable - visual review on change")
        return
    if mode == "adaptive":
        rep.add(app, REVIEW, "icon-adaptive",
                "adaptive icon: family style not machine-verifiable - visual review needed")
        return
    # family mode
    anydpi = os.path.join(resdir, "mipmap-anydpi-v26")
    if os.path.isdir(anydpi):
        # collect available resource names per kind by scanning res/ once
        available = {"mipmap": set(), "drawable": set(), "color": set()}
        for d in os.listdir(resdir):
            full = os.path.join(resdir, d)
            if not os.path.isdir(full):
                continue
            for kind in ("mipmap", "drawable"):
                if d.startswith(kind):
                    for f in os.listdir(full):
                        available[kind].add(os.path.splitext(f)[0])
        values_dir = os.path.join(resdir, "values")
        if os.path.isdir(values_dir):
            for vf in os.listdir(values_dir):
                if vf.endswith(".xml"):
                    available["color"] |= set(re.findall(r'<color name="([^"]+)"',
                                                         read(os.path.join(values_dir, vf))))
        for fn in os.listdir(anydpi):
            text = read(os.path.join(anydpi, fn))
            missing = []
            for kind, name in re.findall(r"@(mipmap|drawable|color)/([A-Za-z0-9_]+)", text):
                if name not in available.get(kind, set()):
                    missing.append("@%s/%s" % (kind, name))
            if missing:
                rep.add(app, FAIL, "icon-adaptive-refs", "%s references missing %s" % (fn, missing))
            else:
                rep.add(app, WARN, "icon-adaptive-refs",
                        "%s: adaptive icon present; Android 8+ uses it, not the raster set - "
                        "references exist but family look needs visual check" % fn)
    # Follow an actual manifest drawable reference, rather than assuming mipmaps.
    manifest = os.path.join(clone, module, "src", "main", "AndroidManifest.xml")
    _, _, icon_ref = manifest_facts(manifest)
    drawable = re.fullmatch(r"@drawable/([A-Za-z0-9_]+)", icon_ref or "")
    if drawable:
        name = drawable.group(1)
        biggest = os.path.join(resdir, "drawable", name + ".png")
        vector = os.path.join(resdir, "drawable", name + ".xml")
        if not os.path.isfile(biggest) and os.path.isfile(vector):
            rep.add(app, REVIEW, "icon-resource",
                    "manifest icon is a vector drawable (@drawable/%s) - family geometry not "
                    "machine-verifiable, visual review on change" % name)
            return
        if not os.path.isfile(biggest):
            rep.add(app, FAIL, "icon-resource", "manifest drawable icon missing: " + str(icon_ref))
            return
        rep.add(app, INFO, "icon-resource", "manifest uses single drawable PNG; mipmap-density coverage is not applicable")
    else:
        densities = conv["icon_family"]["densities"]
        missing = [d for d in densities
                   if not os.path.isfile(os.path.join(resdir, "mipmap-" + d, "ic_launcher.png"))]
        if missing:
            rep.add(app, FAIL, "icon-densities", "missing ic_launcher.png for %s" % ", ".join(missing))
        else:
            rep.add(app, PASS, "icon-densities", "ic_launcher.png in all %d densities" % len(densities))
        biggest = os.path.join(resdir, "mipmap-xxxhdpi", "ic_launcher.png")
        if not os.path.isfile(biggest):
            return
    status = pil()
    if status[0] != "ok":
        rep.add(app, SKIP, "icon-pixels", "Pillow 12.3.0 not available - pixel checks skipped")
        return
    _, Image, _, _ = status
    clean_version = version.replace(" (default)", "") if version else None
    font_path = os.path.join(REPO_DIR, "fonts", "DejaVuSans-Bold.ttf")
    for ok, cid, msg in icon_pixel_checks(Image.open(biggest), clean_version,
                                          conv["icon_family"], font_path):
        rep.add(app, PASS if ok else (SKIP if ok is None else FAIL), cid, msg)


def find_checksum(assets, want_apk, want_sha):
    """Locate the published checksum for the APK. Two accepted formats:
    the per-asset sidecar `app-vX.Y.Z.apk.sha256` (hex, possibly followed by
    the filename) and a sha256sum-format `SHA256SUMS` file listing every
    asset. Returns (asset_name, sha_hex, format) or None."""
    if want_sha in assets:
        try:
            text = fetch_bytes(assets[want_sha]["browser_download_url"]).decode()
        except Exception:
            return None
        fields = text.split()
        if fields and re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
            return (want_sha, fields[0].lower(), "sidecar")
        return None
    if "SHA256SUMS" in assets:
        try:
            text = fetch_bytes(assets["SHA256SUMS"]["browser_download_url"]).decode()
        except Exception:
            return None
        for line in text.splitlines():
            m = re.match(r"([0-9a-fA-F]{64})\s+\*?(\S+)", line.strip())
            if m and m.group(2) == want_apk:
                return ("SHA256SUMS", m.group(1).lower(), "sha256sums")
        return None
    return None


def latest_release(owner, repo):
    rels = api_get("%s/repos/%s/%s/releases?per_page=5" % (GH_API, owner, repo))
    for r in rels:
        if not r.get("draft"):
            return r
    return None


def check_release(rep, proj, conv, gallery_card, verify_downloads, workdir):
    app = proj["app"]
    owner = conv["owner"]
    andr = conv["android"]
    try:
        rel = latest_release(owner, proj["repo"])
    except Exception as e:
        rep.add(app, SKIP, "release", "GitHub API error: %s" % e)
        return
    if not rel:
        rep.add(app, SKIP, "release", "no release yet")
        return None
    tag = rel["tag_name"]
    m = re.fullmatch(r"v([0-9]+\.[0-9]+\.[0-9]+)", tag)
    if not m:
        rep.add(app, FAIL, "release-tag", "tag %r is not vX.Y.Z" % tag)
        return rel
    version = m.group(1)
    rep.add(app, PASS, "release-tag", "latest release %s" % tag)
    want_apk = andr["apk_name_pattern"].format(app=app, version=version)
    want_sha = andr["sha256_sidecar"].format(app=app, version=version)
    assets = {a["name"]: a for a in rel.get("assets", [])}
    if want_apk in assets:
        rep.add(app, PASS, "release-apk-name", want_apk)
    elif assets:
        rep.add(app, FAIL, "release-apk-name", "assets %s; want %s" % (sorted(assets), want_apk))
    else:
        rep.add(app, FAIL, "release-apk-name", "release has no assets; want " + want_apk)
    sha_declared = None
    found = find_checksum(assets, want_apk, want_sha)
    if found:
        asset_name, sha_declared, fmt = found
        rep.add(app, PASS, "release-sha256-file", "checksum published as %s (%s)" % (asset_name, fmt))
    else:
        rep.add(app, FAIL, "release-sha256-file",
                "no checksum asset for %s (accepted: %s or a SHA256SUMS line)" % (want_apk, want_sha))
    if gallery_card is not None:
        cv = gallery_card.get("version")
        if cv == version:
            rep.add(app, PASS, "gallery-version", "gallery card matches release")
        else:
            rep.add(app, FAIL, "gallery-version",
                    "gallery says %s, latest release is %s - stale catalog?" % (cv, version))
        csha = (gallery_card.get("sha256") or "").lower()
        if sha_declared and csha:
            if csha == sha_declared.lower():
                rep.add(app, PASS, "gallery-sha256", "gallery checksum matches published checksum")
            else:
                rep.add(app, FAIL, "gallery-sha256", "gallery checksum != published checksum")
    if verify_downloads and want_apk in assets and sha_declared:
        data = fetch_bytes(assets[want_apk]["browser_download_url"])
        digest = hashlib.sha256(data).hexdigest()
        if digest == sha_declared.lower():
            rep.add(app, PASS, "release-download", "downloaded APK sha256 matches published checksum")
        else:
            rep.add(app, FAIL, "release-download", "downloaded APK sha256 MISMATCH")
        check_packaged_icon(rep, proj, conv, data, version)
    return rel


def check_packaged_icon(rep, proj, conv, apk_bytes, version):
    """Pixel-check the launcher icon that actually ships in the APK."""
    app = proj["app"]
    if proj.get("icon_mode", "family") != "family":
        return
    status = pil()
    if status[0] != "ok":
        rep.add(app, SKIP, "apk-icon", "Pillow 12.3.0 not available - packaged icon not checked")
        return
    _, Image, _, _ = status
    z = zipfile.ZipFile(io.BytesIO(apk_bytes))
    names = z.namelist()
    cand = [n for n in names if re.search(r"mipmap-xxxhdpi[^/]*/ic_launcher\.png$", n)]
    if not cand:
        cand = [n for n in names if re.search(r"mipmap-xxhdpi[^/]*/ic_launcher\.png$", n)]
    if not cand:
        # obfuscated resource paths: fall back to the largest square PNG
        squares = []
        for n in names:
            if n.endswith(".png"):
                try:
                    im = Image.open(io.BytesIO(z.read(n)))
                    if im.size[0] == im.size[1] and im.size[0] >= 144:
                        squares.append((im.size[0], n))
                except Exception:
                    pass
        if squares:
            # launcher icons come in density sizes; library art (e.g. the 860px
            # appcompat oversize background) is larger and is not the icon
            density_pref = [192, 432, 512, 144, 96, 72, 48]
            squares.sort(key=lambda sn: (density_pref.index(sn[0]) if sn[0] in density_pref else 50, -sn[0]))
            cand = [squares[0][1]]
            rep.add(app, INFO, "apk-icon", "resource paths obfuscated; checking %dpx square PNG %s"
                    % (squares[0][0], cand[0]))
    if not cand:
        rep.add(app, FAIL, "apk-icon", "no launcher icon found inside APK")
        return
    img = Image.open(io.BytesIO(z.read(cand[0])))
    font_path = os.path.join(REPO_DIR, "fonts", "DejaVuSans-Bold.ttf")
    for ok, cid, msg in icon_pixel_checks(img, version, conv["icon_family"], font_path):
        rep.add(app, PASS if ok else (SKIP if ok is None else FAIL), "apk-" + cid, msg)


def check_registry_coverage(rep, projects, repositories):
    registered = {p["repo"] for p in projects}
    current = {r["name"] for r in repositories}
    for name in sorted(current - registered):
        rep.add(name, FAIL, "registry-missing", "owner repository absent from registry")
    for name in sorted(registered - current):
        rep.add(name, REVIEW, "registry-stale", "registered repository not found in owner listing")
    if current <= registered:
        rep.add("(registry)", PASS, "registry-coverage", "%d owner repositories represented; presence is not qualification" % len(current))


def check_gallery_coverage(rep, projects, cards, apps_with_release=None):
    by_app = current_gallery_by_app(cards)
    for proj in projects:
        if proj.get("kind") != "android-app":
            continue  # the apps catalog only covers APKs, not websites
        if apps_with_release is not None and proj["app"] not in apps_with_release:
            # no published APK, so a missing card is not a defect
            continue
        if proj["app"] not in by_app:
            rep.add(proj["app"], FAIL, "gallery-card",
                    "app has a published release but no gallery card")


# ---------------------------------------------------------------- main
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    ap = argparse.ArgumentParser(description="cross-project consistency checker")
    ap.add_argument("--conventions", default=os.path.join(REPO_DIR, "conventions.json"))
    ap.add_argument("--registry", default=os.path.join(REPO_DIR, "projects.json"))
    ap.add_argument("--only", action="append", help="check only this app (repeatable)")
    ap.add_argument("--workdir", default=os.path.join(tempfile.gettempdir(), "patuh-clones"),
                    help="where to put clones")
    ap.add_argument("--apk", action="store_true",
                    help="also download release APKs: verify sha256 and the packaged icon")
    ap.add_argument("--apk-file",
                    help="verify a locally built, unpublished APK against the source: "
                         "packaged icon pixels must carry the family badge reading the "
                         "candidate versionName. Use between build and publish.")
    ap.add_argument("--apk-version",
                    help="candidate version for --apk-file when the checked-out source "
                         "predates the version stamp (stamp-at-release flows). "
                         "Default: versionName read from the source.")
    ap.add_argument("--offline", action="store_true",
                    help="skip GitHub API/release/gallery checks; source checks only")
    ap.add_argument("--json", help="write the machine-readable report here")
    args = ap.parse_args(argv)

    conv = load_json(args.conventions)
    projects = load_json(args.registry)["projects"]
    all_projects = projects[:]
    if args.only:
        projects = [p for p in projects if p["app"] in args.only or p["repo"] in args.only]
    if not projects:
        print("no projects selected", file=sys.stderr)
        return 2
    if args.apk_file:
        if len(projects) != 1:
            print("--apk-file needs exactly one project (--only)", file=sys.stderr)
            return 2
        if not os.path.isfile(args.apk_file):
            print("--apk-file not found: %s" % args.apk_file, file=sys.stderr)
            return 2

    rep = Report()
    cards = []
    apps_with_release = set()
    if not args.offline:
        try:
            repositories = []
            page = 1
            while True:
                batch = api_get(GH_API + "/users/%s/repos?type=owner&per_page=100&page=%d" % (conv["owner"], page))
                repositories.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            check_registry_coverage(rep, all_projects, repositories)
        except Exception as e:
            rep.add("(registry)", SKIP, "registry-coverage", "live owner inventory not verified: %s" % e)
    else:
        rep.add("(registry)", SKIP, "registry-coverage", "offline: current owner repositories not verified")
    if not args.offline:
        try:
            cards = gallery_cards(load_json_url(conv["gallery"]["apps_url"]))
            rep.add("(gallery)", PASS, "gallery-fetch", "catalog fetched, %d cards" % len(cards))
        except Exception as e:
            rep.add("(gallery)", SKIP, "gallery-fetch", "could not fetch catalog: %s" % e)
    by_app = current_gallery_by_app(cards)

    os.makedirs(args.workdir, exist_ok=True)
    for proj in projects:
        app = proj["app"]
        kind = proj.get("kind")
        if kind == "inventory":
            rep.add(app, REVIEW, "coverage", proj.get("coverage_note", "Inventory only; checks not qualified"))
            rep.add(app, INFO, "source-type", proj.get("source_type", "repository"))
            continue
        if kind not in ("android-app", "web-site"):
            rep.add(app, SKIP, "kind", "unknown kind %r" % kind)
            continue
        try:
            clone = ensure_clone(conv["owner"], proj["repo"], args.workdir, args.offline)
        except subprocess.CalledProcessError as e:
            rep.add(app, FAIL, "clone", "could not clone: %s" % e)
            continue
        # a repo's own patuh.json overrides the registry baseline
        local = {}
        lp = os.path.join(clone, "patuh.json")
        if os.path.isfile(lp):
            try:
                local = load_json(lp).get("patuh_overrides", {})
                rep.add(app, INFO, "patuh-json", "repo patuh.json overrides applied: %s"
                        % ", ".join(sorted(local)) or "none")
            except Exception as e:
                rep.add(app, WARN, "patuh-json", "repo patuh.json unreadable: %s" % e)
        merged = dict(proj)
        merged.update(local)

        check_repo_hygiene(rep, merged, clone, conv, args.offline)
        check_naming(rep, merged, conv)
        if kind == "web-site":
            # websites have no module, icon, package or APK release to check
            continue
        version = check_module(rep, merged, clone, conv, merged["module"],
                               merged.get("package_expected"), merged.get("label_expected"),
                               merged.get("permissions_baseline"))
        for em in proj.get("extra_modules", []):
            check_module(rep, merged, clone, conv, em["path"], em.get("package_expected"),
                         None, None, check_id_prefix="extra:" + em["path"] + ":",
                         lenient=True)
        check_icon(rep, merged, clone, conv, version)
        if args.apk_file:
            with open(args.apk_file, "rb") as f:
                apk_bytes = f.read()
            rep.add(app, INFO, "candidate-sha256",
                    "candidate APK sha256 %s" % hashlib.sha256(apk_bytes).hexdigest())
            base = os.path.basename(args.apk_file)
            clean_v = args.apk_version or (version.replace(" (default)", "") if version else None)
            want_name = conv["android"]["apk_name_pattern"].format(app=app, version=clean_v)
            if base == want_name:
                rep.add(app, PASS, "candidate-name", "candidate already named " + base)
            else:
                rep.add(app, INFO, "candidate-name",
                        "candidate file %s will be renamed %s at upload; the post-publish "
                        "check verifies the published name" % (base, want_name))
            check_packaged_icon(rep, merged, conv, apk_bytes, clean_v)
        if not args.offline:
            rel = check_release(rep, merged, conv, by_app.get(app), args.apk, args.workdir)
            if rel:
                apps_with_release.add(app)
    if not args.offline and cards:
        check_gallery_coverage(rep, projects, cards, apps_with_release)

    print(rep.text())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([{"project": p, "severity": s, "check": c, "message": m}
                       for p, s, c, m in rep.rows], f, indent=2)
    return 1 if rep.counts()[FAIL] else 0


def load_json_url(url):
    return json.loads(fetch_bytes(url).decode("utf-8"))


def current_gallery_by_app(cards):
    """Previous-build cards must never shadow the available current card."""
    out = {}
    for card in cards:
        name = card.get("name")
        if name not in out or (card.get("state") == "available" and
                               out[name].get("state") != "available"):
            out[name] = card
    return out


def gallery_cards(data):
    if isinstance(data, dict):
        return data.get("apps", [])
    return data


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
