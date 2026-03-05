#!/usr/bin/env python3
import hashlib


def canonical_event_hash(
    execution_id: str,
    agent_id: str,
    state: str,
    output_hash: str,
    prev_event_hash: str | None,
    algorithm: str = "sha256",
) -> str:
    prev = prev_event_hash or ""
    payload = f"{execution_id}|{agent_id}|{state}|{output_hash}|{prev}"
    algo = algorithm.lower()
    if algo == "sha256":
        return hashlib.sha256(payload.encode()).hexdigest()
    if algo == "md5":
        return hashlib.md5(payload.encode()).hexdigest()  # nosec B324
    raise ValueError(f"Unsupported hash algorithm: {algorithm}")
