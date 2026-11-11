#!/usr/bin/env python3
"""Render the self-contained HTML security report and the short text summary for one day.

Usage: render_report.py --dir DAY_DIR [--lang es] [--narrative FILE]
Reads DAY_DIR/snapshot.json and DAY_DIR/diff.json, and the history from DAY_DIR's parent, then
writes DAY_DIR/report.html and DAY_DIR/summary.txt. A JSON line with the paths goes to stdout.

The HTML makes zero network requests: inline CSS and inline SVG only, no scripts, and the only
absolute URLs are links to https://<scope.host>/. Every dynamic value is HTML-escaped.
"""
import argparse
import html
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diff_snapshots import DATE_RE, alert_key, load_history  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "templates" / "report.html"
I18N_DIR = SKILL_DIR / "templates" / "i18n"

SUPPORTED_LANGS = ("en", "es")
DEFAULT_LANG = "en"

SOURCES = ("dependabot", "code_scanning", "secret_scanning")
SEVERITIES = ("critical", "high", "medium", "low", "unknown")
BANDS = ("P1", "P2", "P3")
COVERAGE_VALUES = ("ok", "not_enabled", "not_licensed", "no_permission", "unavailable")
STRATEGY_KEYS = {"org-endpoints": "org_endpoints", "per-repo": "per_repo", "repo-filter": "repo_filter"}
BASELINE_REASONS = ("first_run", "owner_set_changed", "previous_unreadable")
WAVES = (1, 2, 3)
DEP_SCOPES = ("runtime", "development")
DEP_RELATIONSHIPS = ("direct", "transitive")
SECRET_VALIDITY = ("active", "inactive", "unknown")
SECRET_SIGNALS = ("base", "active", "publicly_leaked", "push_protection_bypassed")
ACTIVITY_SIGNALS = ("within_30_days", "within_180_days")
METHOD_TEXTS = ("clusters", "ranking")
NOUNS = ("alert", "repo")
METHOD_RULES = ("coverage", "delta", "lost", "baseline", "secrets", "determinism")
KNOWN_METHOD_KEYS = {"severity_base", "secret", "dependabot", "code_scanning", "activity", "clamp", "bands",
                     "clusters", "ranking", "waves"}
SOURCE_PATH = {"dependabot": "dependabot", "code_scanning": "code-scanning", "secret_scanning": "secret-scanning"}
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$")
TOKEN_RE = re.compile(r"\{\{([a-z0-9_.]+)\}\}|\[\[([a-z0-9_]+)\]\]")

TOP_REPOS = 15
ROW_LIMIT = 50
RECORD_LIMIT = 100
TREND_POINTS = 30


def dynamic_keys():
    """Every i18n key the renderer builds at runtime (the test checks they all exist)."""
    keys = {"strategy.unknown", "baseline.other", "baseline.short.other"}
    keys |= {f"source.{s}" for s in SOURCES}
    keys |= {f"severity.{s}" for s in SEVERITIES}
    keys |= {f"coverage.{c}" for c in COVERAGE_VALUES}
    keys |= {f"coverage.legend.{c}" for c in COVERAGE_VALUES}
    keys |= {f"strategy.{k}" for k in STRATEGY_KEYS.values()}
    keys |= {f"baseline.{r}" for r in BASELINE_REASONS}
    keys |= {f"baseline.short.{r}" for r in BASELINE_REASONS}
    keys |= {f"wave.{n}.title" for n in WAVES} | {f"wave.{n}.desc" for n in WAVES}
    keys |= {f"dep.scope.{s}" for s in DEP_SCOPES}
    keys |= {f"dep.relationship.{r}" for r in DEP_RELATIONSHIPS}
    keys |= {f"secret.validity.{v}" for v in SECRET_VALIDITY}
    keys |= {f"method.secret.{s}" for s in SECRET_SIGNALS}
    keys |= {f"method.activity.{s}" for s in ACTIVITY_SIGNALS}
    keys |= {f"method.text.{s}" for s in METHOD_TEXTS} | {f"method.h_{s}" for s in METHOD_TEXTS}
    keys |= {f"method.rule.{r}" for r in METHOD_RULES}
    keys |= {f"noun.{n}.{f}" for n in NOUNS for f in ("one", "other")}
    return keys


# ---------------------------------------------------------------- strings and escaping

def e(value):
    return "" if value is None else html.escape(str(value), quote=True)


class Strings:
    """i18n lookup. `t(key, **kw)` returns escaped HTML; `t.plain(key, **kw)` returns plain text."""

    def __init__(self, data, lang):
        self.data, self.lang = data, lang

    def plain(self, key, **kw):
        s = self.data[key]
        return s.format(**kw) if kw else s

    def count(self, n, noun):
        """Plain "<n> <noun>" with the singular or plural form from noun.<noun>.one/other."""
        return f"{n} {self.data[f'noun.{noun}.' + ('one' if n == 1 else 'other')]}"

    def __call__(self, key, **kw):
        s = e(self.data[key])
        return s.format(**{k: e(v) for k, v in kw.items()}) if kw else s


def _lang_code(lang):
    return re.split(r"[-_]", (lang or "").strip().lower())[0]


def load_strings(lang):
    """Return (strings, effective_lang); unknown languages fall back to English."""
    code = _lang_code(lang)
    effective = code if code in SUPPORTED_LANGS else DEFAULT_LANG
    data = json.loads((I18N_DIR / f"{DEFAULT_LANG}.json").read_text(encoding="utf-8"))
    if effective != DEFAULT_LANG:
        data.update(json.loads((I18N_DIR / f"{effective}.json").read_text(encoding="utf-8")))
    return data, effective


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _signed(n, minus="−"):
    return f"+{n}" if n > 0 else (f"{minus}{abs(n)}" if n < 0 else "0")


def _ts(value):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", value or "")
    return f"{m.group(1)} {m.group(2)} UTC" if m else (value or "")


def _parse_key(key):
    parts = str(key).rsplit("#", 2)
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else (str(key), "", "")


def _baseline_reason(reason):
    return reason if reason in BASELINE_REASONS else "other"


# ---------------------------------------------------------------- context, links, chips

