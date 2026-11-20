# patuh

Cross-project consistency checker for the app family. It catches drift from
the conventions Irvan approved and from each project's own approved baseline.
It reports; it never modifies a project.

Born 2026-11-17: Tumbuh 0.1.0 shipped with a small floating pill badge while
the other eleven apps share one rounded-square icon family with a full-width
numeric version strip. A person caught it on a real launcher. patuh exists so
a script catches the next one before release.

## What it checks

Per Android app in `projects.json`:

- **Package identity.** `applicationId` matches the project's expected
  `com.vanipy.*` ID in source (and, with `--apk`, is reported for the built
  APK). A mismatch is a finding to discuss: changing an applicationId makes
  Android treat the app as new, so patuh never "fixes" it.
- **Versions are three numbers, aligned everywhere.** `versionName` in the
  build file, the release tag (`vX.Y.Z`), the APK filename
  (`app-vX.Y.Z.apk`), the published checksum, the gallery card, and the
  version drawn on the icon badge itself (the badge is read character by
  character with the family's pinned font, so a one-digit-stale badge
  fails).
- **Launcher icon family geometry** (needs Pillow, pinned): rounded corner,
  full-width strip across the bottom 24%, badge text pixels match the
  version string rendered with the pinned font, art stays inside the
  round-mask safe circle, all five densities present. An
  `mipmap-anydpi-v26` adaptive icon is flagged: Android 8+ prefers it over
  the raster set, which is exactly how the Tumbuh regression shipped.
- **Permissions** in the module's `AndroidManifest.xml` equal the baselined
  set (menit's usage-stats access, tumbuh's zero permissions, ...). Drift
  either way is a FAIL.
- **Launcher label** matches the baselined lowercase name.
- **Repo hygiene.** Public repo, README, LICENSE file compared against its
  baseline (licenses differ per project on purpose; a change warns because
  relicensing needs his confirmation), last-commit author.
- **Naming.** New names contain no L/R and don't start with I. Existing
  names are grandfathered: violations are warnings.
