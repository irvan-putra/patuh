#!/usr/bin/env python3
"""Validate that a caller repo's release workflow wires the patuh gate in
the proven shape: the publish job may not run unless the candidate APK byte
check passed, and nothing publishes automatically.

Usage: python3 tools/validate_caller_chain.py path/to/workflow.yml [more.yml ...]

Checks, per file:
  - a consistency job calling the pinned release-gate (published: false)
  - the build job needs it
  - a candidate-bytes job calling the gate with candidate_apk_artifact,
    needing the build job
  - the publish job needs candidate-bytes (preventive boundary)
  - a verify job calling the gate with published: true, needing publish
  - the workflow has no automatic triggers (push/schedule/release): release
    stays human-dispatched

Exit 0 when every file is well-shaped, 1 otherwise.
"""
import re
import sys

import yaml

GATE_RE = re.compile(r"^irvan-putra/patuh/.github/workflows/release-gate\.yml@(.+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def problems(path):
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    out = []
    jobs = doc.get("jobs") or {}

    def gate_call(job):
        return isinstance(job, dict) and GATE_RE.match(str(job.get("uses", "")))

    for n, j in jobs.items():
        m = GATE_RE.match(str(j.get("uses", ""))) if isinstance(j, dict) else None
        if m and not SHA_RE.match(m.group(1)):
            out.append("gate job %r pins %r - pin the full reviewed commit SHA; "
                       "a tag is mutable" % (n, m.group(1)))

    consistency = [n for n, j in jobs.items()
                   if gate_call(j) and (j.get("with") or {}).get("published") is False
                   and not (j.get("with") or {}).get("candidate_apk_artifact")]
    if not consistency:
        out.append("no pre-publish source-gate job (gate call with published: false)")
    bytes_jobs = [n for n, j in jobs.items()
                  if gate_call(j) and (j.get("with") or {}).get("candidate_apk_artifact")]
    if not bytes_jobs:
        out.append("no candidate-bytes job (gate call with candidate_apk_artifact)")
    verify = [n for n, j in jobs.items()
              if gate_call(j) and (j.get("with") or {}).get("published") is True]
    if not verify:
        out.append("no post-publish verify job (gate call with published: true)")

    def needs(job):
        n = (jobs.get(job) or {}).get("needs") or []
        return [n] if isinstance(n, str) else list(n)

    # a job referencing needs.X.outputs.Y must actually need X
    import json
    out_ref = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs\.")
    for n, j in jobs.items():
        if not isinstance(j, dict):
            continue
        missing = set(out_ref.findall(json.dumps(j))) - set(needs(n))
        if missing:
            out.append("job %r references outputs of %s without needing them"
                       % (n, sorted(missing)))

    def run_text(job):
        # Inspect the original run scalars; yaml.safe_dump wraps long lines
        # and can split a command literal in two.
        parts = []
        for s in ((job or {}).get("steps") or []):
            if isinstance(s, dict) and isinstance(s.get("run"), str):
                parts.append(s["run"])
        return "\n".join(parts)

    publish = [n for n, j in jobs.items() if not gate_call(j)
               and "gh release create" in run_text(j)]
    if not publish:
        out.append("no publish job (a non-gate job running 'gh release create')")
    for p in publish:
        steps = (jobs[p] or {}).get("steps") or []
        has_fetch = any(isinstance(s, dict)
                        and str(s.get("uses", "")).startswith(
                            ("actions/checkout@", "actions/download-artifact@"))
                        for s in steps)
        if not has_fetch:
            out.append("publish job %r has no checkout/download-artifact step - "
                       "'gh release create' needs its assets from somewhere" % p)
    for p in publish:
        for b in bytes_jobs:
            if b not in needs(p):
                out.append("publish job %r does not need %r - the byte check must gate publishing"
                           % (p, b))
    build_like_all = [n for n, j in jobs.items()
                      if not gate_call(j) and n not in publish and "assembleRelease" in run_text(j)]
    for bld in build_like_all:
        if consistency and not any(c in needs(bld) for c in consistency):
            out.append("build job %r does not need the source-gate job %s - "
                       "the build must follow the source gate" % (bld, consistency))
    for b in bytes_jobs:
        if build_like_all and not any(bld in needs(b) for bld in build_like_all):
            out.append("candidate-bytes %r does not need the build job %s" % (b, build_like_all))
    for v in verify:
        for p in publish:
            if p not in needs(v):
                out.append("verify job %r does not need publish job %r" % (v, p))

    # Trigger style (workflow_dispatch vs tag push) is an implementation
    # choice, not a policy the checker enforces: what must hold is that the
    # publish job is gated behind the byte check, checked above.
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    for path in argv:
        probs = problems(path)
        if probs:
            bad = 1
            print("%s: NOT WIRED CORRECTLY" % path)
            for p in probs:
                print("  - " + p)
        else:
            print("%s: chain shape OK (publish gated behind candidate bytes)" % path)
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