class _Ctx:
    def __init__(self, snapshot, diff, t):
        self.s, self.d, self.t = snapshot, diff or {}, t
        scope = snapshot.get("scope") or {}
        host = scope.get("host") or "github.com"
        self.host_label = host
        self.host = host if isinstance(host, str) and HOST_RE.match(host) else None
        self.alerts = {alert_key(a): a for a in snapshot.get("alerts", [])}
        self.totals = snapshot.get("totals") or {}
        self.baseline = bool(self.d.get("baseline", True))
        self.methodology = snapshot.get("methodology") or {}

    def repo_url(self, repo):
        return f"https://{self.host}/{quote(str(repo), safe='/')}" if self.host and repo else None

    def alert_url(self, repo, source, number):
        if not self.host or source not in SOURCE_PATH:
            return None
        try:
            n = int(number)
        except (TypeError, ValueError):
            return None
        return f"{self.repo_url(repo)}/security/{SOURCE_PATH[source]}/{n}"


def _a(url, text_html):
    return f'<a href="{e(url)}">{text_html}</a>' if url else text_html


def _repo(ctx, repo):
    # <wbr> lets long names wrap after the owner instead of mid-name
    return _a(ctx.repo_url(repo), e(repo).replace("/", "/<wbr>", 1))


def _source_label(t, source):
    return t(f"source.{source}") if source in SOURCES else e(source)


def _alert_link(ctx, repo, source, number):
    return _a(ctx.alert_url(repo, source, number), f"{_source_label(ctx.t, source)} #{e(number)}")


def _chip(css, label):
    return f'<span class="chip {css}">{label}</span>'


def _band_chip(band):
    css = band.lower() if band in BANDS else "none"
    return _chip(f"band band-{css}", e(band or "—"))


def _sev_chip(t, sev):
    sev = sev if sev in SEVERITIES else "unknown"
    return _chip(f"sev sev-{sev}", t(f"severity.{sev}"))


def _cov_chip(t, status):
    if status in COVERAGE_VALUES:
        return _chip(f"cov cov-{status}", t(f"coverage.{status}"))
    return _chip("cov cov-unavailable", e(status))


def _code(v):
    return f"<code>{e(v)}</code>" if v not in (None, "") else ""


def _table(headers, rows, cls=""):
    """headers: [(label_html, css)], rows: [[cell_html]] with css taken from the header."""
    head = "".join(f'<th scope="col" class="{c}">{h}</th>' for h, c in headers)
    body = "".join("<tr>" + "".join(f'<td class="{headers[i][1]}">{cell}</td>' for i, cell in enumerate(r)) + "</tr>"
                   for r in rows)
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _note(text_html, cls="note"):
    return f'<p class="{cls}">{text_html}</p>'


def _more(t, shown, total):
    return _note(t("table.more", shown=shown, total=total), "note more") if total > shown else ""


# ---------------------------------------------------------------- alert detail

def _detail(ctx, a):
    t, src = ctx.t, a.get("source")
    meta = []
    if src == "dependabot":
        title = a.get("summary") or a.get("advisory") or a.get("package")
        pkg = a.get("package")
        if pkg:
            meta.append(_code(f"{pkg} {a.get('vulnerable_range') or ''}".strip()))
        meta.append(t("alert.fix", version=a["first_patched"]) if a.get("first_patched") else t("alert.no_fix"))
        meta += [_code(a.get("advisory")), _code(a.get("cve"))]
        if isinstance(a.get("epss_percentile"), (int, float)):
            meta.append(t("alert.epss", pct=f"{a['epss_percentile']:.0f}"))
        if a.get("scope") in DEP_SCOPES:
            meta.append(t(f"dep.scope.{a['scope']}"))
        if a.get("relationship") in DEP_RELATIONSHIPS:
            meta.append(t(f"dep.relationship.{a['relationship']}"))
    elif src == "code_scanning":
        title = a.get("rule_description") or a.get("rule_id")
        meta += [_code(a.get("rule_id")), e(a.get("tool"))]
        if a.get("path"):
            line = f":{a['start_line']}" if a.get("start_line") else ""
            meta.append(_code(f"{a['path']}{line}"))
    elif src == "secret_scanning":
        title = a.get("secret_type_display_name") or a.get("secret_type")
        if a.get("validity") in SECRET_VALIDITY:
            meta.append(t(f"secret.validity.{a['validity']}"))
        if a.get("publicly_leaked"):
            meta.append(t("secret.public_leak"))
        if a.get("push_protection_bypassed"):
            meta.append(t("secret.pp_bypassed"))
    else:
        title = a.get("summary")
    meta_html = " · ".join(m for m in meta if m)
    return f'<div class="d-title">{e(title)}</div>' + (f'<div class="d-meta">{meta_html}</div>' if meta_html else "")


def _sort_alerts(alerts):
    return sorted(alerts, key=lambda a: (-_int(a.get("priority")), str(a.get("repo")), str(a.get("source")),
                                         _int(a.get("number"))))


def _alerts_table(ctx, alerts, limit=ROW_LIMIT):
    t = ctx.t
    alerts = _sort_alerts(alerts)
    headers = [(t("col.band"), "c-chip"), (t("col.score"), "num"), (t("col.severity"), "c-chip"),
               (t("col.repo"), "repo"), (t("col.alert"), "c-alert"), (t("col.detail"), "detail")]
    rows = [[_band_chip(a.get("band")), e(a.get("priority")), _sev_chip(t, a.get("severity")), _repo(ctx, a.get("repo")),
             _alert_link(ctx, a.get("repo"), a.get("source"), a.get("number")), _detail(ctx, a)]
            for a in alerts[:limit]]
    return _table(headers, rows, "alerts") + _more(t, min(limit, len(alerts)), len(alerts))


# ---------------------------------------------------------------- charts

