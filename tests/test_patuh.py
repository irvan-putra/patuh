#!/usr/bin/env python3
"""Tests for patuh: approved icons must pass, known-bad cases must fail.

Fixtures include the actual rejected Tumbuh 0.1.0 icon and the approved
Kemas 0.2.3 icon, both extracted from their public release APKs. Synthetic
negatives are generated with the family's own pinned font and constants.

Run: python3 tests/test_patuh.py   (icon tests need pillow==12.3.0)
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import patuh  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
FONT = os.path.join(os.path.dirname(__file__), "..", "fonts", "DejaVuSans-Bold.ttf")

with open(os.path.join(os.path.dirname(__file__), "..", "conventions.json")) as f:
    CONV = json.load(f)["icon_family"]


def results_by_id(rows):
    return {cid: ok for ok, cid, _ in rows}


def make_family_icon(version, strip=True, corner=0.2, art_outside=False):
    """Minimal re-render of the family pipeline: rounded square, bottom
    strip, badge text, one dot of art - same constants as the generator."""
    from PIL import Image, ImageDraw, ImageFont
    S = 768
    im = Image.new("RGBA", (S, S), (232, 243, 237, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([S * .3, S * .3, S * .5, S * .5], fill=(58, 140, 100, 255))
    if art_outside:
        d.ellipse([S * .80, S * .02, S * .98, S * .20], fill=(58, 140, 100, 255))
    if strip:
        y0 = int(S * CONV["strip_top"])
        d.rectangle([0, y0, S, S], fill=(43, 55, 79, 255))
        f = ImageFont.truetype(FONT, int(S * CONV["text_size"]))
        d.text((S / 2, (y0 + S) / 2), version, font=f, fill=(255, 255, 255, 255), anchor="mm")
    if corner:
        from PIL import ImageChops
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, S - 1, S - 1], radius=corner * S, fill=255)
        im.putalpha(ImageChops.multiply(im.getchannel("A"), m))
    return im.resize((192, 192), Image.LANCZOS)


def have_pillow():
    return patuh.pil()[0] == "ok"


@unittest.skipUnless(have_pillow(), "Pillow 12.3.0 not available")
class IconGeometry(unittest.TestCase):
    def test_approved_real_icon_passes(self):
        from PIL import Image
        rows = patuh.icon_pixel_checks(Image.open(os.path.join(FIX, "kemas-0.2.3-approved.png")),
                                       "0.2.3", CONV, FONT)
        for ok, cid, msg in rows:
            self.assertTrue(ok, "%s should pass: %s" % (cid, msg))

    def test_rejected_tumbuh_icon_fails(self):
        """The actual icon Irvan rejected: this suite must catch it."""
        from PIL import Image
        rows = patuh.icon_pixel_checks(Image.open(os.path.join(FIX, "tumbuh-0.1.0-rejected.png")),
                                       "0.1.0", CONV, FONT)
        by = results_by_id(rows)
        self.assertFalse(by["icon-strip"], "pill badge must fail the strip check")
        self.assertFalse(by["icon-corner"], "unbounded art must fail the corner check")

    def test_wrong_badge_version_fails(self):
        rows = patuh.icon_pixel_checks(make_family_icon("0.0.0"), "9.9.9", CONV, FONT)
        by = results_by_id(rows)
        self.assertFalse(by["icon-badge-version"], "stale badge text must fail")
        self.assertTrue(by["icon-strip-top"], "geometry itself is fine")
        self.assertTrue(by["icon-strip-width"], "geometry itself is fine")

    def test_one_digit_off_badge_fails(self):
        """The sapa incident shape: badge shows last release's version."""
        rows = patuh.icon_pixel_checks(make_family_icon("0.2.8"), "0.2.3", CONV, FONT)
        self.assertFalse(results_by_id(rows)["icon-badge-version"],
                         "a one-digit-stale badge must fail")

    def test_missing_strip_fails(self):
        rows = patuh.icon_pixel_checks(make_family_icon("1.0.0", strip=False), "1.0.0", CONV, FONT)
        self.assertFalse(results_by_id(rows)["icon-strip"])

    def test_square_corner_fails(self):
        rows = patuh.icon_pixel_checks(make_family_icon("1.0.0", corner=0), "1.0.0", CONV, FONT)
        self.assertFalse(results_by_id(rows)["icon-corner"])

    def test_art_outside_safe_circle_fails(self):
        rows = patuh.icon_pixel_checks(make_family_icon("1.0.0", art_outside=True), "1.0.0", CONV, FONT)
        self.assertFalse(results_by_id(rows)["icon-safe-circle"])