- **Gallery agreement.** Every app has a card in kaji's `gallery/apps.json`;
  card version matches the latest release; card checksum matches the
  release's published checksum. Two checksum formats are accepted, both in
  approved use: the per-asset `app-vX.Y.Z.apk.sha256` sidecar and a
  sha256sum-format `SHA256SUMS` file (intodo's format).
- With `--apk`: downloads the released APK, verifies its sha256 against the
  published checksum, and pixel-checks the launcher icon that actually
  ships.

## Coverage: source configuration vs built APK

Being explicit about where each fact is checked:

| Fact | In source | In the built APK (--apk) |
|---|---|---|
| applicationId / com.vanipy.* | yes (build file) | no - compiled manifest decoding is not implemented |
| versionName | yes (build file) | via tag/filename/badge |
| permissions | yes (AndroidManifest.xml) | no |
| launcher label | yes (manifest + strings) | no |
| launcher icon geometry + badge text | yes (res PNGs) | yes (packaged PNG, incl. obfuscated resource paths) |
| checksum integrity | n/a | yes (download and hash) |
| release assets, tag, gallery card | yes (GitHub API) | n/a |

A build step that rewrites the manifest between source and APK would not be
caught today; that gap is stated, not hidden.

## What it does not check

patuh compares structure, metadata and pixels. It cannot judge that art
looks right, that an app works, that wording is good, or that an
adaptive/custom/vector icon renders correctly on a launcher - those stay
REVIEW items for a human with screenshots, and a green run is not proof an
icon looks right. A declared custom photo icon is such a declared
exception. CLEAN only means every check that ran passed; skipped
and review items are always listed in the summary.

Secret scanning is deliberately not reimplemented here: use
[gitsafescan](https://github.com/irvan-putra/gitsafescan). Feed/projection
wording checks live in intodo's `tools/feed-consistency`.

## Usage

```bash
python3 patuh.py                 # source + release-metadata + gallery checks
python3 patuh.py --apk           # additionally download APKs, verify checksums, pixel-check packaged icons
python3 patuh.py --only tumbuh   # one project
python3 patuh.py --offline       # source checks only (uses clones in --workdir)
python3 patuh.py --only tumbuh --offline --apk-file app-release.apk
                                 # pre-publish: byte-check a locally built candidate APK
python3 patuh.py --json report.json
```

Requirements: Python 3.8+, git. Icon pixel checks need `pip install
pillow==12.3.0` and use the pinned `fonts/DejaVuSans-Bold.ttf`
(sha256-verified on load); without them those checks report SKIP, never a
silent pass.

Exit code: `0` no FAIL findings, `1` at least one FAIL, `2` usage error.

## Configuration

- `conventions.json` — the shared rules as data, each with its source.
- `projects.json` — the registry: repo, app module path, expected package
  ID, label, permission baseline, license baseline, icon mode
  (`family`/`adaptive`/`custom`), optional `license_root` for a licensed subtree, and free-text notes for declared
  exceptions.
- A repo's own `patuh.json` (see `examples/patuh.json`) overrides registry
  fields for that repo. Declaring an exception in the repo keeps it next to
  the code it describes.

A baseline change is a deliberate edit with a commit message, not a side
effect of running the checker.

## Running in GitHub Actions

`.github/workflows/patuh.yml` runs the checker on demand and weekly
(Mondays 02:00 UTC, 09:00 WIB) against the whole registry, including the
APK download/checksum/packaged-icon verification. The weekly schedule was
approved 2026-11-20; before that the run was manual-only and this README
was wrong. A red weekly run means drift was found between releases.

## Required gate in an app's release workflow

`.github/workflows/release-gate.yml` is a reusable workflow an app repo
calls so a release cannot ship past a consistency failure. Wire it per app,
as its own small reviewed change. Pin the reusable workflow by full commit
SHA (as shown); version tags are movable and must not be used as the pin.
The workflow itself checks out the patuh checker by its reviewed commit, so
the executed code is immutable too. `tools/validate_caller_chain.py`
shape-checks a wired release workflow before it is trusted:

    python3 tools/validate_caller_chain.py /path/to/repo/.github/workflows/release.yml

```yaml
jobs:
  consistency:
    uses: irvan-putra/patuh/.github/workflows/release-gate.yml@6f4b1eec2a8f73348725b7e3698d3e7bca93b890
    with:
      app: myapp
      published: false   # pre-publish gate on the exact tree being released
  build:
    needs: consistency
    # ... build and sign the APK, upload it as an artifact named candidate-apk ...
  candidate-bytes:
    needs: build
    uses: irvan-putra/patuh/.github/workflows/release-gate.yml@6f4b1eec2a8f73348725b7e3698d3e7bca93b890
    with:
      app: myapp
      published: false
      candidate_apk_artifact: candidate-apk   # byte-check BEFORE publishing
  publish:
    needs: candidate-bytes
    # ... gh release create ...
  verify:
    needs: publish
    uses: irvan-putra/patuh/.github/workflows/release-gate.yml@6f4b1eec2a8f73348725b7e3698d3e7bca93b890
    with:
      app: myapp
      published: true    # post-publish: verifies the live release + gallery
```

The gate always checks the caller's checkout at the ref that triggered the
caller's workflow, never patuh's own tree. The pre-publish gate checks the
candidate source (package ID, three-number version, lowercase label,
permission/license drift, family icon geometry, badge text reading the
candidate version). It does not judge older releases, so fixing an old
non-conforming release is never blocked by its own past.

With `candidate_apk_artifact`, the gate also checks the built APK's actual
bytes before the publish job may run: the packaged launcher icon must carry
the family badge reading the candidate version, and the candidate's sha256
is logged for comparison with the published sidecar. **This is the
preventive boundary**: wired before publish, a defect stops the release.
The post-publish call runs after the release is live and verifies the
published artifacts (tag format, versioned APK filename, checksum asset,
gallery card agreement, downloaded-APK sha256, packaged icon pixels); it
detects anything that still slipped through but cannot unpublish it.

The gate does not replace an app's own build-time checks (signing-certificate
pinning, aapt badging, tests); it adds the family-consistency layer.

## Scope

This repo checks the projects listed in its own registry. It does not run
against or change any repo by itself.

## Complete repository inventory

The registry represents all 68 current owner repositories observed on 19 November 2026,
including forks and archived projects. Twenty-one entries are qualified: eighteen Android
apps and three websites. The Android family grew from the original twelve on 2026-11-20,
when Irvan approved making these checks required across the app family, explicitly beyond
Nada (kokok, nada, sanggup, tampung, tengok and tuju qualified that day, plus the daya and
denting websites). Their per-app permission/license baselines are seeded from the shipped
source at that date and say so in their `baseline_source` notes: a seeded baseline detects
FUTURE DRIFT from what shipped - seeding is not his approval of those permissions or that
license, and not a security validation. The family conventions
themselves (com.vanipy.* IDs, lowercase labels, three-number versions, family icons,
versioned APK filenames with checksums) come from his standing rules. Seeded baselines
change only by a deliberate edit with his ok.

The other 47 entries are explicitly `inventory-only`, including Unggun (Flutter, checker
unsupported), sapi (a personal sandbox tester outside the family conventions - whether it
adopts them is his call), tools and older repositories. Being on this list does not mean a
project passed checks. Each such entry produces REVIEW, never PASS.
New package/permission/license baselines have not been silently approved or invented.

Every online run compares the whole registry with the live, paginated owner repository
list. A new unregistered repository fails `registry-missing`, even with `--only`.
An unavailable listing or offline run is SKIP. Removed/renamed entries are REVIEW.
Removed tumbuh-app is recorded separately with its canonical destination, not as a current
repository. Its direct URL is unavailable; consolidated Tumbuh source/releases remain. Current supported checks still cover native Android and website hygiene;
Flutter, other types and unqualified projects need further checker work.

Report status is NOT CLEAN for failures, INCOMPLETE for skips/reviews, WARNINGS for
warnings alone, and CLEAN only when none of those remain. Historical author metadata
is not repaired by a correctly attributed new HEAD; the author check inspects HEAD only.