def _nice_step(raw):
    if raw <= 1:
        return 1
    mag = 10 ** int(math.floor(math.log10(raw)))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _trend_series(snapshot, history, today=None):
    # Ruling R12: history points are keyed by day-folder name, so today's point uses the folder name
    # too when the caller knows it; otherwise the UTC date of generated_at (how folders are named).
    today = today or (snapshot.get("generated_at") or "")[:10]
    by_date = {}
    for h in history or []:
        d = h.get("date")
        if isinstance(d, str) and (not today or d < today):
            by_date[d] = {"date": d, "open": _int(h.get("open")), "by_band": h.get("by_band") or {}}
    totals = snapshot.get("totals") or {}
    by_date[today] = {"date": today, "open": _int(totals.get("open")), "by_band": totals.get("by_band") or {}}
    return [by_date[k] for k in sorted(by_date)][-TREND_POINTS:]


def _trend_svg(t, rows):
    w, h, left, right, top, bottom = 720, 240, 44, 28, 14, 34
    pw, ph = w - left - right, h - top - bottom
    totals = [r["open"] for r in rows]
    p1 = [_int(r["by_band"].get("P1")) for r in rows]
    step = _nice_step(max(totals + p1 + [1]) / 4)
    ymax = step * max(1, math.ceil(max(totals + p1 + [1]) / step))
    n = len(rows)

    def x(i):
        return round(left + (pw * i / (n - 1) if n > 1 else pw / 2), 1)

    def y(v):
        return round(top + ph - ph * v / ymax, 1)

    parts = []
    for k in range(0, ymax + 1, step):
        parts.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y(k)}" y2="{y(k)}"/>'
                     f'<text class="axis" x="{left - 8}" y="{y(k) + 4}" text-anchor="end">{k}</text>')
    if n <= 7:
        label_idx = list(range(n))
    else:
        label_idx = sorted({round(i * (n - 1) / 5) for i in range(6)})
    for i in label_idx:
        anchor = "start" if i == 0 and n > 1 else ("end" if i == n - 1 and n > 1 else "middle")
        label = rows[i]["date"] if i in (0, n - 1) else rows[i]["date"][5:]
        parts.append(f'<text class="axis" x="{x(i)}" y="{h - 10}" text-anchor="{anchor}">{e(label)}</text>')
    pts_total = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(totals))
    pts_p1 = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(p1))
    parts.append(f'<polyline class="line-p1" points="{pts_p1}"/>')
    parts.append(f'<polyline class="line-total" points="{pts_total}"/>')
    for i, v in enumerate(p1):
        parts.append(f'<rect class="mark-p1" x="{x(i) - 3}" y="{y(v) - 3}" width="6" height="6"/>')
    for i, v in enumerate(totals):
        parts.append(f'<circle class="mark-total" cx="{x(i)}" cy="{y(v)}" r="3.5"/>')
    parts.append(f'<text class="value" x="{x(n - 1)}" y="{y(totals[-1]) - 9}" text-anchor="end">{totals[-1]}</text>')
    desc = t("trend.desc", start=rows[0]["date"], end=rows[-1]["date"], first=totals[0], last=totals[-1])
    return (f'<svg class="chart trend" viewBox="0 0 {w} {h}" role="img" aria-labelledby="trend-t trend-d">'
            f'<title id="trend-t">{t("trend.chart_title")}</title><desc id="trend-d">{desc}</desc>'
            + "".join(parts) + "</svg>")


def _legend_swatch(cls):
    return (f'<svg class="swatch" viewBox="0 0 24 10" aria-hidden="true"><line class="{cls}" x1="1" x2="23" y1="5" '
            f'y2="5"/></svg>')


def _band_bars(t, by_band):
    w, row, label_w, value_w = 360, 30, 36, 44
    area = w - label_w - value_w
    vals = [_int(by_band.get(b)) for b in BANDS]
    vmax = max(vals + [1])
    parts = []
    for i, (b, v) in enumerate(zip(BANDS, vals)):
        y = i * row + 4
        bw = round(area * v / vmax, 1) if v else 0
        parts.append(f'<text class="bar-label" x="0" y="{y + 14}">{b}</text>'
                     f'<rect class="bar-track" x="{label_w}" y="{y}" width="{area}" height="20" rx="2"/>'
                     + (f'<rect class="bar bar-{b.lower()}" x="{label_w}" y="{y}" width="{bw}" height="20" rx="2"/>'
                        if v else "")
                     + f'<text class="bar-value" x="{label_w + bw + 6}" y="{y + 14}">{v}</text>')
    desc = ", ".join(f"{b} {v}" for b, v in zip(BANDS, vals))
    return (f'<svg class="chart bars" viewBox="0 0 {w} {row * 3 + 4}" role="img" aria-labelledby="bands-t bands-d">'
            f'<title id="bands-t">{t("summary.by_band")}</title><desc id="bands-d">{e(desc)}</desc>'
            + "".join(parts) + "</svg>")


# ---------------------------------------------------------------- header

def _scope_label(scope):
    """Who the report is about: the selected repositories when filtered, otherwise the owners."""
    return ", ".join(scope.get("repos") or scope.get("owners") or [])


def _scope_meta(ctx):
    t, s = ctx.t, ctx.s
    scope = s.get("scope") or {}
    owners = scope.get("owners") or []
    mode = t("scope.mode_repo") if scope.get("mode") == "repo" else t("scope.mode_portfolio")
    items = [(t("scope.generated"), e(_ts(s.get("generated_at")))), (t("scope.host"), _code(ctx.host_label)),
             (t("scope.mode"), mode), (t("scope.owners"), e(", ".join(owners)))]
    if scope.get("repos"):
        items.append((t("scope.repos"), e(", ".join(scope["repos"]))))
    return '<dl class="meta">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in items) + "</dl>"


def _scope_table(ctx):
    t = ctx.t
    scope = ctx.s.get("scope") or {}
    strategy = {str(k).lower(): v for k, v in (scope.get("strategy") or {}).items()}
    public_only = {str(o).lower() for o in scope.get("public_only") or []}
    rows = []
    for owner in scope.get("owners") or []:
        key = STRATEGY_KEYS.get(strategy.get(str(owner).lower()))
        label = t(f"strategy.{key}") if key else t("strategy.unknown")
        if key == "per_repo":
            view = f'<span class="flag">{t("strategy.partial_view")}</span>'
        elif key == "org_endpoints":
            view = t("strategy.org_view")
        elif key == "repo_filter":
            view = t("strategy.repo_filter_view")
        else:
            view = "—"
        if str(owner).lower() in public_only:  # Ruling R25
            view += f'<br><span class="flag">{t("strategy.public_only")}</span>'
        rows.append([e(owner), label, view])
    return _table([(t("col.owner"), ""), (t("col.strategy"), ""), (t("col.view"), "")], rows, "scope")


