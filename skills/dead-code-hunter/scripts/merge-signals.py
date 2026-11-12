#!/usr/bin/env python3
"""Merge dead-code signals into one compact, deterministic candidate list.

Read-only. Inputs are files the caller already produced (outside the project):

  --knip FILE        output of `knip --reporter json` (default mode)
  --knip-prod FILE   output of `knip --production --reporter json`
  --tsc FILE         output of `tsc --noEmit --pretty false --noUnusedLocals
                     --allowUnreachableCode false ...` (repeatable)
  --scope PREFIX     keep only candidates under this path (repeatable)
  --grep             count references with `git grep` for each candidate
  --max N            cap the candidate list (counts stay exact)

Run it with the project root as the working directory: paths in knip/tsc
output are relative to it, and `git grep` searches from it.

stdout: JSON {"summary": ..., "candidates": [...], "notes": [...]}
stderr: progress messages.
"""
import argparse
import json
import os
import re
import subprocess
import sys

TEST_RE = re.compile(r"(\.(test|spec|stories|story)\.[cm]?[jt]sx?$|(^|/)(__tests__|__mocks__|tests?|e2e)/)")
TSC_RE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): error TS(?P<code>\d+): (?P<msg>.*)$")
QUOTED_RE = re.compile(r"'([^']+)'")

# knip issue key -> candidate kind. Keys absent here are reported as notes.
KNIP_KINDS = {
    "files": "orphan-file",
    "dependencies": "unused-dependency",
    "devDependencies": "unused-dependency",
    "optionalPeerDependencies": "unused-dependency",
    "exports": "unused-export",
    "nsExports": "unused-export",
    "types": "unused-type",
    "nsTypes": "unused-type",
    "enumMembers": "unused-member",
    "namespaceMembers": "unused-member",
    "classMembers": "unused-member",  # knip <= 5
    "catalog": "unused-catalog-entry",
}
# Not dead code, but they explain false positives (missing plugin, broken alias...).
KNIP_NOTES = ("unlisted", "binaries", "unresolved", "duplicates", "catalogReferences", "subpaths")

TSC_KINDS = {
    "6133": "unused-local",   # declared but its value is never read
    "6138": "unused-local",   # property declared but never read
    "6192": "unused-import",  # all imports in import declaration are unused
    "6196": "unused-local",   # declared but never used (types)
    "6198": "unused-local",   # all destructured elements are unused
    "6199": "unused-local",   # all variables are unused
    "6205": "unused-local",   # all type parameters are unused
    "7027": "unreachable-code",
    "7028": "unreachable-code",  # unused label
}


def log(msg):
    print(msg, file=sys.stderr)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        raise SystemExit(f"error: {path} is empty (did knip exit with code 2?)")
    # knip may print warnings before the JSON document.
    start = text.find("{")
    if start < 0:
        raise SystemExit(f"error: {path} has no JSON object")
    return json.loads(text[start:])


def iter_knip(doc):
    """Yield (key, file, item) from knip JSON, v5 and v6 layouts."""
    for name in doc.get("files", []) or []:  # knip <= 5: top-level list of paths
        yield "files", name, {"name": name}
    for issue in doc.get("issues", []) or []:
        file = issue.get("file", "")
        for key, value in issue.items():
            if key in ("file", "owners"):
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        item = {"name": item}
                    if key == "files":
                        yield key, item.get("name", file), item
                    else:
                        yield key, file, item
            elif isinstance(value, dict):  # knip <= 5: {"EnumName": [{name...}]}
                for parent, members in value.items():
                    for item in members if isinstance(members, list) else members.values():
                        item = dict(item) if isinstance(item, dict) else {"name": str(item)}
                        item["name"] = f"{parent}.{item.get('name', '')}"
                        yield key, file, item


def knip_candidates(doc, signal, notes):
    out = []
    for key, file, item in iter_knip(doc):
        name = item.get("name", "")
        if key in KNIP_NOTES:
            notes.setdefault(f"knip:{key}", []).append(f"{file}: {name}" if file else name)
            continue
        kind = KNIP_KINDS.get(key)
        if not kind:
            continue
        if kind == "orphan-file":
            file, name = name, "<file>"
            if TEST_RE.search(file):
                kind = "orphan-test"
        extra = {"field": key} if kind == "unused-dependency" else {}
        out.append(dict(kind=kind, file=file, line=item.get("line"), name=name, signal=signal, **extra))
    return out


def source_line(file, line):
    try:
        with open(file, encoding="utf-8", errors="replace") as fh:
            for i, text in enumerate(fh, 1):
                if i == line:
                    return text
    except OSError:
        pass
    return ""


