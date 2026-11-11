#!/usr/bin/env python3
"""Deterministic priority scoring, clustering, repo ranking and wave planning for alert snapshots.

All weights live in METHODOLOGY so reports can print exactly what was applied.
"""
import re
import sys
from datetime import datetime, timezone

METHODOLOGY = {
    "severity_base": {"critical": 40, "high": 30, "medium": 20, "low": 10, "unknown": 15},
    "secret": {"base": 60, "active": 25, "publicly_leaked": 15, "push_protection_bypassed": 10},
    "dependabot": {"epss_percentile": [[95, 25], [80, 15], [50, 5]], "scope": {"runtime": 10, "development": -10},
                   "relationship": {"direct": 5}},
    "code_scanning": {"classification_penalty": {"classifications": ["test", "generated"], "points": -15}},
    "activity": {"within_30_days": 10, "within_180_days": 5},
    "clamp": [0, 100],
    "bands": {"P1": 70, "P2": 40, "P3": 0},
    "clusters": "open Dependabot alerts grouped by ecosystem:package:advisory (and angular:<major>), kept when they span >= 2 repos; in a single-repo report, grouped by ecosystem:package (and angular:<major>), kept when they hold >= 2 alerts",
    "ranking": "per repo with coverage, sorted by (-max_priority, -p1_count, -open, repo)",
    "waves": {"1": "all open secrets plus every P1", "2": "alerts in clusters with >= 5 repos, plus P2",
              "3": "the rest"},
}

_BAND_RANK = {"P1": 0, "P2": 1, "P3": 2}
WAVE2_MIN_REPOS = 5


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _activity_bonus(pushed_at, now):
    if not pushed_at:
        return 0
    try:
        days = (_parse(now) - _parse(pushed_at)).total_seconds() / 86400
    except ValueError:
        return 0
    cfg = METHODOLOGY["activity"]
    if days <= 30:
        return cfg["within_30_days"]
    if days <= 180:
        return cfg["within_180_days"]
    return 0


def priority(alert, pushed_at, now):
    m = METHODOLOGY
    source = alert.get("source")
    if source == "secret_scanning":
        s = m["secret"]
        pts = s["base"]
        if alert.get("validity") == "active":
            pts += s["active"]
        if alert.get("publicly_leaked"):
            pts += s["publicly_leaked"]
        if alert.get("push_protection_bypassed"):
            pts += s["push_protection_bypassed"]
    else:
        pts = m["severity_base"].get(alert.get("severity"), m["severity_base"]["unknown"])
        if source == "dependabot":
            epss = alert.get("epss_percentile")
            if epss is not None:
                for threshold, bonus in m["dependabot"]["epss_percentile"]:
                    if epss >= threshold:
                        pts += bonus
                        break
            pts += m["dependabot"]["scope"].get(alert.get("scope"), 0)
            pts += m["dependabot"]["relationship"].get(alert.get("relationship"), 0)
        elif source == "code_scanning":
            pen = m["code_scanning"]["classification_penalty"]
            if set(alert.get("classifications") or []) & set(pen["classifications"]):
                pts += pen["points"]
    pts += _activity_bonus(pushed_at, now)
    lo, hi = m["clamp"]
    return max(lo, min(hi, pts))


def band(score):
    for name in ("P1", "P2"):
        if score >= METHODOLOGY["bands"][name]:
            return name
    return "P3"


def _is_open(a):
    return a.get("state") == "open"


def _major(version):
    m = re.match(r"\s*v?(\d+)", version or "")
    return m.group(1) if m else None


def _cluster_keys(a):
    """Cluster keys an open Dependabot alert belongs to: [(key, extra fields)]."""
    keys = [(f"{a.get('ecosystem')}:{a.get('package')}:{a.get('advisory')}",
             {"ecosystem": a.get("ecosystem"), "package": a.get("package"), "advisory": a.get("advisory"),
              "fix": f"{a.get('package')}>={a['first_patched']}" if a.get("first_patched") else None})]
    pkg = a.get("package") or ""
    major = _major(a.get("first_patched"))
    if pkg.startswith("@angular/") and major:
        keys.append((f"angular:{major}", {"ecosystem": a.get("ecosystem"), "package": "@angular/*",
                                          "advisory": None, "fix": f"@angular/*>={major}.0.0"}))
    # Package key: used only by single-repo reports, where one upgrade closes every advisory of the package.
    keys.append((f"pkg:{a.get('ecosystem')}:{pkg}", {"ecosystem": a.get("ecosystem"), "package": pkg,
                                                     "advisory": None, "fix": None}))
    return keys


