#!/usr/bin/env python
"""Coolify deploy tool for Vaani.

Everything the agent needs to create, configure, deploy and inspect the Vaani
stack on Coolify — behind ONE script, so a single narrow permission rule
(`Bash(python tools/coolify.py:*)`) covers it instead of blanket curl access.

Credentials come from .env. Nothing is hardcoded here.

    python tools/coolify.py servers
    python tools/coolify.py apps
    python tools/coolify.py create-compose --name vaani --repo https://github.com/Vishnuuss/vaani
    python tools/coolify.py set-env <uuid> --file vaani-coolify.env
    python tools/coolify.py get-env <uuid>
    python tools/coolify.py patch <uuid> --json '{"git_submodules_enabled": true}'
    python tools/coolify.py deploy <uuid>
    python tools/coolify.py status <uuid>
    python tools/coolify.py deployments [--uuid <deployment_uuid>]
    python tools/coolify.py raw GET /applications
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import error, request

# The Windows console is cp1252. Coolify's log output contains emoji and its
# JSON contains Telugu, so printing a response used to crash the tool with
# UnicodeEncodeError halfway through the answer it had already fetched.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict:
    """Read .env without a dependency. Later keys win, `export` tolerated."""
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            key, sep, value = line.partition("=")
            if sep:
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("COOLIFY_")})
    return env


ENV = load_env()
BASE = ENV.get("COOLIFY_API_URL", "").rstrip("/")
TOKEN = ENV.get("COOLIFY_API_TOKEN", "")


def api(method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
    if not BASE or not TOKEN:
        sys.exit("COOLIFY_API_URL / COOLIFY_API_TOKEN missing from .env")
    url = f"{BASE}/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body.strip() else None)
    except error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except error.URLError as e:
        sys.exit(f"cannot reach {BASE}: {e.reason}")


def show(status: int, body: object, *, limit: int = 6000) -> None:
    print(f"HTTP {status}")
    text = json.dumps(body, indent=1, ensure_ascii=False) if not isinstance(body, str) else body
    if not limit:
        limit = len(text)
    print(text[:limit] + ("\n…truncated" if len(text) > limit else ""))
    if status >= 400:
        sys.exit(1)


def parse_env_file(path: Path) -> list[tuple[str, str]]:
    """Read a deployment .env. Inline comments are NOT stripped -- a '#' inside
    a generated secret is a legal character and stripping it would silently
    corrupt the value."""
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            pairs.append((key.strip(), value.strip()))
    return pairs


# --- commands ---------------------------------------------------------------
def cmd_servers(_):
    show(*api("GET", "/servers"))


def cmd_apps(_):
    status, body = api("GET", "/applications")
    if status >= 400:
        show(status, body)
    rows = body if isinstance(body, list) else [body]
    print(f"HTTP {status} — {len(rows)} application(s)")
    for a in rows:
        print(f"  {a.get('name')}  uuid={a.get('uuid')}  "
              f"pack={a.get('build_pack')}  status={a.get('status')}  "
              f"repo={a.get('git_repository')}@{a.get('git_branch')}")


def cmd_create_compose(a):
    payload = {
        "project_uuid": a.project or ENV.get("COOLIFY_PROJECT_UUID"),
        "server_uuid": a.server or ENV.get("COOLIFY_SERVER_UUID"),
        "environment_uuid": a.environment or ENV.get("COOLIFY_ENVIRONMENT_UUID"),
        "git_repository": a.repo,
        "git_branch": a.branch,
        "build_pack": "dockercompose",
        "docker_compose_location": a.compose,
        "name": a.name,
        "instant_deploy": False,
    }
    show(*api("POST", "/applications/public", payload))


def cmd_patch(a):
    show(*api("PATCH", f"/applications/{a.uuid}", json.loads(a.json)))


def cmd_get_env(a):
    show(*api("GET", f"/applications/{a.uuid}/envs"))


def cmd_set_env(a):
    path = Path(a.file)
    if not path.is_absolute():
        path = ROOT / path
    pairs = parse_env_file(path)
    print(f"{len(pairs)} variable(s) from {path}")
    ok = failed = 0
    for key, value in pairs:
        status, body = api("POST", f"/applications/{a.uuid}/envs",
                           {"key": key, "value": value, "is_preview": False})
        if status >= 400:
            # Already exists -> update it instead.
            status, body = api("PATCH", f"/applications/{a.uuid}/envs",
                               {"key": key, "value": value, "is_preview": False})
        if status < 400:
            ok += 1
            print(f"  ok      {key}")
        else:
            failed += 1
            print(f"  FAILED  {key}: {json.dumps(body)[:200]}")
    print(f"\n{ok} set, {failed} failed")
    if failed:
        sys.exit(1)


def cmd_deploy(a):
    # Coolify moved /deploy from GET to POST (405 "This endpoint has changed to
    # a POST request."). GET is kept as a fallback so this still works against
    # an older install.
    query = f"/deploy?uuid={a.uuid}&force={'true' if a.force else 'false'}"
    status, body = api("POST", query)
    if status == 405:
        status, body = api("GET", query)
    show(status, body)


def cmd_status(a):
    status, body = api("GET", f"/applications/{a.uuid}")
    if status >= 400:
        show(status, body)
    keep = ("name", "uuid", "status", "build_pack", "git_repository", "git_branch",
            "git_commit_sha", "docker_compose_location", "fqdn", "ports_exposes")
    print(f"HTTP {status}")
    for k in keep:
        if k in body:
            print(f"  {k}: {body[k]}")


def cmd_wait(a):
    """Block until the newest deployment settles.

    `status <uuid>` is NOT a substitute. It reports the RUNNING container, which
    is the OLD one while a new build is still going, so a wait loop on
    "running:healthy" returns immediately and the next command tests stale code.
    That happened on 2026-08-28: a download fix was verified against the
    previous image and looked unfixed.
    """
    import time as _t
    deadline = _t.time() + a.timeout
    last = None
    while _t.time() < deadline:
        status, body = api("GET", "/deployments")
        rows = body if isinstance(body, list) else [body]
        mine = [r for r in rows if isinstance(r, dict)
                and r.get("application_id") in (a.uuid, None)
                or (isinstance(r, dict) and r.get("deployment_uuid"))]
        cur = (mine[0] if mine else {}) if rows else {}
        state = (cur or {}).get("status")
        if state != last:
            print(f"  {state}  {(cur or {}).get('commit','')[:8]}", flush=True)
            last = state
        if state in (None, "finished", "failed", "cancelled-by-user"):
            print(f"deployment {state}")
            return 0 if state in (None, "finished") else sys.exit(1)
        _t.sleep(a.interval)
    sys.exit(f"still not settled after {a.timeout}s (last status {last})")


def cmd_deployments(a):
    path = f"/deployments/{a.uuid}" if a.uuid else "/deployments"
    show(*api("GET", path), limit=a.limit)


def cmd_raw(a):
    payload = json.loads(a.json) if a.json else None
    show(*api(a.method.upper(), a.path, payload), limit=a.limit)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("servers").set_defaults(fn=cmd_servers)
    sub.add_parser("apps").set_defaults(fn=cmd_apps)

    c = sub.add_parser("create-compose")
    c.add_argument("--name", required=True)
    c.add_argument("--repo", required=True)
    c.add_argument("--branch", default="main")
    c.add_argument("--compose", default="/docker-compose.yaml")
    c.add_argument("--project")
    c.add_argument("--server")
    c.add_argument("--environment")
    c.set_defaults(fn=cmd_create_compose)

    c = sub.add_parser("patch")
    c.add_argument("uuid")
    c.add_argument("--json", required=True)
    c.set_defaults(fn=cmd_patch)

    c = sub.add_parser("get-env")
    c.add_argument("uuid")
    c.set_defaults(fn=cmd_get_env)

    c = sub.add_parser("set-env")
    c.add_argument("uuid")
    c.add_argument("--file", required=True)
    c.set_defaults(fn=cmd_set_env)

    c = sub.add_parser("deploy")
    c.add_argument("uuid")
    c.add_argument("--force", action="store_true")
    c.set_defaults(fn=cmd_deploy)

    c = sub.add_parser("status")
    c.add_argument("uuid")
    c.set_defaults(fn=cmd_status)

    c = sub.add_parser("wait", help="block until the newest deployment settles")
    c.add_argument("uuid")
    c.add_argument("--timeout", type=int, default=1200)
    c.add_argument("--interval", type=int, default=15)
    c.set_defaults(fn=cmd_wait)

    c = sub.add_parser("deployments")
    c.add_argument("--uuid")
    c.add_argument("--limit", type=int, default=6000)
    c.set_defaults(fn=cmd_deployments)

    c = sub.add_parser("raw")
    c.add_argument("method")
    c.add_argument("path")
    c.add_argument("--json")
    # `raw GET /applications/<uuid>` is 20k+ of JSON and the fields worth
    # reading -- docker_compose_domains among them -- sit well past 6000 chars,
    # so the default cap put the answer in the truncated tail every time.
    # 0 means no cap.
    c.add_argument("--limit", type=int, default=6000)
    c.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
