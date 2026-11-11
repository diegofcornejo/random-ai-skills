# Playbook — npm, Yarn, pnpm

For Dependabot alerts with `ecosystem: npm` in JavaScript/TypeScript projects (Angular packages also follow [angular.md](angular.md)).

## 1. Identify the package manager

| Evidence | Manager | Notes |
|----------|---------|-------|
| `package-lock.json` or `npm-shrinkwrap.json` | npm | `overrides` needs npm ≥ 8.3 |
| `yarn.lock` without `.yarnrc.yml` | Yarn 1 (classic) | `resolutions` |
| `yarn.lock` with `.yarnrc.yml` | Yarn 2+ (Berry) | `resolutions`, `yarn up -R` |
| `pnpm-lock.yaml` | pnpm | `pnpm.overrides` in `package.json` |
| `packageManager` field in `package.json` | the one named (and its version) | Wins over guessing |

Use only the manager the repo already uses. Never mix lockfiles, never delete a lockfile to "start fresh".

## 2. Direct or transitive

The alert's `relationship` says it; confirm before acting.

```bash
npm ls <pkg> --all        # npm (needs node_modules); or: npm explain <pkg>
yarn why <pkg>            # Yarn 1 and 2+
pnpm why <pkg>            # pnpm
```

Without `node_modules`, read the lockfile: npm lockfile v2/v3 lists `"node_modules/<pkg>"` (top level) and `"node_modules/<parent>/node_modules/<pkg>"` (nested) with their `version`; `yarn.lock` and `pnpm-lock.yaml` list every resolved `<pkg>@<range>`.

Record: the installed version(s), who pulls it in (the parent chain), and each parent's **declared range** for the package.

## 3. When a bump implies a major

Compare the **installed** version with `first_patched`:

- `4.17.20 → 4.17.21`: patch, `direct-bump` or in-range transitive refresh, low.
- `4.1.0 → 4.6.2`: minor, medium if it is at ≥ 1.0.
- `3.x → 4.x`: **major**, `major-upgrade`: read the package's changelog/release notes for breaking changes and list them as fix-risk factors.
- `0.3.x → 0.4.x`: semver treats a `0.x` minor as breaking: major-upgrade.
- Transitive where the only fixed line requires a **new major of the parent**: the fix is upgrading the parent, a major-upgrade of the parent.

## 4. Direct dependency fixes

Keep the existing range style (`^`, `~`, exact) of `package.json`. The commands below write the manager's default prefix (`^`): add `--save-exact` (npm) / `--exact` (Yarn) for exact pins; for pnpm exact pins and for `~` ranges, edit the range in `package.json` and refresh the lockfile instead.

| Manager | Command |
|---------|---------|
| npm | `npm install <pkg>@<version>` (updates `package.json` and the lockfile) |
| Yarn 1 | `yarn upgrade <pkg>@<version>` |
| Yarn 2+ | `yarn up <pkg>@<version>` |
| pnpm | `pnpm update <pkg>@<version>` |

Check `devDependencies` vs `dependencies`: keep the package where it is.

## 5. Transitive fixes

Try in this order and stop at the first that works.

### 5.1 In-range lockfile refresh (no manifest change)

If every parent's declared range already accepts the patched version, only the lockfile needs to move:

| Manager | Command |
|---------|---------|
| npm | `npm update <pkg> --package-lock-only` (re-resolves `<pkg>` within the declared ranges and touches only `package-lock.json`; drop the flag to update `node_modules` too) |
| Yarn 1 | No reliable in-range refresh command for a transitive package: use `resolutions` (5.2). With a version inside the parent's range it stays low/medium fix-risk |
| Yarn 2+ | `yarn up -R <pkg>` |
| pnpm | `pnpm update <pkg>`; if `pnpm why` still shows an old copy, use `pnpm.overrides` (5.2) |

Then confirm with `npm ls <pkg>` / `yarn why <pkg>` / `pnpm why <pkg>` that **every** copy is at or above `first_patched`. Nested copies are easy to miss.

### 5.2 Force it with an override

When a parent's range excludes the patched version, pin the transitive version in `package.json`:

```jsonc
// npm (>= 8.3)
"overrides": { "lodash": "4.17.21" }
// npm, only under one parent
"overrides": { "some-parent": { "lodash": "4.17.21" } }
// Yarn 1 and 2+
"resolutions": { "lodash": "4.17.21" }          // Yarn 1 also accepts "**/lodash"
// pnpm (or `overrides:` in pnpm-workspace.yaml when the repo already keeps pnpm settings there)
"pnpm": { "overrides": { "lodash": "4.17.21" } }
```

Then refresh the lockfile: `npm install`, `yarn install`, or `pnpm install`.

Rules:

- An override that stays inside the major the parent declares is medium fix-risk. One that crosses it (parent wants `^3`, you force `4.x`) is high: the parent was never tested with it. Prefer upgrading the parent when a version of the parent already accepts the fix.
- Add the override only for the vulnerable package, never as a blanket pin of unrelated packages.
- Say in the commit body and the plan that the override should be removed once the parent's own range includes the fix.

### 5.3 Upgrade the parent

When a newer parent version depends on the patched package, bump the parent (section 4). If that is a major for the parent, it is a `major-upgrade` block.

## 6. Monorepos

With `workspaces` (npm/Yarn) or `pnpm-workspace.yaml`, run commands from the root and target the workspace (`npm install <pkg>@<v> -w <workspace>`, `yarn workspace <name> up <pkg>@<v>`, `pnpm --filter <name> update <pkg>@<v>`). Overrides/resolutions go in the **root** `package.json`.

## 7. Verify

`npm ci` / `yarn install --frozen-lockfile` (Yarn 1) / `yarn install --immutable` (Yarn 2+) / `pnpm install --frozen-lockfile`, then the project's `test`, `build` and `lint` scripts. Commands per stack are in [../execution.md](../execution.md).