def _baseline_notice(ctx):
    if not ctx.baseline:
        return ""
    reason = _baseline_reason(ctx.d.get("reason"))
    return (f'<div class="notice" role="note"><strong>{ctx.t("baseline.label")}</strong> '
            f'{ctx.t(f"baseline.{reason}")}</div>')


# ---------------------------------------------------------------- sections

def _kpi(label, value, sub="", tone=""):
    return (f'<div class="kpi {tone}"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')


def _narrative_html(narrative):
    paras = [p.strip() for p in re.split(r"\n\s*\n", (narrative or "").strip()) if p.strip()]
    return "".join(f"<p>{'<br>'.join(e(line) for line in p.splitlines())}</p>" for p in paras)


def _section_summary(ctx, narrative):
    t, d, tot = ctx.t, ctx.d, ctx.totals
    dt = d.get("totals") or {}
    repos = tot.get("repos") or {}
    by_band = tot.get("by_band") or {}
    open_now = _int(dt.get("curr_open", tot.get("open")))
    closed, new, dismissed = d.get("closed") or [], d.get("new") or [], d.get("dismissed") or []
    lost = _int(dt.get("lost_coverage"))
    dash = "—"
    if ctx.baseline:
        open_sub = t("kpi.baseline_no_delta")
    else:
        lost_cls = ' class="warn"' if lost else ""
        open_sub = (f'{t("kpi.delta", delta=_signed(_int(dt.get("delta"))))}'
                    f'<br><span{lost_cls}>{t("kpi.lost_coverage", n=lost)}</span>')
    p1_min = (ctx.methodology.get("bands") or {}).get("P1", "")
    no_cov = len(repos.get("no_coverage") or [])
    tiles = [
        _kpi(t("kpi.open"), open_now, open_sub),
        _kpi(t("kpi.p1"), _int(by_band.get("P1")), t("kpi.p1_sub", min=p1_min)),
        _kpi(t("kpi.closed"), dash if ctx.baseline else len(closed),
             "" if ctx.baseline else t("kpi.closed_sub", resolved=len(closed) - len(dismissed),
                                       dismissed=len(dismissed))),
        _kpi(t("kpi.new"), dash if ctx.baseline else len(new), "" if ctx.baseline else t("kpi.new_sub")),
        _kpi(t("kpi.coverage"), f'{_int(repos.get("scanned"))}<span class="of"> / {_int(repos.get("total"))}</span>',
             t("kpi.coverage_sub", n=no_cov), "warn" if no_cov else ""),
        _kpi(t("kpi.zero"), len(repos.get("zero_open") or []),
             ("" if ctx.baseline else t("kpi.zero_sub", n=len(d.get("repos_reached_zero") or [])) + "<br>")
             + t("kpi.zero_partial", n=len(repos.get("zero_open_partial") or []))),
    ]
    out = [f'<div class="kpis">{"".join(tiles)}</div>']
    if narrative and narrative.strip():
        out.append(f'<div class="narrative"><h3>{t("summary.narrative")}</h3>{_narrative_html(narrative)}'
                   f'<p class="note">{t("summary.narrative_note")}</p></div>')

    by_source, by_sev = tot.get("by_source") or {}, tot.get("by_severity") or {}
    src_rows = [[_source_label(t, s), _int(by_source.get(s))] for s in SOURCES]
    sev_rows = [[_sev_chip(t, s), _int(by_sev.get(s))] for s in SEVERITIES if s != "unknown" or by_sev.get(s)]
    out.append('<div class="grid3">'
               f'<figure><figcaption>{t("summary.by_band")}</figcaption>{_band_bars(t, by_band)}</figure>'
               f'<div><h3 class="small">{t("summary.by_source")}</h3>'
               f'{_table([(t("col.source"), ""), (t("col.open"), "num")], src_rows, "compact")}</div>'
               f'<div><h3 class="small">{t("summary.by_severity")}</h3>'
               f'{_table([(t("col.severity"), ""), (t("col.open"), "num")], sev_rows, "compact")}</div></div>')

    # per-owner breakdown
    owners = (ctx.s.get("scope") or {}).get("owners") or []
    cov = ctx.s.get("coverage") or []
    no_cov_set = set(repos.get("no_coverage") or [])
    open_alerts = [a for a in ctx.s.get("alerts", []) if a.get("state") == "open"]
    owner_rows = []
    for o in owners:
        # Ruling R23: logins are case-insensitive (older snapshots kept the typed spelling).
        key = str(o).lower()
        repos_o = [c["repo"] for c in cov if str(c.get("owner")).lower() == key]
        alerts_o = [a for a in open_alerts if str(a.get("owner")).lower() == key]
        owner_rows.append([e(o), len(repos_o), len([r for r in repos_o if r not in no_cov_set]), len(alerts_o),
                           len([a for a in alerts_o if a.get("band") == "P1"])])
    out.append(f'<h3>{t("summary.by_owner")}</h3>' + _table(
        [(t("col.owner"), ""), (t("col.repos"), "num"), (t("col.with_coverage"), "num"), (t("col.open"), "num"),
         (t("col.p1"), "num")], owner_rows, "compact"))

    # changes since previous report
    out.append(f'<h3>{t("changes.title")}</h3>')
    if ctx.baseline:
        out.append(_note(t("changes.baseline")))
    elif not (closed or new):
        out.append(_note(t("changes.none")))
    else:
        if new:
            new_alerts = [ctx.alerts[k] for k in new if k in ctx.alerts]
            out.append(f'<h4>{t("changes.new", n=len(new))}</h4>' + _alerts_table(ctx, new_alerts))
        if closed:
            dis = {x.get("key"): x for x in dismissed}
            rows = []
            for k in closed[:ROW_LIMIT]:
                repo, source, number = _parse_key(k)
                if k in dis:
                    x = dis[k]
                    outcome = t("changes.outcome_dismissed", reason=x.get("reason") or "—",
                                by=x.get("by") or "—")
                else:
                    outcome = t("changes.outcome_resolved")
                rows.append([_repo(ctx, repo), _alert_link(ctx, repo, source, number), outcome])
            out.append(f'<h4>{t("changes.closed", n=len(closed))}</h4>'
                       + _table([(t("col.repo"), "repo"), (t("col.alert"), "c-alert"), (t("col.outcome"), "")],
                                rows) + _more(t, min(ROW_LIMIT, len(closed)), len(closed)))
    reached = d.get("repos_reached_zero") or []
    if reached and not ctx.baseline:
        out.append(_note(f'<strong>{t("changes.reached_zero")}</strong> '
                         + ", ".join(_repo(ctx, r) for r in reached)))
    partial = d.get("repos_reached_zero_partial") or []
    if partial and not ctx.baseline:
        out.append(_note(f'<strong>{t("changes.reached_zero_partial")}</strong> '
                         + ", ".join(_repo(ctx, r) for r in partial)))
    return "".join(out)


