#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

try:
    from scripts.runtime_hash_chain import canonical_event_hash
except ModuleNotFoundError:
    from runtime_hash_chain import canonical_event_hash


def load_db_url() -> str:
    env_url = os.getenv("OPENCLAW_DB_URL", "").strip()
    if env_url:
        return env_url

    env_file = os.path.expanduser("~/apps/.env.production")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("OPENCLAW_DB_URL="):
                    return line.split("=", 1)[1].strip()
    return ""


def validate_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return bool(u.scheme and u.netloc and u.path)
    except Exception:
        return False


def main() -> int:
    db_url = load_db_url()
    if not db_url or not validate_url(db_url):
        print("ERROR: OPENCLAW_DB_URL no disponible o invalida")
        return 2

    root = Path(__file__).resolve().parents[1]
    hash_algorithm = "sha256"
    cp_file = root / "control-plane" / "openclaw.json"
    if cp_file.exists():
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        hash_algorithm = data.get("audit", {}).get("hash_algorithm", "sha256")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, execution_id, agent_id, state, output_hash, prev_event_hash, event_hash
                FROM mem_audit.execution_ledger
                ORDER BY execution_id, event_id
                """
            )
            rows = cur.fetchall()

        last_hash_by_exec = {}
        broken = []
        for event_id, execution_id, agent_id, state, output_hash, prev_hash, event_hash in rows:
            last_hash = last_hash_by_exec.get(execution_id)
            if last_hash is None:
                if prev_hash not in (None, ""):
                    broken.append((event_id, execution_id, "primer evento con prev_event_hash no nulo"))
            else:
                if prev_hash != last_hash:
                    broken.append((event_id, execution_id, "prev_event_hash no coincide con hash previo"))

            expected = canonical_event_hash(
                execution_id=execution_id,
                agent_id=agent_id,
                state=state,
                output_hash=output_hash,
                prev_event_hash=prev_hash,
                algorithm=hash_algorithm,
            )
            if event_hash != expected:
                broken.append((event_id, execution_id, "event_hash no cumple formula canonica"))
            last_hash_by_exec[execution_id] = event_hash

        if broken:
            print("AUDIT_CHAIN: BROKEN")
            for b in broken[:20]:
                print(f"- event_id={b[0]} execution_id={b[1]} motivo={b[2]}")
            return 1

        print("AUDIT_CHAIN: OK")
        print(f"Eventos revisados: {len(rows)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
