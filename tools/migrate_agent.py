#!/usr/bin/env python
"""Move an agent from the LOCAL Dograh database to a remote Dograh install.

Reads straight out of local Postgres (via docker exec) and pushes through the
remote REST API, so the remote side gets properly validated records rather than
a raw SQL dump between two schemas.

What travels:
  1. the tools the agent references  (recreated remotely; UUIDs are remapped)
  2. the workflow itself             (prompt, greeting, extraction variables)
  3. optionally the model config     (LLM/TTS/STT provider keys)

    python tools/migrate_agent.py --workflow-id 5 \
        --remote https://vaani-api.bswealthfinance.com --api-key <key> --dry-run

Drop --dry-run to actually write. --with-model-config also copies the provider
API keys out of the local organization_configurations row.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from urllib import error, request

PG_CONTAINER = "dograh-vapi-postgres-1"


def psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
         "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        sys.exit(f"local postgres query failed:\n{out.stderr.strip()}")
    return out.stdout.strip()


class Remote:
    def __init__(self, base: str, api_key: str, dry_run: bool):
        self.base = base.rstrip("/")
        self.key = api_key
        self.dry_run = dry_run

    def call(self, method: str, path: str, payload=None):
        url = f"{self.base}/api/v1/{path.lstrip('/')}"
        if self.dry_run and method != "GET":
            print(f"    DRY-RUN would {method} {path}")
            return 200, {"uuid": "dry-run", "id": 0}
        data = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self.key)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(req, timeout=90) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(body) if body.strip() else None)
        except error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, body


def local_workflow(workflow_id: int) -> tuple[str, dict]:
    name = psql(f"SELECT name FROM workflows WHERE id={workflow_id};")
    if not name:
        sys.exit(f"no local workflow with id {workflow_id}")
    # The definition the browser test runs actually used -- prefer the newest,
    # which is what the editor last saved, not the older published row.
    raw = psql(
        "SELECT workflow_json::text FROM workflow_definitions "
        f"WHERE workflow_id={workflow_id} ORDER BY id DESC LIMIT 1;"
    )
    return name, json.loads(raw)


def local_tools(uuids: list[str]) -> list[dict]:
    if not uuids:
        return []
    quoted = ",".join(f"'{u}'" for u in uuids)
    raw = psql(
        "SELECT json_agg(row_to_json(t))::text FROM ("
        "  SELECT tool_uuid, name, description, category, icon, icon_color, definition"
        f"  FROM tools WHERE tool_uuid IN ({quoted})"
        ") t;"
    )
    return json.loads(raw) if raw and raw != "null" else []


def local_model_config() -> dict | None:
    raw = psql(
        "SELECT value::text FROM organization_configurations "
        "WHERE key='MODEL_CONFIGURATION_V2' LIMIT 1;"
    )
    return json.loads(raw) if raw else None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workflow-id", type=int, required=True)
    p.add_argument("--remote", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--name", help="override the remote agent name")
    p.add_argument("--with-model-config", action="store_true",
                   help="also copy the provider API keys")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    remote = Remote(a.remote, a.api_key, a.dry_run)

    print("== reading local ==")
    name, definition = local_workflow(a.workflow_id)
    node = definition["nodes"][0]["data"]
    tool_uuids = list(node.get("tool_uuids") or [])
    tools = local_tools(tool_uuids)
    print(f"  workflow  {name!r}")
    print(f"  nodes/edges {len(definition['nodes'])}/{len(definition['edges'])}, "
          f"prompt {len(node.get('prompt',''))} chars")
    print(f"  tools     {[t['name'] for t in tools]}")

    print("\n== checking the remote is reachable and the key works ==")
    s, me = remote.call("GET", "workflow/fetch")
    if s >= 400:
        sys.exit(f"  remote rejected the key: HTTP {s} {json.dumps(me)[:200]}")
    existing = me if isinstance(me, list) else (me or {}).get("workflows", [])
    print(f"  OK -- {len(existing)} workflow(s) already there")

    print("\n== recreating tools ==")
    uuid_map = {}
    for t in tools:
        payload = {
            "name": t["name"],
            "description": t.get("description"),
            "category": t["category"],
            "icon": t.get("icon"),
            "icon_color": t.get("icon_color"),
            "definition": t["definition"],
        }
        s, b = remote.call("POST", "tools/", payload)
        if s >= 400:
            sys.exit(f"  tool {t['name']!r} failed: HTTP {s} {json.dumps(b)[:300]}")
        uuid_map[t["tool_uuid"]] = b.get("tool_uuid", "dry-run")
        print(f"  {t['name']!r}  {t['tool_uuid'][:8]}… -> {uuid_map[t['tool_uuid']][:8]}…")

    # The remote issues its own tool UUIDs, so the node must be rewritten or the
    # agent would reference tools that do not exist there.
    node["tool_uuids"] = [uuid_map.get(u, u) for u in tool_uuids]

    print("\n== creating the workflow ==")
    s, b = remote.call("POST", "workflow/create/definition",
                       {"name": a.name or name, "workflow_definition": definition})
    if s >= 400:
        sys.exit(f"  failed: HTTP {s} {json.dumps(b)[:400]}")
    new_id = b.get("id")
    print(f"  created id={new_id} name={b.get('name')!r}")

    if a.with_model_config:
        print("\n== copying model configuration (provider API keys) ==")
        cfg = local_model_config()
        if not cfg:
            print("  none found locally, skipped")
        else:
            pipeline = (cfg.get("byok") or {}).get("pipeline") or {}
            for kind in ("llm", "tts", "stt"):
                spec = pipeline.get(kind) or {}
                print(f"  {kind}: {spec.get('provider')} / {spec.get('model')}")
            s, b = remote.call("PUT", "organizations/model-configurations/v2", cfg)
            print(f"  push -> HTTP {s} {json.dumps(b)[:200] if s>=400 else 'ok'}")

    print("\nDone." + ("  (DRY RUN -- nothing was written)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
