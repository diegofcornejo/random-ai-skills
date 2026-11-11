#!/usr/bin/env python3
"""View, replace and diff secret-bearing lines without ever printing the secret value.

Usage: secret_redact.py show PATH START END --commit SHA [--start-column C --end-column C]
       secret_redact.py replace PATH START END --commit SHA     (replacement text on stdin)
       secret_redact.py diff [--cached | --commit REV] [PATH ...]

--commit SHA (required for show/replace) is the `commit_sha` of the alert location. Before printing or
writing anything, lines START..END of the working file must be byte-identical to the same lines of
PATH at SHA (read with `git cat-file blob`, no textconv); otherwise the location is stale and the
command prints only a JSON error.

show     Prints only the alert's lines START..END, never their content: each becomes
         `PATH:N: [line redacted: secret-bearing]`. The one exception is a single-line location with
         known columns: that line is shown with exactly the column span replaced by `[redacted]`
         (the rest of the line is additionally masked). No context lines are printed.
replace  Swaps lines START..END for stdin, byte for byte; every other byte of the file is untouched.
diff     Prints only the structure of `git diff`/`git show` (files, hunk ranges, line numbers).
         Changed lines are never printed. Fails closed on any output it cannot parse, and refuses
         merge commits.
Lines are counted like git: split on "\\n" only.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REDACTED_LINE = "[line redacted: secret-bearing]"
REMOVED_LINE = "[line redacted: removed]"
ADDED_LINE = "[line redacted: added in a secret-bearing file]"
GIT_SAFE = ["--no-color", "--no-ext-diff", "--no-textconv", "-U0", "--inter-hunk-context=0",
            "--src-prefix=a/", "--dst-prefix=b/"]
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
STALE_HINT = "re-run analyze_repo.py or ask the developer to locate the secret"
_QUOTED = re.compile(r"""(["'`])(?:(?!\1).)*\1""")
_ASSIGNED = re.compile(r"""([:=]\s*)(?!["'`\[])[^\s,;)}\]]+""")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/_.=-]{16,}")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def mask(text):
    """Extra masking for the visible remainder of a span-masked line (never the only protection)."""
    text = _QUOTED.sub(r"\1[redacted]\1", text)
    text = _ASSIGNED.sub(r"\1[redacted]", text)
    return _LONG_TOKEN.sub("[redacted]", text)


def _lines(data):
    """Split bytes like git does: on b"\\n" only. Returns (lines, had_trailing_newline)."""
    parts = data.split(b"\n")
    trailing = data.endswith(b"\n")
    return (parts[:-1] if trailing else parts), trailing


def _text(raw):
    return raw.rstrip(b"\r").decode("utf-8", errors="replace")


def _span_masked(raw, start_col, end_col):
    """Replace the alert's column span (covers 0/1-based, inclusive/exclusive) and mask the rest."""
    lo, hi = max(0, start_col - 1), end_col + 1
    if start_col < 0 or end_col < start_col or lo >= len(raw):
        return None
    return mask(_text(raw[:lo])) + "[redacted]" + mask(_text(raw[hi:]))


def show(path, start, end, start_col=None, end_col=None):
    with open(path, "rb") as f:
        lines, _ = _lines(f.read())
    if not 1 <= start <= end <= len(lines):
        raise ValueError(f"lines {start}-{end} out of range (file has {len(lines)} lines)")
    out = []
    for n in range(start, end + 1):
        text = None
        if start == end and start_col is not None and end_col is not None:
            text = _span_masked(lines[n - 1], start_col, end_col)
        out.append(f"{path}:{n}: {text if text is not None else REDACTED_LINE}")
    return "\n".join(out)


def replace(path, start, end, new_bytes):
    with open(path, "rb") as f:
        lines, trailing = _lines(f.read())
    if not 1 <= start <= end <= len(lines):
        raise ValueError(f"lines {start}-{end} out of range (file has {len(lines)} lines)")
    cr = b"\r" if lines[start - 1].endswith(b"\r") else b""
    body = new_bytes[:-1] if new_bytes.endswith(b"\n") else new_bytes
    new_lines = [ln.rstrip(b"\r") + cr for ln in body.split(b"\n")]
    lines[start - 1:end] = new_lines
    with open(path, "wb") as f:
        f.write(b"\n".join(lines) + (b"\n" if trailing else b""))
    return {"path": path, "replaced": [start, end], "new_lines": len(new_lines)}


class DiffFormatError(ValueError):
    pass