def _section_trend(ctx, history, today=None):
    t = ctx.t
    rows = _trend_series(ctx.s, history, today)
    out = []
    if len(rows) < 2:
        out.append(_note(t("trend.single")))
    else:
        out.append(f'<figure class="trend-fig">{_trend_svg(t, rows)}<figcaption class="legend">'
                   f'<span>{_legend_swatch("line-total")}{t("trend.total")}</span>'
                   f'<span>{_legend_swatch("line-p1")}{t("trend.p1")}</span></figcaption></figure>')
    table = _table([(t("col.date"), ""), (t("col.open"), "num")] + [(e(b), "num") for b in BANDS],
                   [[e(r["date"]), r["open"]] + [_int(r["by_band"].get(b)) for b in BANDS] for r in reversed(rows)],
                   "compact")
    out.append(f'<details class="data"><summary>{t("trend.data")}</summary>{table}</details>')
    return "".join(out)


def _section_coverage(ctx):
    t = ctx.t
    cov = ctx.s.get("coverage") or []
    repos = ctx.totals.get("repos") or {}
    out = [_note(t("coverage.lead", scanned=_int(repos.get("scanned")), total=_int(repos.get("total"))), "lead")]

    matrix = []
    for s in SOURCES:
        counts = [sum(1 for c in cov if c.get(s) == v) for v in COVERAGE_VALUES]
        matrix.append([_source_label(t, s)] + [n if n else '<span class="zero">0</span>' for n in counts])
    out.append(_table([(t("col.scanner"), "")] + [(_cov_chip(t, v), "num") for v in COVERAGE_VALUES], matrix,
                      "matrix"))

    no_cov = set(repos.get("no_coverage") or [])
    gaps = [c for c in cov if any(c.get(s) != "ok" for s in SOURCES)]
    gaps.sort(key=lambda c: (c.get("repo") not in no_cov, str(c.get("repo"))))
    out.append(f'<h3>{t("coverage.gaps_title", n=len(gaps))}</h3>')
    if not gaps:
        out.append(_note(t("coverage.no_gaps")))
    else:
        rows = []
        for c in gaps:
            name = _repo(ctx, c.get("repo"))
            if c.get("repo") in no_cov:
                name += " " + _chip("flag-chip", t("coverage.none_badge"))
            vis = t("repo.private") if c.get("private") else t("repo.public")
            if c.get("archived"):
                vis += " · " + t("repo.archived")
            rows.append([name, vis] + [_cov_chip(t, c.get(s)) for s in SOURCES])
        out.append(_table([(t("col.repo"), "repo"), (t("col.visibility"), "")]
                          + [(_source_label(t, s), "c-chip") for s in SOURCES], rows))
        full = len(cov) - len(gaps)
        out.append(_note(t("coverage.full_count", n=full)))

    out.append(f'<h3>{t("coverage.lost_title")}</h3>')
    lost = ctx.d.get("lost_coverage") or []
    if ctx.baseline:
        out.append(_note(t("coverage.lost_baseline")))
    elif not lost:
        out.append(_note(t("coverage.lost_none")))
    else:
        cmap = {c.get("repo"): c for c in cov}
        rows = []
        for k in lost:
            repo, source, number = _parse_key(k)
            status = (cmap.get(repo) or {}).get(source, "unavailable")
            rows.append([_repo(ctx, repo), _alert_link(ctx, repo, source, number), _cov_chip(t, status)])
        out.append(_note(t("coverage.lost_lead", n=len(lost))))
        out.append(_table([(t("col.repo"), "repo"), (t("col.alert"), "c-alert"), (t("col.coverage_now"), "c-chip")],
                          rows))

    legend = "".join(f"<div><dt>{_cov_chip(t, v)}</dt><dd>{t(f'coverage.legend.{v}')}</dd></div>"
                     for v in COVERAGE_VALUES)
    out.append(f'<h3>{t("coverage.legend_title")}</h3><dl class="legend-list">{legend}</dl>')
    return "".join(out)


def _band_for(ctx, score):
    """Band for a score using the thresholds recorded in the snapshot's methodology."""
    bands = ctx.methodology.get("bands") or {}
    for name in ("P1", "P2"):
        if isinstance(bands.get(name), (int, float)) and score >= bands[name]:
            return name
    return "P3" if bands else None


def _section_top_risk(ctx):
    t = ctx.t
    ranking = [r for r in ctx.s.get("ranking") or [] if _int(r.get("open")) > 0]
    if not ranking:
        return _note(t("top.empty"))
    per = {}
    for a in ctx.s.get("alerts", []):
        if a.get("state") == "open":
            per.setdefault(a.get("repo"), {}).setdefault(a.get("source"), 0)
            per[a.get("repo")][a.get("source")] += 1
    rows = []
    for i, r in enumerate(ranking[:TOP_REPOS], 1):
        mp = _int(r.get("max_priority"))
        chip = _band_chip(_band_for(ctx, mp))
        counts = per.get(r.get("repo"), {})
        rows.append([i, _repo(ctx, r.get("repo")), f"{chip} {mp}", _int(r.get("p1_count")), _int(r.get("open"))]
                    + [counts.get(s, 0) or '<span class="zero">0</span>' for s in SOURCES])
    headers = [(t("col.rank"), "num"), (t("col.repo"), "repo"), (t("col.max_priority"), "num"),
               (t("col.p1"), "num"), (t("col.open"), "num")] + [(_source_label(t, s), "num") for s in SOURCES]
    return (_note(t("top.lead", n=min(TOP_REPOS, len(ranking)), total=len(ranking)), "lead")
            + _table(headers, rows))