def tsc_candidates(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = TSC_RE.match(raw.strip())
            if not m or m["code"] not in TSC_KINDS:
                continue
            file = os.path.relpath(m["file"]) if os.path.isabs(m["file"]) else m["file"]
            line = int(m["line"])
            kind = TSC_KINDS[m["code"]]
            q = QUOTED_RE.search(m["msg"])
            name = q.group(1) if q else ("<code>" if kind == "unreachable-code" else "<all>")
            if kind == "unused-local" and source_line(file, line).lstrip().startswith("import"):
                kind = "unused-import"
            out.append(dict(kind=kind, file=file, line=line, name=name, signal=f"tsc:TS{m['code']}"))
    return out


def in_scope(file, scopes):
    if not scopes:
        return True
    norm = file[2:] if file.startswith("./") else file
    return any(norm == s or norm.startswith(s.rstrip("/") + "/") for s in scopes)


def merge(cands):
    merged = {}
    for c in cands:
        key = (c["kind"], c["file"], c["name"])
        cur = merged.get(key)
        if cur is None:
            cur = merged[key] = {k: v for k, v in c.items() if k != "signal"}
            cur["signals"] = []
        if c["signal"] not in cur["signals"]:
            cur["signals"].append(c["signal"])
        if cur.get("line") is None and c.get("line") is not None:
            cur["line"] = c["line"]
    return list(merged.values())


def grep_term(c):
    """What to search for to prove a candidate is still referenced somewhere."""
    if c["kind"] in ("orphan-file", "orphan-test"):
        stem = os.path.splitext(c["file"])[0]
        parts = stem.split("/")
        if parts[-1] == "index" and len(parts) > 1:
            parts = parts[:-1]
        return "/".join(parts[-2:]) if len(parts) > 1 else parts[-1]
    if c["kind"] == "unreachable-code" or c["name"].startswith("<"):
        return None
    return c["name"].split(".")[-1]


# Build output and vendored code produce false "it's used" hits even when committed.
GREP_EXCLUDES = [":(exclude,glob)**/" + d + "/**" for d in
                 ("node_modules", "dist", "build", ".next", ".nuxt", ".output", "coverage", ".turbo", "out")]
LOCKFILE_RE = re.compile(r"^[^:]*(package\.json|pnpm-lock\.yaml|yarn\.lock|package-lock\.json|bun\.lockb?|npm-shrinkwrap\.json):")
LOCAL_KINDS = ("unused-import", "unused-local")


def git_grep(term, paths, word):
    cmd = ["git", "grep", "-n", "-I", "-F"] + (["-w"] if word else []) + ["-e", term, "--"] + paths
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode not in (0, 1):
        return None
    return [ln for ln in res.stdout.splitlines() if ln]


def add_refs(c):
    """Attach `refs` (other mentions) and up to 3 `ref_samples` to a candidate."""
    term = grep_term(c)
    if not term:
        return
    kind = c["kind"]
    if kind in LOCAL_KINDS:
        # Only the own module matters; drop the declaration line itself.
        hits = git_grep(term, [c["file"]], word=True)
        if hits is not None:
            hits = [h for h in hits if not h.startswith(f"{c['file']}:{c.get('line')}:")]
    elif kind == "unused-dependency":
        hits = git_grep(term, ["."] + GREP_EXCLUDES, word=False)
        if hits is not None:  # the manifest and lockfiles always mention the package
            hits = [h for h in hits if not LOCKFILE_RE.match(h)]
    elif kind in ("orphan-file", "orphan-test"):
        hits = git_grep(term, ["."] + GREP_EXCLUDES, word="/" not in term)
        if hits is not None:
            hits = [h for h in hits if not h.startswith(c["file"] + ":")]
    else:
        hits = git_grep(term, ["."] + GREP_EXCLUDES + [f":(exclude){c['file']}"], word=True)
    if hits is None:
        return
    c["refs"] = len(hits)
    c["ref_samples"] = [h[:160] for h in hits[:3]]
    # Every mention lives in a test file: alive only for the tests.
    if hits and kind not in LOCAL_KINDS + ("orphan-test",) and all(TEST_RE.search(h.split(":", 1)[0]) for h in hits):
        c["test_only"] = True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--knip")
    ap.add_argument("--knip-prod")
    ap.add_argument("--tsc", action="append", default=[])
    ap.add_argument("--scope", action="append", default=[])
    ap.add_argument("--grep", action="store_true")
    ap.add_argument("--max", type=int, default=300)
    args = ap.parse_args(argv)
    if not (args.knip or args.knip_prod or args.tsc):
        ap.error("give at least one of --knip, --knip-prod, --tsc")

    notes, cands = {}, []
    default_keys = set()
    if args.knip:
        found = knip_candidates(load_json(args.knip), "knip", notes)
        default_keys = {(c["kind"], c["file"], c["name"]) for c in found}
        cands += found
    if args.knip_prod:
        prod_notes = {}
        for c in knip_candidates(load_json(args.knip_prod), "knip:production", prod_notes):
            # Dead in production but alive in the default run => used only by tests/tooling.
            if args.knip and (c["kind"], c["file"], c["name"]) not in default_keys:
                c["test_only"] = True
            cands.append(c)
        if not args.knip:
            notes.update(prod_notes)
    for path in args.tsc:
        cands += tsc_candidates(path)

    cands = [c for c in merge(cands) if in_scope(c["file"], args.scope)]
    cands.sort(key=lambda c: (c["kind"], c["file"], c.get("line") or 0, c["name"]))

    if args.grep:
        log(f"git grep for {min(len(cands), args.max)} candidates...")
        for c in cands[: args.max]:
            add_refs(c)

    by_kind = {}
    for c in cands:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    for i, c in enumerate(cands, 1):
        c["id"] = i
    result = {
        "summary": {
            "total": len(cands),
            "shown": min(len(cands), args.max),
            "by_kind": dict(sorted(by_kind.items())),
            "inputs": {"knip": bool(args.knip), "knip_prod": bool(args.knip_prod), "tsc": len(args.tsc)},
            "scope": args.scope or ["<repo root>"],
        },
        "candidates": cands[: args.max],
        "notes": [{"type": k, "count": len(v), "examples": v[:5]} for k, v in sorted(notes.items())],
    }
    json.dump(result, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
