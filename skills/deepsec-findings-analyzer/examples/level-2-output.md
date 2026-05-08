# Example: Level 2 Pattern Analysis Output

This is a real example of what Level 2 produces, generated from a scan of a Node.js/TypeScript multi-tenant SaaS application with 126 findings (1 CRITICAL, 11 HIGH, 5 HIGH_BUG, 45 MEDIUM, 64 BUG). Project name and paths have been redacted.

---

# Deepsec Findings: Pattern Analysis

**Project:** my-app
**Total findings:** 126 (122 true positives, 4 false positives)
**Scan date:** May 2026

## Executive Summary

Most findings concentrate in three areas: a single rate-limiter middleware (12 findings, all variations of bypass), the webhook delivery system (10 findings spanning SSRF, signature verification, and tenant isolation), and the CRM module (multi-tenancy issues across 6+ services). Three CRITICAL/HIGH SSRF findings share a root cause in webhook URL validation. Six `cross-tenant-id` findings in CRM suggest a missing tenant-scoping pattern. Fixing the rate-limiter and webhook layer alone would resolve ~25 findings — about 20% of the total scan output.

## Recommended Action Plan

### 🔴 P0 — This week

**Group: SSRF in webhook delivery** (3 findings, 1 CRITICAL + 2 HIGH)
- **Root cause:** Validator only string-matches hostname; fetch follows redirects without re-validation; allowlist incomplete (alt IP encodings, IPv4-mapped IPv6, DNS rebinding all bypass)
- **Files:** `webhook.service.ts`, `webhook-dispatcher.service.ts`, `webhook.validator.ts`
- **Estimated fix scope:** Validator refactor + manual redirect handling + response size cap
- **Why prioritized:** Reachable from authenticated users with `flows.edit`. Confirmed end-to-end exploit path against IMDS / private services from inside the API VPC.

**Group: JWT algorithm pinning missing** (3 findings, MEDIUM but in critical path)
- **Root cause:** `jwt.verify()` calls in `auth-guard.ts` and `auth.service.ts` don't pin algorithms
- **Files:** `apps/api/src/middleware/auth-guard.ts` (3 findings, all line 30), `apps/api/src/modules/auth/auth.service.ts`
- **Estimated fix scope:** Add `algorithms: ['HS256']` (or appropriate) to all `verify()` calls
- **Why prioritized:** Single trivial fix that closes algorithm confusion attack vector across all authenticated routes

### 🟡 P1 — Next sprint

**Group: Cross-tenant data exposure in CRM** (6 findings, 1 HIGH + 4 MEDIUM + 1 BUG)
- **Root cause:** Multiple services accept `userId`/`ownerUserId` from request body without verifying the user belongs to the requesting tenant
- **Files:** `customer-organization.service.ts`, `customer-person.service.ts`, `seller-profile.service.ts`, `lead-import.service.ts`, `activity.service.ts`, `opportunity-line-item.service.ts`
- **Estimated fix scope:** Add a shared `assertSameTenant(userId, companyId)` helper and apply at all entry points
- **Why prioritized:** Multi-tenancy data leakage across customers; subtle and may have been exploited unnoticed

**Group: Rate limiter bypass cluster** (10 findings, all in `rate-limiter.ts`)
- **Root cause:** Multiple distinct issues in same file: trusts unverified JWT for bucket key, trusts X-Forwarded-For unconditionally, fails open on Redis errors, silently disables when env vars unset
- **Files:** `apps/api/src/middleware/rate-limiter.ts`
- **Estimated fix scope:** Full middleware rewrite (~1-2 days). Split into per-concern fixes if preferred.
- **Why prioritized:** Single file, single fix budget, broad coverage. Can be tackled by one engineer in a sprint.

