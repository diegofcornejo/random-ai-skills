# Playbook — PHP / Composer

For Dependabot alerts with `ecosystem: composer`.

## 1. Know the platform first

Read `composer.json` and `composer.lock` before proposing anything:

| Field | Meaning for the fix |
|-------|---------------------|
| `require.php` | The PHP versions the project claims to support |
| `config.platform.php` | The PHP version Composer **resolves against** (pins resolution even if the local PHP is newer). Usually mirrors production |
| `require.ext-*` | PHP extensions the project needs |
| `composer.lock` → `platform`, `platform-overrides` | What the lock was resolved with |
| The framework (`laravel/framework`, `symfony/*`, …) | Most PHP alerts sit under the framework's dependency tree |

`composer check-platform-reqs` (local, read-only) compares the lock's requirements with the PHP installed on this machine.

A patched version that needs a higher PHP than production runs, or a missing extension, is a **platform change outside the repo**: high fix-risk, or "Will not be fixed now" with "needs PHP <x.y>" as the reason, and "human outside the repo" in **Who acts**.

## 2. Why is the package installed

```bash
composer why <vendor/pkg>                    # who requires it (alias of composer depends)
composer why-not <vendor/pkg> <version>      # what blocks the patched version
composer show <vendor/pkg>                    # installed version and its requirements
composer show --all <vendor/pkg> <version>   # requirements of the patched version, including php
```

Direct = listed in `require`/`require-dev` of `composer.json`. Everything else is transitive.

## 3. Fixes

### Direct dependency

- Patched version inside the declared constraint: `composer update <vendor/pkg>` (lock-only move).
- Outside it: edit the constraint, keeping its style (`^`, `~`), e.g. `composer require <vendor/pkg>:^<new>` (or `--dev` for `require-dev`). A major jump is a `major-upgrade` block: read the package's `UPGRADE.md`/changelog and list breaking changes as factors.

### Transitive dependency

```bash
composer update <vendor/pkg> --with-dependencies       # -w: also moves its own dependencies
composer update <vendor/pkg> --with-all-dependencies   # -W: also lets shared dependencies move; wider blast radius
```

- Prefer `--with-dependencies`. Use `--with-all-dependencies` only when `why-not` shows that a shared dependency blocks it, and say so as a fix-risk factor.
- If the parent's constraint excludes the patched version, upgrade the parent (`composer why-not` names it). If that is a major for the parent, it is a `major-upgrade` block.
- Never hand-edit `composer.lock`.

### After the update

- `composer show <vendor/pkg>` must show a version ≥ `first_patched`.
- Check the lock diff (`git diff --stat composer.lock`): an update that moved many unrelated packages raises the fix-risk; say how many moved.

## 4. Cross-check with `composer audit`

**Ask before running it**: it sends the locked package names and versions to the configured package repository's advisory service (Packagist by default). `composer audit --locked` lists known advisories for the locked packages. Use it to confirm that a block's packages no longer appear, and to spot advisories Dependabot has not raised (mention those in the plan's notes; they are not GitHub alerts and do not change the numbers). Skip it if the developer declines or the project forbids it.

## 5. Coverage gap: CodeQL does not analyze PHP

GitHub code scanning with CodeQL does not support PHP. Even when `code_scanning` coverage is `ok`, it covers only the repo's other languages (e.g. the JS/TS front end). Always state in the plan's coverage section: **"CodeQL does not analyze PHP; PHP code has no code-scanning coverage."** Do not suggest that zero code-scanning alerts means the PHP code is clean.

## 6. Verify

`composer install`, `composer validate --no-check-publish`, `composer test` (or `vendor/bin/phpunit`), and `php -l` on every changed PHP file. Details in [../execution.md](../execution.md).