class ConsolidatedLicense(unittest.TestCase):
    def test_nested_license_does_not_relicense_website(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "android"))
            with open(os.path.join(root, "android", "LICENSE"), "w") as f:
                f.write("GNU AFFERO GENERAL PUBLIC LICENSE")
            self.assertIsNone(patuh.detect_license(root))
            self.assertEqual(patuh.detect_license(root, "android"), "AGPL-3.0")

    def test_tumbuh_registry_points_to_consolidated_module(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "projects.json")) as f:
            p = next(x for x in json.load(f)["projects"] if x["app"] == "tumbuh")
        self.assertEqual((p["repo"], p["module"], p["license_root"]),
                         ("tumbuh", "android/app", "android"))


class Parsing(unittest.TestCase):
    def gradle(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".gradle", delete=False) as f:
            f.write(text)
        return patuh.parse_gradle(f.name)

    def test_plain(self):
        self.assertEqual(self.gradle('applicationId "com.vanipy.x"\nversionName "1.2.3"'),
                         ("com.vanipy.x", "1.2.3"))

    def test_groovy_property_default(self):
        self.assertEqual(self.gradle(
            "applicationId 'com.vanipy.x'\nversionName((project.findProperty('versionName') ?: '0.1.1') as String)"),
            ("com.vanipy.x", "0.1.1 (default)"))

    def test_kts_val_indirection(self):
        self.assertEqual(self.gradle(
            'val appVersionName = "0.1.1"\ndefaultConfig { versionName = appVersionName }'),
            (None, "0.1.1"))

    def test_manifest(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write('<manifest><uses-permission android:name="android.permission.CAMERA"/>'
                    '<application android:label="myapp" android:icon="@mipmap/ic_launcher"/></manifest>')
        perms, label, icon = patuh.manifest_facts(f.name)
        self.assertEqual(perms, ["android.permission.CAMERA"])
        self.assertEqual(label, "myapp")
        self.assertEqual(icon, "@mipmap/ic_launcher")

    def test_manifest_tools_remove_entries_are_not_permissions(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write('<manifest xmlns:tools="http://schemas.android.com/tools">'
                    '<uses-permission android:name="android.permission.WAKE_LOCK"\n'
                    '        tools:node="remove" />'
                    '<uses-permission android:name="android.permission.CAMERA"/>'
                    '<application android:label="myapp" android:icon="@mipmap/ic_launcher"/></manifest>')
        perms, label, icon = patuh.manifest_facts(f.name)
        self.assertEqual(perms, ["android.permission.CAMERA"])


class CurrentGallery(unittest.TestCase):
    def test_previous_build_does_not_shadow_available(self):
        current = {"name": "tumbuh", "version": "0.2.2", "state": "available"}
        old = {"name": "tumbuh", "version": "0.2.1", "state": "previous"}
        self.assertEqual(patuh.current_gallery_by_app([current, old])["tumbuh"], current)
        self.assertEqual(patuh.current_gallery_by_app([old, current])["tumbuh"], current)


class Checksums(unittest.TestCase):
    class FakeResp:
        def __init__(self, body):
            self.body = body

    def assets(self, *names):
        return {n: {"browser_download_url": "https://example.invalid/" + n} for n in names}

    def patch_fetch(self, bodies):
        real = patuh.fetch_bytes
        patuh.fetch_bytes = lambda url: bodies[url.rsplit("/", 1)[-1]]
        return real

    def test_sidecar_format(self):
        assets = self.assets("myapp-v1.0.0.apk", "myapp-v1.0.0.apk.sha256")
        real = self.patch_fetch({"myapp-v1.0.0.apk.sha256": b"a" * 64 + b"\n"})
        try:
            found = patuh.find_checksum(assets, "myapp-v1.0.0.apk", "myapp-v1.0.0.apk.sha256")
        finally:
            patuh.fetch_bytes = real
        self.assertEqual(found, ("myapp-v1.0.0.apk.sha256", "a" * 64, "sidecar"))

    def test_sha256sums_format(self):
        assets = self.assets("myapp-v1.0.0.apk", "SHA256SUMS")
        body = ("b" * 64 + "  other.zip\n" + "c" * 64 + "  myapp-v1.0.0.apk\n").encode()
        real = self.patch_fetch({"SHA256SUMS": body})
        try:
            found = patuh.find_checksum(assets, "myapp-v1.0.0.apk", "myapp-v1.0.0.apk.sha256")
        finally:
            patuh.fetch_bytes = real
        self.assertEqual(found, ("SHA256SUMS", "c" * 64, "sha256sums"))

    def test_missing_checksum(self):
        real = self.patch_fetch({})
        try:
            found = patuh.find_checksum(self.assets("myapp-v1.0.0.apk"),
                                        "myapp-v1.0.0.apk", "myapp-v1.0.0.apk.sha256")
        finally:
            patuh.fetch_bytes = real
        self.assertIsNone(found)

    def test_sha256sums_without_apk_line(self):
        assets = self.assets("myapp-v1.0.0.apk", "SHA256SUMS")
        real = self.patch_fetch({"SHA256SUMS": ("b" * 64 + "  other.zip\n").encode()})
        try:
            found = patuh.find_checksum(assets, "myapp-v1.0.0.apk", "myapp-v1.0.0.apk.sha256")
        finally:
            patuh.fetch_bytes = real
        self.assertIsNone(found)


class RegistryCoverageTests(unittest.TestCase):
    def test_new_inventory_entries_do_not_seed_baselines(self):
        registry_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "projects.json")
        with open(registry_path, encoding="utf-8") as f:
            projects = json.load(f)["projects"]
        entries = {p["repo"]: p for p in projects}
        for name in ("jasa", "naung"):
            entry = entries[name]
            self.assertEqual(entry["kind"], "inventory")
            self.assertEqual(entry["coverage"], "inventory-only")
            self.assertFalse(set(entry) & {"package_id", "permissions", "license", "icon", "baseline_source"})
        report = patuh.Report()
        patuh.check_registry_coverage(report, projects, [{"name": n} for n in entries])
        self.assertFalse(any(row[1] == patuh.FAIL for row in report.rows))
        patuh.check_registry_coverage(report, projects, [{"name": "future-unregistered-repo"}])
        self.assertTrue(any(row[1:3] == (patuh.FAIL, "registry-missing") for row in report.rows))

    def test_missing_repo_fails_even_if_other_entries_exist(self):
        r = patuh.Report()
        patuh.check_registry_coverage(r, [{"repo": "tumbuh"}], [{"name": "tumbuh"}, {"name": "new-app"}])
        self.assertTrue(any(row[1:3] == (patuh.FAIL, "registry-missing") for row in r.rows))

    def test_all_represented_is_presence_only(self):
        r = patuh.Report()
        patuh.check_registry_coverage(r, [{"repo": "tumbuh"}], [{"name": "tumbuh"}])
        self.assertIn("presence is not qualification", r.rows[0][3])

    def test_skips_reviews_and_warnings_not_clean(self):
        for severity, status in [(patuh.REVIEW, "INCOMPLETE"), (patuh.SKIP, "INCOMPLETE"), (patuh.WARN, "WARNINGS")]:
            r = patuh.Report()
            r.add("x", severity, "coverage", "not verified")
            self.assertIn(status, r.text())

class DrawableIconTests(unittest.TestCase):
    def test_manifest_drawable_is_pixel_checked_not_missing_mipmap(self):
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path
            root = Path(d) / "app/src/main"
            (root / "res/drawable").mkdir(parents=True)
            (root / "AndroidManifest.xml").write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:icon="@drawable/ic_launcher"/></manifest>')
            make_family_icon("1.2.3").save(root / "res/drawable/ic_launcher.png")
            r = patuh.Report()
            patuh.check_icon(r, {"app":"test", "module":"app"}, d, {"icon_family": CONV}, "1.2.3")
            self.assertFalse(any(row[2] == "icon-densities" for row in r.rows))
            self.assertTrue(any(row[2] == "icon-badge-version" for row in r.rows))

    def test_manifest_vector_drawable_is_review_not_fail(self):
        """A vector launcher icon (tampung's shape) is legitimate Android; the
        family geometry cannot be pixel-checked, so it is a visual REVIEW."""
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path
            root = Path(d) / "app/src/main"
            (root / "res/drawable").mkdir(parents=True)
            (root / "AndroidManifest.xml").write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:icon="@drawable/ic_launcher"/></manifest>')
            (root / "res/drawable/ic_launcher.xml").write_text('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp"/>')
            r = patuh.Report()
            patuh.check_icon(r, {"app": "test", "module": "app"}, d, {"icon_family": CONV}, "1.2.3")
            self.assertIn((patuh.REVIEW, "icon-resource"), [(row[1], row[2]) for row in r.rows])
            self.assertFalse(any(row[1] == patuh.FAIL for row in r.rows))

    def test_manifest_drawable_missing_entirely_fails(self):
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path
            root = Path(d) / "app/src/main"
            (root / "res/drawable").mkdir(parents=True)
            (root / "AndroidManifest.xml").write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:icon="@drawable/ic_launcher"/></manifest>')
            r = patuh.Report()
            patuh.check_icon(r, {"app": "test", "module": "app"}, d, {"icon_family": CONV}, "1.2.3")
            self.assertIn((patuh.FAIL, "icon-resource"), [(row[1], row[2]) for row in r.rows])

class GalleryCoverageKinds(unittest.TestCase):
    def test_web_site_projects_skip_apk_gallery_coverage(self):
        rep = patuh.Report()
        projects = [
            {"app": "kapan", "repo": "kapan", "kind": "web-site"},
            {"app": "ghost", "repo": "ghost", "kind": "android-app"},
        ]
        patuh.check_gallery_coverage(rep, projects, [])
        by_app = {}
        for app, sev, cid, msg in rep.rows:
            by_app.setdefault(app, []).append((sev, cid))
        self.assertNotIn("kapan", by_app)
        self.assertIn((patuh.FAIL, "gallery-card"), by_app["ghost"])

    def test_unreleased_app_is_not_flagged_for_missing_card(self):
        """No published APK means a missing gallery card is not a defect."""
        rep = patuh.Report()
        projects = [
            {"app": "released", "repo": "released", "kind": "android-app"},
            {"app": "unreleased", "repo": "unreleased", "kind": "android-app"},
        ]
        patuh.check_gallery_coverage(rep, projects, [], apps_with_release={"released"})
        flagged = {app for app, sev, cid, msg in rep.rows if sev == patuh.FAIL}
        self.assertEqual(flagged, {"released"})


class RegistryShape(unittest.TestCase):
    """The registry itself: qualification must be explicit and complete, and
    an inventory entry must never silently carry an approved baseline."""

    @classmethod
    def projects(cls):
        with open(os.path.join(os.path.dirname(__file__), "..", "projects.json")) as f:
            return json.load(f)["projects"]

    def test_inventory_entries_carry_no_baselines(self):
        baseline_fields = {"module", "package_expected", "label_expected",
                           "permissions_baseline", "license_baseline", "icon_mode"}
        for p in self.projects():
            if p["kind"] == "inventory":
                self.assertFalse(baseline_fields & set(p),
                                 "inventory entry %s must not carry baseline fields" % p["app"])

    def test_qualified_android_apps_are_complete(self):
        for p in self.projects():
            if p["kind"] == "android-app":
                for field in ("module", "package_expected", "label_expected",
                              "permissions_baseline", "icon_mode"):
                    self.assertIn(field, p, "%s missing %s" % (p["app"], field))
                self.assertTrue(p["package_expected"].startswith("com.vanipy."),
                                "%s outside com.vanipy.*" % p["app"])
                self.assertEqual(p["label_expected"], p["label_expected"].lower(),
                                 "%s label not lowercase" % p["app"])

    def test_seeded_baselines_are_recorded_openly(self):
        """Entries qualified after the original thirteen must say where their
        baselines came from - never a silent inventory-to-approved flip."""
        for p in self.projects():
            if p["kind"] != "inventory" and "baseline_source" in p:
                self.assertIn("seeded", p["baseline_source"])


@unittest.skipUnless(have_pillow(), "Pillow 12.3.0 not available")
class PackagedIcon(unittest.TestCase):
    def apk_bytes(self, version, path="res/mipmap-xxxhdpi/ic_launcher.png"):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            img = io.BytesIO()
            make_family_icon(version).save(img, "PNG")
            z.writestr(path, img.getvalue())
        return buf.getvalue()

    def test_candidate_apk_badge_must_match_candidate_version(self):
        rep = patuh.Report()
        patuh.check_packaged_icon(rep, {"app": "x", "icon_mode": "family"},
                                  {"icon_family": CONV}, self.apk_bytes("1.2.3"), "1.2.3")
        self.assertIn((patuh.PASS, "apk-icon-badge-version"),
                      [(row[1], row[2]) for row in rep.rows])

    def test_candidate_apk_stale_badge_fails(self):
        rep = patuh.Report()
        patuh.check_packaged_icon(rep, {"app": "x", "icon_mode": "family"},
                                  {"icon_family": CONV}, self.apk_bytes("1.2.2"), "1.2.3")
        self.assertIn((patuh.FAIL, "apk-icon-badge-version"),
                      [(row[1], row[2]) for row in rep.rows])

    def test_obfuscated_resource_path_still_checked(self):
        rep = patuh.Report()
        patuh.check_packaged_icon(rep, {"app": "x", "icon_mode": "family"},
                                  {"icon_family": CONV}, self.apk_bytes("1.2.3", "res/ab.png"), "1.2.3")
        self.assertIn((patuh.PASS, "apk-icon-badge-version"),
                      [(row[1], row[2]) for row in rep.rows])


class ReleaseGateWorkflowShape(unittest.TestCase):
    """The reusable gate itself must keep the proven shape: the pinned patuh
    checkout, the three modes, and the byte check gated on the artifact input
    and never running post-publish."""

    @classmethod
    def doc(cls):
        import yaml
        path = os.path.join(os.path.dirname(__file__), "..",
                            ".github", "workflows", "release-gate.yml")
        with open(path) as f:
            return yaml.safe_load(f)

    @classmethod
    def steps(cls):
        return cls.doc()["jobs"]["gate"]["steps"]

    def test_pinned_patuh_checkout_is_an_immutable_commit(self):
        # A version tag is movable: the internal checker checkout must pin
        # the exact reviewed commit, or a caller pinning this workflow by
        # SHA would still execute a mutable patuh.py.
        checkouts = [s for s in self.steps()
                     if str(s.get("uses", "")).startswith("actions/checkout@")
                     and (s.get("with") or {}).get("repository") == "irvan-putra/patuh"]
        self.assertEqual(len(checkouts), 1)
        self.assertRegex(checkouts[0]["with"]["ref"], r"^[0-9a-f]{40}$")

    def test_inputs_keep_their_contract(self):
        on = self.doc().get(True, self.doc().get("on"))
        inputs = on["workflow_call"]["inputs"]
        self.assertTrue(inputs["app"]["required"])
        self.assertIs(inputs["published"]["default"], False)
        self.assertEqual(inputs["candidate_apk_artifact"]["default"], "")
        self.assertEqual(inputs["candidate_version"]["default"], "")

    def test_source_gate_is_offline_and_pre_publish_only(self):
        src = [s for s in self.steps() if "pre-publish source gate" in s.get("name", "")]
        self.assertEqual(len(src), 1)
        self.assertIn("--offline", src[0]["run"])
        self.assertIn("!inputs.published", src[0]["if"])

    def test_byte_check_uses_apk_file_and_requires_artifact(self):
        byt = [s for s in self.steps() if "--apk-file" in s.get("run", "")]
        self.assertEqual(len(byt), 1)
        self.assertIn("!inputs.published", byt[0]["if"])
        self.assertIn("candidate_apk_artifact != ''", byt[0]["if"])

    def test_post_publish_verify_uses_apk_online(self):
        post = [s for s in self.steps() if "post-publish" in s.get("name", "")]
        self.assertEqual(len(post), 1)
        self.assertIn("--apk", post[0]["run"])
        self.assertNotIn("--offline", post[0]["run"])
        self.assertIn("inputs.published", post[0]["if"])


def _build_axml(pkg):
    """Minimal binary AndroidManifest.xml declaring one package attribute."""
    import struct
    strings = ["package", pkg, "manifest"]
    blob, offsets = b"", []
    for s in strings:
        b = s.encode("utf-8")
        offsets.append(len(blob))
        blob += bytes([len(b), len(b)]) + b + b"\0"
    sstart = 28 + 4 * len(strings)
    sp = struct.pack("<HHIIIIII", 0x0001, 28, sstart + len(blob),
                     len(strings), 0, 0x100, sstart, 0)
    sp += b"".join(struct.pack("<I", o) for o in offsets) + blob
    attr = struct.pack("<IIIHBBI", 0xFFFFFFFF, 0, 1, 8, 0, 0x03, 1)
    body = struct.pack("<IIIIHHHHHH", 0, 0xFFFFFFFF, 0xFFFFFFFF, 2,
                       20, 20, 1, 0, 0, 0) + attr
    se = struct.pack("<HHI", 0x0102, 16, 8 + len(body)) + body
    return struct.pack("<HHI", 0x0003, 8, 8 + len(sp) + len(se)) + sp + se


def _apk_with_manifest(pkg):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", _build_axml(pkg))
    return buf.getvalue()


class PackagedPackageCheck(unittest.TestCase):
    """The APK's own manifest package must match the registry expectation."""

    class Rep:
        def __init__(self):
            self.rows = []

        def add(self, app, status, check, msg):
            self.rows.append((status, check, msg))

    PROJ = {"app": "x", "package_expected": "com.vanipy.x"}

    def test_reads_binary_manifest_package(self):
        self.assertEqual(patuh.apk_package(_apk_with_manifest("com.vanipy.x")),
                         "com.vanipy.x")

    def test_matching_package_passes(self):
        rep = self.Rep()
        patuh.check_packaged_package(rep, self.PROJ, _apk_with_manifest("com.vanipy.x"))
        self.assertEqual([r[0] for r in rep.rows], ["PASS"])

    def test_mismatched_package_fails(self):
        # a stale artifact from before a rename must not slip through
        rep = self.Rep()
        patuh.check_packaged_package(rep, self.PROJ, _apk_with_manifest("com.old.x"))
        self.assertEqual(rep.rows[0][0], "FAIL")

    def test_unreadable_package_skips(self):
        rep = self.Rep()
        patuh.check_packaged_package(rep, self.PROJ, b"not an apk")
        self.assertEqual(rep.rows[0][0], "SKIP")


class CallerChainValidator(unittest.TestCase):
    """The validator script: a correctly wired chain passes, and each broken
    shape it exists to catch fails."""

    def write(self, doc):
        import yaml
        f = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False)
        yaml.safe_dump(doc, f)
        f.close()
        return f.name

    def good(self):
        gate = ("irvan-putra/patuh/.github/workflows/release-gate.yml@"
                "6f4b1eec2a8f73348725b7e3698d3e7bca93b890")
        return {"on": {"workflow_dispatch": None}, "jobs": {
            "consistency": {"uses": gate, "with": {"app": "x", "published": False}},
            "build": {"needs": "consistency", "steps": [{"run": "./gradlew assembleRelease"}]},
            "candidate-bytes": {"needs": "build", "uses": gate,
                                "with": {"app": "x", "published": False,
                                         "candidate_apk_artifact": "candidate-apk"}},
            "publish": {"needs": "candidate-bytes",
                        "steps": [{"uses": "actions/download-artifact@v4"},
                                  {"env": {"GH_REPO": "o/r"},
                                   "run": "gh release create v1 x.apk"}]},
            "verify": {"needs": "publish", "uses": gate,
                       "with": {"app": "x", "published": True}},
        }}

    def test_well_shaped_chain_passes(self):
        from tools import validate_caller_chain as v
        probs, notes = v.problems(self.write(self.good()))
        self.assertEqual(probs, [])

    def test_ungated_publish_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["needs"] = "build"
        self.assertTrue(any("must gate publishing" in p
                            for p in v.problems(self.write(doc))[0]))

    def test_tag_trigger_allowed_when_gates_hold(self):
        # Trigger style is an implementation choice, not checker policy:
        # a tag-triggered release passes while the publish job stays gated.
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["on"] = {"push": {"tags": ["v*"]}}
        self.assertEqual(v.problems(self.write(doc))[0], [])

    def test_wrapped_run_scalar_still_detected(self):
        # yaml.safe_dump wraps long lines; detection must read the raw run
        # scalars so a long gh-release command still marks the publish job.
        from tools import validate_caller_chain as v
        doc = self.good()
        long_cmd = "gh release create v1 " + "--notes " + "x" * 120 + " app.apk"
        doc["jobs"]["publish"]["steps"] = [{"uses": "actions/download-artifact@v4"},
                                           {"env": {"GH_REPO": "o/r"}, "run": long_cmd}]
        self.assertEqual(v.problems(self.write(doc))[0], [])

    def test_missing_bytes_job_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        del doc["jobs"]["candidate-bytes"]
        self.assertTrue(any("candidate-bytes" in p for p in v.problems(self.write(doc))[0]))

    def test_tag_pinned_gate_fails(self):
        # Tags are movable: only a full reviewed commit SHA is an acceptable pin.
        from tools import validate_caller_chain as v
        doc = self.good()
        for j in doc["jobs"].values():
            if "uses" in j:
                j["uses"] = "irvan-putra/patuh/.github/workflows/release-gate.yml@v0.2.1"
        self.assertTrue(any("full reviewed commit SHA" in p
                            for p in v.problems(self.write(doc))[0]))

    def test_build_without_source_gate_needs_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["build"]["needs"] = []
        doc["jobs"]["candidate-bytes"]["needs"] = "build"
        self.assertTrue(any("must follow the source gate" in p
                            for p in v.problems(self.write(doc))[0]))

    def test_publish_without_bytes_needs_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["needs"] = "build"
        self.assertTrue(any("must gate publishing" in p
                            for p in v.problems(self.write(doc))[0]))

    def test_outputs_reference_without_needs_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["steps"].append(
            {"run": "gh release create v1 ${{ needs.build.outputs.apk }}"})
        self.assertTrue(any("without needing them" in p
                            for p in v.problems(self.write(doc))[0]))

    def test_publish_without_fetch_is_a_note_not_a_failure(self):
        # scripts may generate assets inline; static analysis cannot prove
        # provenance either way, so this stays a note.
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["steps"] = [
            {"env": {"GH_REPO": "o/r"}, "run": "gh release create v1 x.apk"}]
        probs, notes = v.problems(self.write(doc))
        self.assertEqual(probs, [])
        self.assertTrue(any("not statically proven" in n for n in notes))

    def test_publish_gh_without_repo_context_fails(self):
        # no checkout and no explicit repo context: gh cannot resolve the
        # repository - a provable failure, not a heuristic.
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["steps"] = [
            {"uses": "actions/download-artifact@v4"},
            {"run": "gh release create v1 x.apk"}]
        probs, _ = v.problems(self.write(doc))
        self.assertTrue(any("cannot resolve the repository" in p for p in probs))

    def test_publish_gh_with_gh_repo_env_passes(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["jobs"]["publish"]["steps"] = [
            {"uses": "actions/download-artifact@v4"},
            {"env": {"GH_REPO": "o/r"}, "run": "gh release create v1 x.apk"}]
        probs, _ = v.problems(self.write(doc))
        self.assertEqual(probs, [])

    def test_tag_trigger_with_ungated_publish_fails(self):
        from tools import validate_caller_chain as v
        doc = self.good()
        doc["on"] = {"push": {"tags": ["v*"]}}
        doc["jobs"]["publish"]["needs"] = "build"
        self.assertTrue(any("must gate publishing" in p
                            for p in v.problems(self.write(doc))[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