**Group: Webhook signature & secret handling** (4 findings, 1 HIGH + 3 MEDIUM)
- **Root cause:** Mix of secret-in-fallback patterns, signature mismatch logic, algorithm confusion in webhook auth
- **Files:** `webhook.service.ts`, `webhook-callback.controller.ts`
- **Estimated fix scope:** Webhook auth audit + standardization
- **Why prioritized:** Adjacent to the SSRF cluster — likely makes sense to fix together

### 🟢 P2 — Backlog

- 24 isolated MEDIUM findings across various services (no clear cross-cutting pattern)
- Race conditions in CRM (`other-race-condition` x9) — review case-by-case for actual concurrency risk
- ACL checks in feature modules (`acl-check` x11) — likely each requires individual analysis

### ⚪ P3 — Code quality (BUG severity)

64 BUG findings — track as a backlog. Most are not security but code-quality issues. No urgent action needed; revisit during normal refactor cycles.

## Detected Patterns

### Cross-Cutting

- **Multi-tenancy leakage in CRM**: 6 findings span 6 different services in `modules/crm/`, all variations of "accept userId from request without verifying tenant". This is a shared anti-pattern that should be fixed at the helper level, not per-service.

- **Webhook delivery layer is a security hot spot**: 10 findings across 4 webhook-related files. Issues include SSRF, signature handling, tenant isolation, and storage DoS. Recommend a security review of the entire webhook delivery flow as one effort.

- **Rate limiter is fundamentally broken in multiple ways**: 12 findings in one file isn't 12 unique bugs — it's a middleware that needs to be redesigned with security primitives in mind (trusted proxy detection, fail-closed behavior, key derivation from authenticated principal).

### Hot Spots

- `apps/api/src/middleware/rate-limiter.ts` (12 findings) — Single file, multiple distinct issues. Best treated as a rewrite candidate.
- `apps/api/src/modules/webhooks/webhook.service.ts` (7 findings) — Concentration of webhook logic; review with security mindset.
- `apps/api/src/modules/crm/customer-organization/customer-organization.service.ts` (6 findings) — Multi-tenancy + race condition combination.
- `apps/api/src/middleware/auth-guard.ts` (4 findings, 3 of same kind) — JWT algorithm pinning fix likely closes 3 in one shot.

## False Positive Review

The 4 findings marked as false-positives by `revalidate` were:

[For each FP, brief summary of why deepsec marked it FP. The skill quotes the revalidation reasoning verbatim from the JSON.]

Recommend trusting these verdicts unless you see specific reason to override.

## Findings Worth Reviewing for Possible Dismissal

2 low-confidence findings might be safe to dismiss after a quick spot-check:

- **[BUG] Login failure log leaks attacker-supplied email verbatim** — `auth.controller.ts`. Slug `other-info-disclosure`. Review whether the log destination is access-controlled.
- **[BUG] Request bodies forwarded to service without schema validation** — `customer-organization.controller.ts`. Slug `other-input-validation`. Review whether the service layer does its own validation.

## Group Index

| Group | Count | Max Severity | Priority |
|-------|-------|--------------|----------|
| SSRF in webhook delivery | 3 | CRITICAL | P0 |
| JWT algorithm pinning | 3 | MEDIUM | P0 |
| Cross-tenant data exposure | 6 | HIGH | P1 |
| Rate limiter bypass cluster | 10 | MEDIUM | P1 |
| Webhook signature & secret | 4 | HIGH | P1 |
| ACL checks (feature modules) | 11 | MEDIUM | P2 |
| Race conditions | 9 | MEDIUM | P2 |
| Non-atomic operations | 5 | MEDIUM | P2 |
| Other input validation | 4 | MEDIUM | P2 |
| Auth bypass (isolated) | 3 | HIGH | P1 |
| BUG severity (mixed) | 64 | BUG | P3 |

---

The report is ready. You can ask me follow-up questions like:

- "Show me the details of the SSRF in webhook delivery group"
- "Explain the CRITICAL finding"
- "Generate a ticket draft for the JWT algorithm pinning group"
- "Why is finding X marked as a false positive?"
- "What's the recommended fix for the rate limiter?"

What would you like to explore?
