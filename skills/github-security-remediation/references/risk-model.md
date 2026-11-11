# Risk Model

Two separate axes. **Do not blend them into one score.**

| Axis | Question it answers | Who computes it | Used for |
|------|---------------------|-----------------|----------|
| **Priority** | How urgent is the vulnerability? | `score.py`, deterministically | Block order, waves, top-risk repos |
| **Fix-risk** | What does applying the fix imply? | You (or the subagent), with the rubric below | Shown on every block, tie-break inside equal priority |

## 1. Priority (computed by `score.py`, never by you)

Every alert in `analyze_repo.py` / `snapshot.json` output already carries `priority` (0–100) and `band` (`P1`/`P2`/`P3`). **Copy them. Never recompute, round, adjust or "correct" them**, even if you disagree; explain your view in prose instead. The same weights are printed in the report's methodology section and in `snapshot.json` under `methodology`, so every number is auditable.

`METHODOLOGY` as defined in `scripts/score.py`:

```python
METHODOLOGY = {
    "severity_base": {"critical": 40, "high": 30, "medium": 20, "low": 10, "unknown": 15},
    "secret": {"base": 60, "active": 25, "publicly_leaked": 15, "push_protection_bypassed": 10},
    "dependabot": {"epss_percentile": [[95, 25], [80, 15], [50, 5]], "scope": {"runtime": 10, "development": -10},
                   "relationship": {"direct": 5}},
    "code_scanning": {"classification_penalty": {"classifications": ["test", "generated"], "points": -15}},
    "activity": {"within_30_days": 10, "within_180_days": 5},
    "clamp": [0, 100],
    "bands": {"P1": 70, "P2": 40, "P3": 0},
    "clusters": "open Dependabot alerts grouped by ecosystem:package:advisory (and angular:<major>), kept when they span >= 2 repos",
    "ranking": "per repo with coverage, sorted by (-max_priority, -p1_count, -open, repo)",
    "waves": {"1": "all open secrets plus every P1", "2": "alerts in clusters with >= 5 repos, plus P2",
              "3": "the rest"},
}
```

How to read it (for explanations to the user, in their language):

- **Secret scanning**: base 60 instead of the severity base, +25 if `validity` is `active`, +15 if `publicly_leaked`, +10 if `push_protection_bypassed`.
- **Dependabot**: severity base, plus the first matching EPSS bonus (percentile ≥95: +25, ≥80: +15, ≥50: +5), runtime scope +10 or development −10, direct dependency +5.
- **Code scanning**: severity base from `security_severity_level`, −15 when the location is classified `test` or `generated`.
- **Every source**: +10 if the repo was pushed within 30 days, +5 within 180 days (a proxy for production use).
- Clamped to 0–100. Band: P1 ≥ 70, P2 ≥ 40, otherwise P3.
- **Exposed secrets always go first** in a plan and in wave 1, whatever their band.

## 2. Fix-risk (what applying the fix implies)

Every block states one level, `low`, `medium` or `high`, **and the concrete factors that justify it**. The block's level is the **highest** level among its factors. Never average. A factor that does not apply is simply not listed.

### Rubric

| Factor | low | medium | high |
|--------|-----|--------|------|
| **Semver jump** (installed → target) | Patch (`1.2.3 → 1.2.9`) | Minor (`1.2 → 1.5`) at ≥ 1.0 | Major (`1.x → 2.x`), or a minor jump on `0.x` (`0.3 → 0.4`), or several minors with a documented deprecation removal |
| **Direct vs transitive** | Direct dependency bumped inside its range, or a transitive refresh that the parent's declared range already accepts (lockfile-only) | Transitive forced with `overrides`/`resolutions`/`pnpm.overrides`/`composer update --with-dependencies` while staying in the same major the parent asks for | Forced transitive that crosses the major the parent declares, or the fix requires upgrading the parent across a major |
| **Framework major upgrade (Angular)** | Patch within the same major (`11.0.3 → 11.0.5`) | Minor within the same major (`11.0 → 11.2`) | Any major hop (`11 → 12`). Always high. List the intermediate versions, the `ng update` migrations, the peer cascade (TypeScript, RxJS, Zone.js, Angular Material/CDK, third-party Angular libs) and the breaking changes from the official update guide as factors |
| **Files and code that must change** | Only manifests and lockfiles | 1–5 application files, or config/build files (`angular.json`, `tsconfig*.json`, `composer.json` scripts) | More than 5 application files, template/API migrations, public API changes, or changes across modules owned by other teams |
| **Test coverage available** | A test suite exists, its baseline passes, and it exercises the changed area | Tests exist but do not cover the changed area, or the baseline is flaky | No tests, the baseline already fails, or the tests cannot run locally (missing browser, services, DB) |
| **PHP platform constraints** | The patched version supports the current `require.php` and `config.platform.php`, and needs no new extension | The patched version needs a new `ext-*` already available in the runtime image, or a raise of `config.platform.php` within what production already runs | The patched version needs a higher minimum PHP than production runs, or an extension that is not installed: an infrastructure change outside the repo |
| **Secret rotation** (consumers to update; secret-scanning alerts and code-scanning credential alerts) | Credential unused, or only used by the developer locally | Known consumers that one person can update in one window (CI secret, one service) | Unknown consumers, shared across systems or teams, or production traffic depends on it with no overlap period |
| **Code-scanning fix** | Local change in one function, behaviour preserved, a test can pin it | Changes a shared helper or the input validation of an endpoint | Changes an authentication/authorization path or the data model, or needs a design decision |

### Code that can't be inspected

A block is never "unrated". If the code a fix touches can't be inspected (file missing, binary, outside the checkout), rate the block **high** and list the factor `source not available for inspection: <path>`.

### Writing the factors

Write them as short, concrete facts the developer can check, in the user's language:

- good: "major 11→12; requires TypeScript 4.2 (installed 4.0.5); `@angular/material` 11 must move to 12; 37 `*.spec.ts` files, baseline passing";
- bad: "might break things", "complex upgrade", "some risk".

### Fix-risk and ordering

Fix-risk is one of the keys that order the plan's blocks. The rule is defined once, in [plan-format.md](plan-format.md#block-ordering-rule). A high fix-risk never lowers priority: a P1 alert behind an Angular major upgrade stays P1, and the plan says it is blocked by that upgrade.
