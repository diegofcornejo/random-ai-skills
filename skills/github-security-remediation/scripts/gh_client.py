#!/usr/bin/env python3
"""Thin wrapper around the `gh` CLI: argv building, pagination, error parsing, rate-limit backoff."""
import json
import os
import re
import subprocess
import sys
import time

DEFAULT_HOST = "github.com"
_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")
_RATE_RE = re.compile(r"rate limit", re.IGNORECASE)


class GhApiError(Exception):
    def __init__(self, status, message, path, hint=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.path = path
        self.hint = hint

    def __str__(self):
        s = f"{self.message} (HTTP {self.status})" if self.status else self.message
        s += f" [{self.path}]"
        return f"{s} - {self.hint}" if self.hint else s


def _hint(status, message, stderr):
    text = f"{message}\n{stderr}"
    if "gh auth login" in text or status == 401:
        return "Run: gh auth login"
    if "security_events" in text:
        return "Run: gh auth refresh -s security_events"
    return None


def _field_args(fields):
    args = []
    for k, v in fields.items():
        if isinstance(v, bool):
            args += ["-F", f"{k}={'true' if v else 'false'}"]
        elif isinstance(v, int):
            args += ["-F", f"{k}={v}"]
        else:
            args += ["-f", f"{k}={v}"]
    return args


class GhClient:
    def __init__(self, host=DEFAULT_HOST, runner=subprocess.run, sleep=time.sleep, max_retries=5):
        self.host = host
        self.runner = runner
        self.sleep = sleep
        self.max_retries = max_retries

    def get(self, path, params=None, paginate=False):
        argv = ["gh", "api", "--hostname", self.host, "-X", "GET",
                "-H", "Accept: application/vnd.github+json", path]
        argv += _field_args(params or {})
        if paginate:
            argv += ["--paginate", "--slurp"]
        data = self._call(argv, path)
        if paginate and isinstance(data, list):
            flat = []
            for page in data:
                flat.extend(page) if isinstance(page, list) else flat.append(page)
            return flat
        return data

    def patch(self, path, fields):
        argv = ["gh", "api", "--hostname", self.host, "-X", "PATCH",
                "-H", "Accept: application/vnd.github+json", path]
        argv += _field_args(fields)
        return self._call(argv, path)

    def run_json(self, args):
        argv = ["gh"] + list(args)
        env = None
        if self.host != DEFAULT_HOST:
            env = dict(os.environ, GH_HOST=self.host)
        return self._call(argv, " ".join(args), env=env)

    def _call(self, argv, path, env=None):
        kwargs = {"capture_output": True, "text": True}
        if env is not None:
            kwargs["env"] = env
        attempt = 0
        while True:
            try:
                proc = self.runner(argv, **kwargs)
            except FileNotFoundError:
                raise GhApiError(None, "gh CLI not found", path, "Install GitHub CLI: https://cli.github.com")
            if proc.returncode == 0:
                return self._parse_ok(proc.stdout, path)
            err = self._parse_error(proc, path)
            if err.status in (403, 429) and _RATE_RE.search(err.message) and attempt < self.max_retries:
                delay = min(60 * 2 ** attempt, 900)
                print(f"rate limited on {path}; retrying in {delay}s", file=sys.stderr)
                self.sleep(delay)
                attempt += 1
                continue
            raise err

    @staticmethod
    def _parse_ok(stdout, path):
        if not stdout or not stdout.strip():
            return {}  # e.g. HTTP 204
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            raise GhApiError(None, "gh returned non-JSON output", path)

    @staticmethod
    def _parse_error(proc, path):
        stderr = (proc.stderr or "").strip()
        m = _STATUS_RE.search(stderr)
        status = int(m.group(1)) if m else None
        message = None
        try:
            body = json.loads(proc.stdout or "")
            if isinstance(body, dict):
                message = body.get("message")
        except json.JSONDecodeError:
            pass
        if not message:
            message = stderr or f"gh exited with code {proc.returncode}"
        return GhApiError(status, message, path, _hint(status, message, stderr))
