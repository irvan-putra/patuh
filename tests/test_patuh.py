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


if __name__ == "__main__":
    unittest.main(verbosity=2)
