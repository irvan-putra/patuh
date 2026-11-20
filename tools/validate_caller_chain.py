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

GATE_RE = re.compile(r"^irvan-putra/patuh/.github/workflows/release-gate\.yml@v\d+\.\d+\.\d+$")


def problems(path):
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    out = []
    jobs = doc.get("jobs") or {}

    def gate_call(job):
        return isinstance(job, dict) and GATE_RE.match(str(job.get("uses", "")))

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

    publish = [n for n, j in jobs.items() if not gate_call(j)
               and "gh release create" in yaml.safe_dump(j)]
    if not publish:
        out.append("no publish job (a non-gate job running 'gh release create')")
    for p in publish:
        for b in bytes_jobs:
            if b not in needs(p):
                out.append("publish job %r does not need %r - the byte check must gate publishing"
                           % (p, b))
    for b in bytes_jobs:
        build_like = [n for n, j in jobs.items()
                      if not gate_call(j) and n not in publish and "assembleRelease" in yaml.safe_dump(j)]
        if build_like and not any(bld in needs(b) for bld in build_like):
            out.append("candidate-bytes %r does not need the build job %s" % (b, build_like))
    for v in verify:
        for p in publish:
            if p not in needs(v):
                out.append("verify job %r does not need publish job %r" % (v, p))

    # no automatic release dispatch: the only trigger allowed is workflow_dispatch
    on = doc.get(True, doc.get("on"))  # PyYAML parses the bare key `on` as True
    triggers = set(on) if isinstance(on, dict) else {on}
    auto = triggers - {"workflow_dispatch", None}
    if auto:
        out.append("automatic triggers present %s - releases must stay human-dispatched" % sorted(auto))
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
            print("%s: chain shape OK (publish gated behind candidate bytes, manual dispatch only)" % path)
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
