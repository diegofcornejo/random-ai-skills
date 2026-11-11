#!/usr/bin/env bash
# Repo consistency checks. Run before pushing:  scripts/validate.sh
#  - every skills/<dir>/SKILL.md has `name:` == <dir> and a `description:`
#  - every skill is registered in .claude-plugin/marketplace.json
#  - every path in marketplace.json exists
#  - every skill referenced by an agent ("references/…" of skills/<name>) exists
#  - no obvious secrets are committed
#  - local unit tests pass (when a tests/ folder exists)
#  - `claude plugin validate .` passes (when the claude CLI is installed)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
fail=0
err() { echo "✗ $*" >&2; fail=1; }
ok() { echo "✓ $*" >&2; }

# 1. Skill frontmatter
for skill_md in skills/*/SKILL.md; do
  dir="$(basename "$(dirname "$skill_md")")"
  name="$(awk '/^---$/{n++; next} n==1 && /^name:/{sub(/^name:[[:space:]]*/,""); print; exit}' "$skill_md")"
  desc="$(awk '/^---$/{n++; next} n==1 && /^description:/{print "y"; exit}' "$skill_md")"
  [[ "$name" == "$dir" ]] || err "$skill_md: name '$name' != directory '$dir'"
  [[ "$desc" == "y" ]] || err "$skill_md: missing description"
  lines="$(wc -l < "$skill_md" | tr -d ' ')"
  [[ "$lines" -le 500 ]] || err "$skill_md: $lines lines (keep under ~500)"
done
ok "skill frontmatter checked"

# 2 + 3. Marketplace registration and paths
if [[ -f .claude-plugin/marketplace.json ]]; then
  python3 - <<'PY' || fail=1
import json, os, sys
m = json.load(open(".claude-plugin/marketplace.json"))
bad = False
registered = set()
for p in m.get("plugins", []):
    for key in ("skills", "agents"):
        for path in p.get(key, []):
            if not os.path.exists(path):
                print(f"✗ marketplace: plugin '{p['name']}' {key} path missing: {path}", file=sys.stderr); bad = True
            if key == "skills":
                registered.add(os.path.basename(os.path.normpath(path)))
for d in sorted(os.listdir("skills")):
    if os.path.isfile(os.path.join("skills", d, "SKILL.md")) and d not in registered:
        print(f"✗ marketplace: skill '{d}' is not in any plugin", file=sys.stderr); bad = True
sys.exit(1 if bad else 0)
PY
  ok "marketplace paths checked"
fi

# 4. Agents -> skills they depend on
shopt -s nullglob
for agent in agents/*.md opencode/agents/*.md; do
  for ref in $(grep -oE '[a-z0-9-]+/references/[a-z0-9.-]+\.md' "$agent" | sort -u); do
    [[ -f "skills/$ref" ]] || err "$agent references missing skills/$ref"
  done
done
shopt -u nullglob
ok "agent -> skill references checked"

# 5. Secrets
if git grep -nIE '(ctx7sk-[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})' -- . ':!scripts/validate.sh' >/dev/null 2>&1; then
  err "possible secret committed:"; git grep -nIE '(ctx7sk-|ghp_|AKIA)[A-Za-z0-9]{8,}' -- . ':!scripts/validate.sh' | cut -c1-120 >&2
else
  ok "no obvious secrets"
fi

# 6. Unit tests (local only; tests/ is not distributed)
shopt -s nullglob
for t in tests/*/; do
  if PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$t" >/dev/null 2>&1; then
    ok "unit tests ($t)"
  else
    err "unit tests failed in $t (run: python3 -m unittest discover -s $t)"
  fi
done
shopt -u nullglob

# 7. Claude plugin validation
if command -v claude >/dev/null 2>&1; then
  if claude plugin validate . >/dev/null 2>&1; then ok "claude plugin validate"; else err "claude plugin validate failed (run it for details)"; fi
else
  echo "- claude CLI not found, skipping plugin validation" >&2
fi

[[ $fail -eq 0 ]] && echo "All checks passed." >&2
exit $fail
