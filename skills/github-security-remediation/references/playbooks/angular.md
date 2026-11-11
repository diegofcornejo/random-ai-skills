# Playbook — Angular upgrades

An Angular major-version migration is **never** a routine dependency bump. It is always its own block, and every major hop is a separate block.

## 1. Classify the Angular alert

Read the installed `@angular/core` version (lockfile) and the alert's `first_patched`:

| Jump | Fix type | Fix-risk | Block |
|------|----------|----------|-------|
| Patch in the same major (`11.0.3 → 11.0.5`) | `direct-bump` | low (raise it if tests are missing) | May join the direct-bumps block, but bump **all** `@angular/*` packages together to the same version |
| Minor in the same major (`11.0 → 11.2`) | `direct-bump` | medium | Its own block or the direct-bumps block; all `@angular/*` together |
| Major (`11.x → 12.x` or further) | `major-upgrade` | **high, always** | One block **per major hop** |

All `@angular/*` framework packages (`core`, `common`, `compiler`, `forms`, `router`, `platform-browser`, `animations`, `cli`, `compiler-cli`, `@angular-devkit/*`, …) move together. Never bump only `@angular/core`.

## 2. One major version per step

Angular supports updating **one major at a time**: 11→12→13→…, never 11→14 directly. If the patched version is three majors away, the plan has three blocks (e.g. "5.1 Angular 11→12", "5.2 Angular 12→13", "5.3 Angular 13→14"), each verified and committed separately. Alerts closed only by the last hop are listed on that block; blocks in between say "intermediate step".

## 3. Read the official update guide for the from/to pair

For each hop, read the guide for that exact pair:

- `https://angular.dev/update-guide?v=<N>.0-<N+1>.0&l=3` (all steps, "advanced" level);
- if that page cannot be rendered by your tools, ask the developer to open it and paste the checklist, or read the breaking-change section for `<N+1>.0.0` in the Angular changelog (`https://github.com/angular/angular/blob/main/CHANGELOG.md`);
- `https://angular.dev/reference/versions` for the supported TypeScript, RxJS and Node.js ranges of `<N+1>`.

These are public pages; you only send the version numbers. Never send the project's code anywhere.

List every breaking change that applies to this project as a **fix-risk factor** of the block, with the evidence (e.g. "uses `ViewEngine`-only library `ngx-foo@2`", "22 templates use the removed `xyz` API"). Do not list changes that do not apply.

Well-known landmarks to check for (always confirm them in the guide for the pair you are on):

- v13: View Engine is no longer available for applications; libraries not compiled for Ivy need `ngcc`, and IE11 support is dropped.
- v14: typed reactive forms (`ng update` migrates existing forms to `UntypedFormControl`/`UntypedFormGroup`).
- v15: Angular Material components move to the MDC-based implementation (the old ones remain as `legacy` for a while).
- v16: `ngcc` is removed; libraries still published only in View Engine format stop working.

## 4. The peer cascade

Each hop drags its peers. Check every one against the target's supported ranges and list the required moves as factors:

| Peer | Where to check | Typical impact |
|------|----------------|----------------|
| TypeScript | `typescript` in `package.json` vs the supported range for `<N+1>` | Compiler errors from stricter checks |
| RxJS | `rxjs` vs the supported range | RxJS 6 → 7 changes (`toPromise` deprecated, operator imports) |
| Zone.js | `zone.js` vs the version `ng update` installs | Polyfill import paths |
| Angular Material / CDK | `@angular/material`, `@angular/cdk` must be on the **same major** as `@angular/core` | Visual and API changes; the v15 MDC migration is large |
| Node.js | `engines.node`, `.nvmrc`, CI images vs the Node range for `<N+1>` | CI and local tooling must move first; may be a human-outside-the-repo step |
| Third-party Angular libs | `ngx-*`, `@ng-*`, `@ngrx/*`, `primeng`, `@ng-bootstrap/*`, `angular-*` | Each needs a release compatible with `<N+1>`. A lib without one **blocks the hop**: put the alert under "Will not be fixed now" with that reason, or plan replacing the lib |
| Builders and tooling | `@angular-builders/*`, Karma/Jest config, ESLint (`@angular-eslint/*`) | Must match the target major |

## 5. Run the hop (ask before running)

`ng update` downloads and installs packages, and it requires a clean working tree. **Ask the developer before running it**, every hop.

```bash
git status --porcelain                                                     # must be empty
npx --no-install ng update                                                 # lists the packages that can be updated; changes nothing
npx --no-install ng update @angular/core@<N+1> @angular/cli@<N+1>
npx --no-install ng update @angular/material@<N+1> @angular/cdk@<N+1>    # when Material is used
```

- `--no-install` uses the project's local Angular CLI; it never installs a global CLI. If the local CLI is missing, the project's dependencies are not installed: run the project's install first (with the permission from execution step 0), never `npm install -g @angular/cli`.
- `ng update` runs the migrations (schematics) for the hop and prints what it changed. Keep that output: summarize it for the developer.
- If `ng update` refuses because of peer conflicts, report the conflict. Do not add `--force` without the developer's explicit approval, and say what `--force` skips.
- Third-party libraries: update each to its release for `<N+1>` (with `ng update <lib>` when the lib supports it, otherwise the package manager).

## 6. After `ng update`

1. Show `git diff --stat` and the migrations' summary.
2. Build: `npx --no-install ng build`. Fix compile errors as **application code changes**: show each proposed edit and ask (execution.md, "always ask first").
3. Test: `npx --no-install ng test --watch=false` (add `--browsers=ChromeHeadless` when the Karma config supports it), and lint if configured.
4. Commit the hop as one commit, e.g. `chore(angular): update to Angular <N+1> (block 5.1)`.
5. Only then start the next hop.

## 7. In the plan

An Angular block always shows:

- **Fix-risk: high** (unless it is a patch within the same major), with the factors: from → to versions and the intermediate hops; TypeScript/RxJS/Zone.js/Material/Node moves; third-party libs that need new releases (and any that have none); the applicable breaking changes from the update guide; the number of affected files; the tests available.
- **Effort**: usually M or L per hop; L when Material moves to MDC or many third-party libs move.
- **Who acts**: agent (runs `ng update` after approval) + developer (approves every code edit) + human outside the repo when Node/CI images must change.
- The alerts it closes, and the alerts **blocked by it** in "Will not be fixed now" (e.g. a library fix that needs Angular 12).