def _section_campaigns(ctx):
    t = ctx.t
    single = (ctx.s.get("scope") or {}).get("mode") == "repo"
    sfx = "_repo" if single else ""
    clusters = sorted(ctx.s.get("clusters") or [],
                      key=lambda c: (-_int(c.get("repos")), -_int(c.get("alerts")), str(c.get("key"))))
    moves = {} if ctx.baseline else {c.get("key"): c for c in ctx.d.get("clusters") or []}
    out = [_note(t(f"campaigns.lead{sfx}"), "lead")]
    if not clusters:
        out.append(_note(t(f"campaigns.empty{sfx}")))
    else:
        rows = []
        for c in clusters:
            fix = _code(c.get("fix")) or t("alert.no_fix")
            if str(c.get("key", "")).startswith("angular:"):
                fix += "<br>" + _chip("flag-chip", t("campaigns.angular"))
            if _int(c.get("unpatched")):
                fix += "<br>" + _chip("flag-chip", t("campaigns.unpatched", n=_int(c.get("unpatched"))))
            m = moves.get(c.get("key"))
            change = (_move_text(t, m) if m else ("—" if ctx.baseline else t("campaigns.unchanged")))
            pkg = f'{_code(c.get("package"))} <span class="muted">{e(c.get("ecosystem"))}</span>'
            # A single-repo report has no repos column; it counts the advisories one upgrade closes instead.
            middle = ([_int(c.get("advisories"))] if single
                      else [_code(c.get("advisory")) or "—", _int(c.get("repos"))])
            rows.append([fix, pkg, *middle, _int(c.get("alerts")), _band_chip(c.get("max_band")), change])
        middle_head = ([(t("col.advisories"), "num")] if single
                       else [(t("col.advisory"), ""), (t("col.repos"), "num")])
        out.append(_table([(t("col.fix"), ""), (t("col.package"), ""), *middle_head, (t("col.alerts"), "num"),
                           (t("col.max_band"), "c-chip"), (t("col.change"), "num")], rows))
    # Ruling R10: a campaign is completed only when no open alert matches its key any more. A key
    # that fell below the 2-repo threshold but still has open alerts is listed separately.
    # Ruling R21: alerts hidden by lost coverage are unknown, so such a key is never completed.
    current = {c.get("key") for c in clusters}
    done, unconfirmed, shrunk = [], [], []
    for k, m in moves.items():
        lost, still_open = _int(m.get("lost_coverage")), _int(m.get("curr_open")) - _int(m.get("lost_coverage"))
        if lost == 0 and still_open <= 0:
            done.append(m)
        elif k not in current:
            (shrunk if still_open > 0 else unconfirmed).append(m)

    def moved(items):
        return ", ".join(f'{_code(m.get("key"))} ({_move_text(t, m)})'
                         for m in sorted(items, key=lambda m: str(m.get("key"))))

    if done:
        out.append(_note(f'<strong>{t("campaigns.completed")}</strong> {moved(done)}'))
    if unconfirmed:
        out.append(_note(f'<strong>{t("campaigns.unconfirmed")}</strong> {moved(unconfirmed)}'))
    if shrunk:
        out.append(_note(f'<strong>{t(f"campaigns.shrunk{sfx}")}</strong> {moved(shrunk)}'))
    return "".join(out)


def _move_text(t, m):
    """"prev → curr", plus how many of curr are hidden by lost coverage (Ruling R21)."""
    text = f'{_int(m.get("prev_open"))} \u2192 {_int(m.get("curr_open"))}'
    lost = _int(m.get("lost_coverage"))
    return f'{text}; {t("campaigns.lost_suffix", n=lost)}' if lost else text


def _section_waves(ctx):
    t = ctx.t
    out = [_note(t("waves.lead"), "lead")]
    for w in sorted(ctx.s.get("waves") or [], key=lambda w: _int(w.get("wave"))):
        n = _int(w.get("wave"))
        alerts = [ctx.alerts[alert_key(r)] for r in w.get("alerts") or []
                  if isinstance(r, dict) and alert_key(r) in ctx.alerts]
        title = t(f"wave.{n}.title") if n in WAVES else e(n)
        desc = (t(f"wave.{n}.desc_repo") if n == 2 and (ctx.s.get("scope") or {}).get("mode") == "repo"
                else t(f"wave.{n}.desc")) if n in WAVES else ""
        stats = t("waves.stats", alerts=t.count(len(alerts), "alert"), repos=t.count(len(w.get("repos") or []), "repo"))
        out.append(f'<div class="wave wave-{n}"><div class="wave-head"><h3>{title}</h3>'
                   f'<span class="wave-stats">{stats}</span></div><p class="note">{desc}</p>')
        out.append(_alerts_table(ctx, alerts) if alerts else _note(t("waves.empty")))
        out.append("</div>")
    return "".join(out)


def _comment_cell(t, comment):
    if comment and str(comment).strip():
        return f'<span class="comment">{e(comment)}</span>'
    return _chip("flag-chip", t("dismissals.no_comment"))