def redact_diff(diff_text):
    """Structure-only rendering of a -U0 unified diff. Never emits the content of a changed line."""
    out, removed, added = [], 0, 0
    lines = diff_text.split("\n")
    i, path = 0, None
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            out.append(line)
            path = None
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@", "diff --git ")):  # file header block
                hdr = lines[i]
                if hdr.startswith("+++ ") and hdr[4:] != "/dev/null":
                    path = hdr[4:].split("/", 1)[1] if hdr[4:].startswith("b/") else hdr[4:]
                elif hdr.startswith("--- ") and path is None and hdr[4:] != "/dev/null":
                    path = hdr[4:].split("/", 1)[1] if hdr[4:].startswith("a/") else hdr[4:]
                elif hdr.startswith("Binary files"):
                    out.append("binary change [content redacted]")
                i += 1
            continue
        if line.startswith("@@"):
            m = _HUNK.match(line)
            if not m or path is None:
                raise DiffFormatError("unsupported diff format (merge commit or unexpected header)")
            old_start, new_start = int(m.group(1)), int(m.group(3))
            old_n = int(m.group(2)) if m.group(2) is not None else 1
            new_n = int(m.group(4)) if m.group(4) is not None else 1
            out.append(f"@@ -{old_start},{old_n} +{new_start},{new_n} @@")
            i += 1
            seen_old = seen_new = 0
            while seen_old < old_n or seen_new < new_n:
                if i >= len(lines):
                    raise DiffFormatError("truncated hunk")
                body = lines[i]
                if body.startswith("\\"):  # "\ No newline at end of file"
                    i += 1
                    continue
                if body.startswith("-") and seen_old < old_n:
                    out.append(f"{path}:-{old_start + seen_old}: {REMOVED_LINE}")
                    seen_old += 1
                    removed += 1
                elif body.startswith("+") and seen_new < new_n:
                    out.append(f"{path}:+{new_start + seen_new}: {ADDED_LINE}")
                    seen_new += 1
                    added += 1
                else:
                    raise DiffFormatError("unexpected line inside a hunk (context lines are not allowed)")
                i += 1
            while i < len(lines) and lines[i].startswith("\\"):
                i += 1
            continue
        if line.strip():
            raise DiffFormatError("unexpected line outside a file section")
        i += 1
    out.append(f"{removed} removed, {added} added line(s); content redacted")
    return "\n".join(out)


class StaleLocationError(ValueError):
    pass


def verify_location(path, start, end, commit, runner=subprocess.run):
    """Refuse unless lines START..END of PATH equal the same lines at COMMIT. Prints nothing."""
    sha7 = (commit or "")[:7]
    if not commit or not _SHA.match(commit):
        raise StaleLocationError("missing or invalid --commit (use the alert location's commit_sha)")
    p = Path(path).resolve()
    try:
        current, _ = _lines(p.read_bytes())
    except OSError:
        raise StaleLocationError(f"alert location file not found: {path}")
    proc = runner(["git", "-C", str(p.parent), "cat-file", "blob", f"{commit}:./{p.name}"], capture_output=True)
    if proc.returncode != 0:
        raise StaleLocationError(f"alert location not found at {sha7}: unknown commit or path")
    old, _ = _lines(proc.stdout)
    if end > len(old) or end > len(current) or old[start - 1:end] != current[start - 1:end]:
        raise StaleLocationError(f"alert location is stale: file changed since {sha7}")


def _fail(msg, hint):
    print(json.dumps({"error": msg, "hint": hint}))
    print(f"error: {msg}", file=sys.stderr)
    return 2


def main(argv=None, runner=subprocess.run, stdin=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("path")
    s.add_argument("start", type=int)
    s.add_argument("end", type=int)
    s.add_argument("--commit", required=True, metavar="SHA", help="the alert location's commit_sha")
    s.add_argument("--start-column", type=int)
    s.add_argument("--end-column", type=int)
    r = sub.add_parser("replace")
    r.add_argument("path")
    r.add_argument("start", type=int)
    r.add_argument("end", type=int)
    r.add_argument("--commit", required=True, metavar="SHA", help="the alert location's commit_sha")
    d = sub.add_parser("diff")
    g = d.add_mutually_exclusive_group()
    g.add_argument("--cached", action="store_true")
    g.add_argument("--commit", metavar="REV")
    d.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    try:
        if args.cmd in ("show", "replace"):
            if not 1 <= args.start <= args.end:
                raise ValueError(f"bad line range {args.start}-{args.end}")
            verify_location(args.path, args.start, args.end, args.commit, runner)
        if args.cmd == "show":
            print(show(args.path, args.start, args.end, args.start_column, args.end_column))
        elif args.cmd == "replace":
            data = (stdin or sys.stdin.buffer).read()
            print(json.dumps(replace(args.path, args.start, args.end, data), sort_keys=True))
        else:
            if args.commit:
                if args.commit.startswith("-"):
                    raise ValueError(f"invalid revision {args.commit!r}")
                merge = runner(["git", "rev-parse", "--verify", "--quiet", f"{args.commit}^2"], capture_output=True)
                if merge.returncode == 0:
                    return _fail("merge commits are not supported", "pass a non-merge commit, or check each parent's diff")
                git = ["git", "show", "--format=", "--no-notes"] + GIT_SAFE + [args.commit]
            else:
                git = ["git", "diff"] + GIT_SAFE + (["--cached"] if args.cached else [])
            proc = runner(git + ["--"] + args.paths, capture_output=True)
            if proc.returncode != 0:
                first = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[:1]
                return _fail(first[0] if first else "git failed", "run it inside the repo with a valid revision")
            print(redact_diff(proc.stdout.decode("utf-8", errors="replace")))
    except StaleLocationError as e:
        return _fail(str(e), STALE_HINT)
    except DiffFormatError as e:
        return _fail(str(e), "nothing was printed; use git diff --stat and describe the change instead")
    except (OSError, ValueError) as e:
        return _fail(str(e), "check the path and the line numbers from the alert's locations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
