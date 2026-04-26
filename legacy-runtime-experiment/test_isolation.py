"""
Session isolation test: two concurrent sessions, each given a different
secret number, verifying memory doesn't leak across sessions.

Session A: told to remember 12345.
Session B: told to remember 67890.
Each session is then asked what number it was given.

Writes isolation-results.json.

NOTE: agent is configured memory_mode=NO_MEMORY at deploy, so true cross-
invocation memory WILL NOT persist. What we're testing here is:
  1. The two sessions get different microVMs / context.
  2. Neither leaks the other's number.
Both "I don't remember" for A and "I don't remember" for B is a PASS —
what would be a FAIL is session A mentioning 67890 or vice versa.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test_isolation")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
RESULTS_PATH = HERE / "isolation-results.json"

SESSION_A_NUMBER = 12345
SESSION_B_NUMBER = 67890


def _load_arn() -> str:
    env_arn = os.environ.get("AGENT_ARN")
    if env_arn:
        return env_arn
    if not DEPLOY_LOG.exists():
        raise FileNotFoundError(f"{DEPLOY_LOG} not found; run deploy_agent.py first or set AGENT_ARN")
    data = json.loads(DEPLOY_LOG.read_text())
    arn = data.get("agent_arn")
    if not arn:
        raise ValueError("agent_arn missing from deploy-log.json")
    return arn


def _read_stream(stream: Any) -> str:
    chunks = []
    try:
        for chunk in stream:
            if isinstance(chunk, (bytes, bytearray)):
                chunks.append(bytes(chunk))
            elif isinstance(chunk, dict):
                inner = chunk.get("chunk") or chunk
                payload = inner.get("bytes") if isinstance(inner, dict) else None
                if payload:
                    chunks.append(payload)
    except TypeError:
        if hasattr(stream, "read"):
            data = stream.read()
            if data:
                chunks.append(data)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _invoke(client, agent_arn: str, session_id: str, prompt: str) -> Dict[str, Any]:
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    try:
        r = client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=session_id,
            payload=payload,
            qualifier="DEFAULT",
        )
    except ClientError as exc:
        return {
            "prompt": prompt,
            "session_id": session_id,
            "error": str(exc),
            "duration_seconds": time.perf_counter() - started,
            "started_at": started_at.isoformat(),
        }
    body = _read_stream(r.get("response"))
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    meta = r.get("ResponseMetadata") or {}
    headers = dict(meta.get("HTTPHeaders") or {})
    # surface any x-amzn-* headers — potential microVM identity hints.
    amzn_headers = {k: v for k, v in headers.items() if k.lower().startswith("x-amzn")}
    return {
        "prompt": prompt,
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "duration_seconds": time.perf_counter() - started,
        "status_code": meta.get("HTTPStatusCode"),
        "request_id": meta.get("RequestId"),
        "x_amzn_headers": amzn_headers,
        "runtime_session_id_response": r.get("runtimeSessionId"),
        "response_body_raw": body,
        "response_body_parsed": parsed,
    }


def _extract_text(parsed: Any) -> str:
    if isinstance(parsed, dict):
        r = parsed.get("response")
        if isinstance(r, str):
            return r
        return json.dumps(r) if r is not None else ""
    return str(parsed)


def _run_session(
    client,
    agent_arn: str,
    session_label: str,
    my_number: int,
    other_number: int,
    results_sink: Dict[str, Any],
) -> None:
    session_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    logger.info("[%s] session_id=%s number=%d", session_label, session_id, my_number)

    first = _invoke(
        client,
        agent_arn,
        session_id,
        f"Remember the number {my_number}. Acknowledge that you will remember it.",
    )
    second = _invoke(
        client,
        agent_arn,
        session_id,
        "What number did I just ask you to remember?",
    )

    first_text = _extract_text(first.get("response_body_parsed"))
    second_text = _extract_text(second.get("response_body_parsed"))

    mentions_own = str(my_number) in (first_text + second_text)
    leaked_other = str(other_number) in (first_text + second_text)

    results_sink[session_label] = {
        "session_id": session_id,
        "my_number": my_number,
        "other_number": other_number,
        "first_invoke": first,
        "second_invoke": second,
        "mentions_own_number": mentions_own,
        "leaked_other_session_number": leaked_other,
    }


def main() -> int:
    agent_arn = _load_arn()
    client = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])

    shared: Dict[str, Any] = {}
    threads: List[threading.Thread] = [
        threading.Thread(
            target=_run_session,
            args=(client, agent_arn, "A", SESSION_A_NUMBER, SESSION_B_NUMBER, shared),
        ),
        threading.Thread(
            target=_run_session,
            args=(client, agent_arn, "B", SESSION_B_NUMBER, SESSION_A_NUMBER, shared),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    leaked = any(shared[k]["leaked_other_session_number"] for k in ("A", "B"))
    distinct_sessions = shared["A"]["session_id"] != shared["B"]["session_id"]

    # Best-effort: list sessions for this runtime (if API supports it).
    control = boto3.client("bedrock-agentcore-control", region_name=os.environ["AWS_REGION"])
    sessions_metadata: Dict[str, Any] = {}
    for method in ("list_agent_runtime_sessions", "list_sessions"):
        if hasattr(control, method):
            try:
                agent_id = agent_arn.split("/")[-1]
                # try both call shapes
                try:
                    resp = getattr(control, method)(agentRuntimeId=agent_id)
                except TypeError:
                    resp = getattr(control, method)(agentRuntimeArn=agent_arn)
                sessions_metadata[method] = resp
                break
            except ClientError as exc:
                sessions_metadata[method + "_error"] = str(exc)
            except Exception as exc:  # pragma: no cover
                sessions_metadata[method + "_error"] = repr(exc)
    if not sessions_metadata:
        sessions_metadata["note"] = "no list_sessions-style method available on this boto3 client"

    summary = {
        "agent_arn": agent_arn,
        "sessions": shared,
        "distinct_session_ids": distinct_sessions,
        "cross_contamination_detected": leaked,
        "isolation_pass": (not leaked) and distinct_sessions,
        "sessions_metadata": sessions_metadata,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote %s", RESULTS_PATH)

    print("\n=== Isolation summary ===")
    print(f"Session A id: {shared['A']['session_id']}")
    print(f"Session B id: {shared['B']['session_id']}")
    print(f"A leaked B's number? {shared['A']['leaked_other_session_number']}")
    print(f"B leaked A's number? {shared['B']['leaked_other_session_number']}")
    print(f"Isolation pass: {summary['isolation_pass']}")
    return 0 if summary["isolation_pass"] else 8


if __name__ == "__main__":
    sys.exit(main())