def _section_dismissals(ctx):
    t = ctx.t
    out = [f'<h3>{t("dismissals.period_title")}</h3>']
    period = ctx.d.get("dismissed") or []
    if ctx.baseline:
        out.append(_note(t("dismissals.baseline")))
    elif not period:
        out.append(_note(t("dismissals.none_period")))
    else:
        rows = []
        for x in period:
            repo, source, number = _parse_key(x.get("key"))
            a = ctx.alerts.get(x.get("key")) or {}
            rows.append([e(_ts(a.get("dismissed_at"))) or "—", _repo(ctx, repo),
                         _alert_link(ctx, repo, source, number), e(x.get("by")) or "—",
                         _code(x.get("reason")) or "—", _comment_cell(t, x.get("comment"))])
        out.append(_dismissal_table(t, rows))

    record = [a for a in ctx.s.get("alerts", []) if a.get("state") == "dismissed"]
    record.sort(key=lambda a: (str(a.get("dismissed_at") or ""), str(a.get("repo")), str(a.get("source")),
                               _int(a.get("number"))), reverse=True)
    out.append(f'<h3>{t("dismissals.record_title", n=len(record))}</h3>')
    if not record:
        out.append(_note(t("dismissals.none_record")))
    else:
        rows = [[e(_ts(a.get("dismissed_at"))) or "—", _repo(ctx, a.get("repo")),
                 _alert_link(ctx, a.get("repo"), a.get("source"), a.get("number")),
                 e(a.get("dismissed_by")) or "—", _code(a.get("dismissed_reason")) or "—",
                 _comment_cell(t, a.get("dismissed_comment"))] for a in record[:RECORD_LIMIT]]
        out.append(_dismissal_table(t, rows) + _more(t, min(RECORD_LIMIT, len(record)), len(record)))
    return "".join(out)


def _dismissal_table(t, rows):
    return _table([(t("col.dismissed_at"), "c-date"), (t("col.repo"), "repo"), (t("col.alert"), "c-alert"),
                   (t("col.by"), "c-nowrap"), (t("col.reason"), "c-nowrap"), (t("col.comment"), "detail")], rows,
                  "dismissals")