def _version_key(version):
    """Numeric sort key for a version string ("2.29.4" > "2.29.10" is False); prerelease tags ignored."""
    core = re.split(r"[-+ ]", (version or "").strip().lstrip("v"), maxsplit=1)[0]
    return tuple(int(x) if x.isdigit() else 0 for x in core.split("."))


def build_clusters(alerts, single_repo=False):
    """Portfolio: advisory (and angular) keys spanning >= 2 repos. Single repo: package (and angular)
    keys holding >= 2 alerts, with the fix set to the highest first patched version per major line."""
    groups = {}
    for a in alerts:
        if a.get("source") != "dependabot" or not _is_open(a):
            continue
        for key, extra in _cluster_keys(a):
            g = groups.setdefault(key, {"extra": extra, "alerts": []})
            g["alerts"].append(a)
    clusters = []
    for key in sorted(groups):
        g = groups[key]
        repos = {a["repo"] for a in g["alerts"]}
        is_pkg = key.startswith("pkg:")
        if single_repo:
            if key.startswith("angular:") or is_pkg:
                if len(g["alerts"]) < 2:
                    continue
            else:
                continue
        elif is_pkg or len(repos) < 2:
            continue
        best = min((a.get("band") or band(a.get("priority", 0)) for a in g["alerts"]), key=_BAND_RANK.get)
        c = {"key": key, "repos": len(repos), "alerts": len(g["alerts"]), "max_band": best}
        c.update(g["extra"])
        if single_repo:
            c["advisories"] = len({a.get("advisory") for a in g["alerts"]})
        if is_pkg:
            patched = [a["first_patched"] for a in g["alerts"] if a.get("first_patched")]
            # One minimum per major line: transitive copies on different majors are upgraded separately.
            per_major = {}
            for v in patched:
                m = _version_key(v)[:1]
                if m not in per_major or _version_key(v) > _version_key(per_major[m]):
                    per_major[m] = v
            mins = [per_major[m] for m in sorted(per_major)]
            c["fix"] = f"{c['package']}>=" + ", >=".join(mins) if mins else None
            c["unpatched"] = len(g["alerts"]) - len(patched)
        clusters.append(c)
    return clusters


def _has_coverage(c):
    return any(c.get(s) == "ok" for s in ("dependabot", "code_scanning", "secret_scanning"))


def rank_repos(alerts, coverage):
    per = {}
    for a in alerts:
        if _is_open(a):
            per.setdefault(a["repo"], []).append(a)
    rows = []
    for c in coverage:
        if not _has_coverage(c):
            continue
        open_alerts = per.get(c["repo"], [])
        prios = [a.get("priority", 0) for a in open_alerts]
        rows.append({"repo": c["repo"], "max_priority": max(prios, default=0),
                     "p1_count": sum(1 for p in prios if band(p) == "P1"), "open": len(open_alerts)})
    rows.sort(key=lambda r: (-r["max_priority"], -r["p1_count"], -r["open"], r["repo"]))
    return rows


def _ref(a):
    return {"repo": a["repo"], "source": a["source"], "number": a["number"]}


def build_waves(alerts, clusters):
    big = {c["key"] for c in clusters if c["repos"] >= WAVE2_MIN_REPOS}
    waves = {1: [], 2: [], 3: []}
    for a in sorted((x for x in alerts if _is_open(x)), key=lambda x: (x["repo"], x["source"], x["number"])):
        b = a.get("band") or band(a.get("priority", 0))
        if a["source"] == "secret_scanning" or b == "P1":
            w = 1
        elif b == "P2" or (a["source"] == "dependabot" and any(k in big for k, _ in _cluster_keys(a))):
            w = 2
        else:
            w = 3
        waves[w].append(a)
    return [{"wave": n, "alerts": [_ref(a) for a in waves[n]], "repos": sorted({a["repo"] for a in waves[n]})}
            for n in (1, 2, 3)]


if __name__ == "__main__":
    print("score.py is a library; use snapshot.py", file=sys.stderr)
    sys.exit(2)
