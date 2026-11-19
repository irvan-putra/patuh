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
adaptive/custom icon renders correctly on a launcher. Those stay REVIEW
items for a human with screenshots. fae's approved photo icon is such a
declared exception. CLEAN only means every check that ran passed; skipped
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

`.github/workflows/patuh.yml` runs the checker on demand and weekly against
the registry. To use patuh from an app's own repo, pin a tag and call it
before a release build; do not wire every repo at once — each wiring is its
own small reviewed change.

```yaml
- uses: actions/checkout@v4
  with: { repository: irvan-putra/patuh, ref: v0.1.0, path: patuh }
- run: pip install pillow==12.3.0
- run: python3 patuh/patuh.py --only myapp --workdir patuh-clones
```

## Scope

This repo checks the projects listed in its own registry. It does not run
against or change any repo by itself.