def _pts(v):
    return _signed(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else e(v)


def _section_methodology(ctx):
    t, m, lang = ctx.t, ctx.methodology, ctx.t.lang
    rows = []

    def group(label):
        rows.append(f'<tr class="group"><th colspan="2" scope="rowgroup">{label}</th></tr>')

    def row(label, value):
        rows.append(f'<tr><td>{label}</td><td class="num">{value}</td></tr>')

    sb = m.get("severity_base") or {}
    if sb:
        group(t("method.g_severity"))
        for sev in [s for s in SEVERITIES if s in sb] + sorted(k for k in sb if k not in SEVERITIES):
            row(t(f"severity.{sev}") if sev in SEVERITIES else e(sev), e(sb[sev]))
    dep = m.get("dependabot") or {}
    if dep:
        group(t("method.g_dependabot"))
        for threshold, bonus in dep.get("epss_percentile") or []:
            row(t("method.epss", threshold=threshold), _pts(bonus))
        for k, v in (dep.get("scope") or {}).items():
            row(t("method.dep_scope", scope=t.plain(f"dep.scope.{k}") if k in DEP_SCOPES else k), _pts(v))
        for k, v in (dep.get("relationship") or {}).items():
            row(t("method.dep_relationship",
                  relationship=t.plain(f"dep.relationship.{k}") if k in DEP_RELATIONSHIPS else k), _pts(v))
    pen = (m.get("code_scanning") or {}).get("classification_penalty") or {}
    if pen:
        group(t("method.g_code_scanning"))
        row(t("method.cs_classification", classifications=", ".join(str(c) for c in pen.get("classifications") or [])),
            _pts(pen.get("points")))
    sec = m.get("secret") or {}
    if sec:
        group(t("method.g_secret"))
        for k, v in sec.items():
            row(t(f"method.secret.{k}") if k in SECRET_SIGNALS else e(k), e(v) if k == "base" else _pts(v))
    act = m.get("activity") or {}
    if act:
        group(t("method.g_activity"))
        for k, v in act.items():
            row(t(f"method.activity.{k}") if k in ACTIVITY_SIGNALS else e(k), _pts(v))
    clamp = m.get("clamp") or []
    lo, hi = clamp[:2] if len(clamp) >= 2 else ("\u2014", "\u2014")
    out = [_note(t("method.lead", generated=_ts(ctx.s.get("generated_at"))), "lead"),
           f'<h3>{t("method.h_priority")}</h3>', _note(t("method.priority_intro", lo=lo, hi=hi)),
           f'<div class="table-wrap"><table class="method"><thead><tr><th scope="col">{t("col.signal")}</th>'
           f'<th scope="col" class="num">{t("col.points")}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>']

    bands = m.get("bands") or {}
    if bands:
        brows = [[_band_chip(b), t("method.band_threshold", min=bands[b])] for b in BANDS if b in bands]
        out.append(f'<h3>{t("method.h_bands")}</h3>' + _table([(t("col.band"), "c-chip"), (t("col.rule"), "")],
                                                               brows, "compact"))

    def recorded(key, raw, translated):
        if raw is None:
            return ""
        if lang == DEFAULT_LANG:
            return f"<p>{e(raw)}</p>"
        return f'<p>{translated}</p><p class="recorded">{t("method.recorded")} <code>{e(raw)}</code></p>'

    out.append(f'<h3>{t("method.h_grouping")}</h3>')
    for k in METHOD_TEXTS:
        if k in m:
            out.append(f'<h4>{t(f"method.h_{k}")}</h4>' + recorded(k, m[k], t(f"method.text.{k}")))
    waves = m.get("waves") or {}
    if waves:
        out.append(f'<h4>{t("method.h_waves")}</h4><dl class="defs">')
        for n in sorted(waves, key=lambda x: str(x)):
            label = t(f"wave.{n}.title") if str(n) in {str(w) for w in WAVES} else e(n)
            desc = t(f"wave.{n}.desc") if str(n) in {str(w) for w in WAVES} else ""
            body = e(waves[n]) if lang == DEFAULT_LANG else (
                f'{desc}<br><span class="recorded">{t("method.recorded")} <code>{e(waves[n])}</code></span>')
            out.append(f"<div><dt>{label}</dt><dd>{body}</dd></div>")
        out.append("</dl>")

    extra = sorted(k for k in m if k not in KNOWN_METHOD_KEYS)
    if extra:
        out.append(f'<h3>{t("method.h_other")}</h3>' + _table(
            [(t("col.parameter"), ""), (t("col.value"), "")],
            [[_code(k), _code(json.dumps(m[k], sort_keys=True, ensure_ascii=False))] for k in extra], "compact"))

    out.append(f'<h3>{t("method.h_rules")}</h3><ul class="rules">'
               + "".join(f'<li>{t(f"method.rule.{r}")}</li>' for r in METHOD_RULES) + "</ul>")
    return "".join(out)


# ---------------------------------------------------------------- public API

def render_html(snapshot, diff, history, lang, narrative=None, today=None):
    """Render the report. `today` is the day-folder name (YYYY-MM-DD) keying today's trend point."""
    data, effective = load_strings(lang)
    t = Strings(data, effective)
    ctx = _Ctx(snapshot, diff, t)
    scope = snapshot.get("scope") or {}
    slots = {
        "lang": e(effective),
        "doc_title": e(" · ".join(x for x in (t.plain("report.title"), _scope_label(scope),
                                                    (snapshot.get("generated_at") or "")[:10]) if x)),
        "scope_meta": _scope_meta(ctx),
        "scope_table": _scope_table(ctx),
        "baseline_notice": _baseline_notice(ctx),
        "summary": _section_summary(ctx, narrative),
        "trend": _section_trend(ctx, history, today),
        "coverage": _section_coverage(ctx),
        "top_risk": _section_top_risk(ctx),
        "campaigns": _section_campaigns(ctx),
        "waves": _section_waves(ctx),
        "dismissals": _section_dismissals(ctx),
        "methodology": _section_methodology(ctx),
        "footer": t("footer.text", generated=_ts(snapshot.get("generated_at")), host=ctx.host_label),
    }
    template = TEMPLATE.read_text(encoding="utf-8")

    def fill(match):
        return t(match.group(1)) if match.group(1) else slots[match.group(2)]

    return TOKEN_RE.sub(fill, template)


def render_summary(snapshot, diff, lang):
    data, effective = load_strings(lang)
    t = Strings(data, effective)
    d = diff or {}
    dt = d.get("totals") or {}
    tot = snapshot.get("totals") or {}
    repos = tot.get("repos") or {}
    scope = snapshot.get("scope") or {}
    by_band = tot.get("by_band") or {}
    open_now = _int(dt.get("curr_open", tot.get("open")))
    baseline = bool(d.get("baseline", True))
    lines = [t.plain("summary.line_title", owners=_scope_label(scope),
                     date=(snapshot.get("generated_at") or "")[:10])]
    if baseline:
        lines.append(t.plain("summary.open_baseline", open=open_now,
                             reason=t.plain(f"baseline.short.{_baseline_reason(d.get('reason'))}")))
    else:
        lines.append(t.plain("summary.open", open=open_now, delta=_signed(_int(dt.get("delta")), "-"),
                             lost=_int(dt.get("lost_coverage"))))
        lines.append(t.plain("summary.changes", closed=len(d.get("closed") or []),
                             dismissed=len(d.get("dismissed") or []), new=len(d.get("new") or [])))
    lines.append(t.plain("summary.bands", p1=_int(by_band.get("P1")), p2=_int(by_band.get("P2")),
                         p3=_int(by_band.get("P3"))))
    lines.append(t.plain("summary.coverage", scanned=_int(repos.get("scanned")),
                         total=t.count(_int(repos.get("total")), "repo"), none=len(repos.get("no_coverage") or [])))
    top = [r for r in snapshot.get("ranking") or [] if _int(r.get("open")) > 0][:3]
    if top:
        lines.append(t.plain("summary.top", repos="; ".join(
            t.plain("summary.top_item", repo=r.get("repo"), score=_int(r.get("max_priority"))) for r in top)))
    wave1 = next((w for w in snapshot.get("waves") or [] if _int(w.get("wave")) == 1), None)
    if wave1 and wave1.get("alerts"):
        lines.append(t.plain("summary.wave1", alerts=t.count(len(wave1["alerts"]), "alert"),
                             repos=t.count(len(wave1.get("repos") or []), "repo")))
    partial = sorted(o for o, s in (scope.get("strategy") or {}).items() if s == "per-repo")
    public_only = sorted(scope.get("public_only") or [])
    if partial or public_only:
        # One line for both, so the summary stays within 10 lines (Ruling R25 adds public_only).
        text = t.plain("summary.partial", owners=", ".join(partial)) if partial else ""
        if public_only:
            text += ("; " if text else "") + t.plain("summary.public_only", owners=", ".join(public_only))
        lines.append(text)
    reached = d.get("repos_reached_zero") or []
    if reached and not baseline:
        shown = ", ".join(reached[:5]) + (f" (+{len(reached) - 5})" if len(reached) > 5 else "")
        lines.append(t.plain("summary.reached_zero", repos=shown))
    lines.append(t.plain("summary.full_report"))
    return "\n".join(lines[:10]) + "\n"


def _fail(msg, hint):
    print(json.dumps({"error": msg, "hint": hint}, sort_keys=True))
    print(f"error: {msg}", file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, type=Path, help="day directory holding snapshot.json and diff.json")
    ap.add_argument("--lang", default=DEFAULT_LANG, help="report language (en, es); unknown falls back to en")
    ap.add_argument("--narrative", type=Path, help="plain-text narrative file to include in the summary")
    args = ap.parse_args(argv)
    day = args.dir
    try:
        snapshot = json.loads((day / "snapshot.json").read_text(encoding="utf-8"))
        diff = json.loads((day / "diff.json").read_text(encoding="utf-8"))
        narrative = args.narrative.read_text(encoding="utf-8") if args.narrative else None
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read report inputs in {day}: {exc}",
                     "run snapshot.py and diff_snapshots.py -o DAY_DIR/diff.json first, or pass the right --dir")
    effective = load_strings(args.lang)[1]
    if effective != _lang_code(args.lang):
        print(f"warning: language {args.lang!r} not available, using {effective}", file=sys.stderr)
    history = load_history(day.resolve().parent)
    report = day / "report.html"
    summary = day / "summary.txt"
    today = day.resolve().name if DATE_RE.match(day.resolve().name) else None
    report.write_text(render_html(snapshot, diff, history, effective, narrative, today=today), encoding="utf-8")
    summary.write_text(render_summary(snapshot, diff, effective), encoding="utf-8")
    print(json.dumps({"report": str(report), "summary": str(summary), "lang": effective}, sort_keys=True))
    print(f"wrote {report} and {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
