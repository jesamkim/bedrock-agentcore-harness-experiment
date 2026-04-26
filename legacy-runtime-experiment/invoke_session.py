"""
Invoke the deployed agent twice on the SAME session to measure cold vs warm latency.

Reads the agent ARN from deploy-log.json (or env var AGENT_ARN).
Writes invoke-results.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("invoke_session")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
RESULTS_PATH = HERE / "invoke-results.json"

PROMPT = "What time is it right now? Also compute 17+25."


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


def _read_response_stream(stream: Any) -> str:
    """invoke_agent_runtime returns an EventStream-like iterable of bytes."""
    chunks = []
    try:
        for chunk in stream:
            if isinstance(chunk, (bytes, bytearray)):
                chunks.append(bytes(chunk))
            elif isinstance(chunk, dict):
                # older SDKs wrap bytes in a dict like {"chunk": {"bytes": b"..."}}
                inner = chunk.get("chunk") or chunk
                payload = inner.get("bytes") if isinstance(inner, dict) else None
                if payload:
                    chunks.append(payload)
    except TypeError:
        # streaming body: .read()
        data = stream.read() if hasattr(stream, "read") else b""
        if data:
            chunks.append(data)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _single_invoke(
    client, agent_arn: str, session_id: str, prompt: str, label: str
) -> Dict[str, Any]:
    payload_bytes = json.dumps({"prompt": prompt}).encode("utf-8")
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=session_id,
            payload=payload_bytes,
            qualifier="DEFAULT",
        )
    except ClientError as exc:
        elapsed = time.perf_counter() - started
        logger.error("%s invoke failed after %.2fs: %s", label, elapsed, exc)
        return {
            "label": label,
            "session_id": session_id,
            "prompt": prompt,
            "error": str(exc),
            "duration_seconds": elapsed,
            "started_at": started_at.isoformat(),
        }
    body = _read_response_stream(response.get("response"))
    elapsed = time.perf_counter() - started
    finished_at = datetime.now(timezone.utc)

    # Gather interesting metadata. Redact any auth-ish headers just in case.
    meta = response.get("ResponseMetadata") or {}
    headers = dict(meta.get("HTTPHeaders") or {})
    for h in list(headers.keys()):
        if "authorization" in h.lower() or "x-amz-security-token" in h.lower():
            headers[h] = "<redacted>"

    return {
        "label": label,
        "session_id": session_id,
        "prompt": prompt,
        "duration_seconds": elapsed,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status_code": meta.get("HTTPStatusCode"),
        "request_id": meta.get("RequestId"),
        "response_headers": headers,
        "response_body_raw": body,
        "response_body_parsed": _try_json(body),
        "contentType": response.get("contentType"),
        "runtimeSessionId": response.get("runtimeSessionId"),
    }


def main() -> int:
    agent_arn = _load_arn()
    logger.info("Invoking %s", agent_arn)

    client = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])

    # 33+ chars required by the service.
    session_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    logger.info("Session id: %s", session_id)

    cold = _single_invoke(client, agent_arn, session_id, PROMPT, label="cold")
    logger.info("Cold: %.2fs  status=%s", cold["duration_seconds"], cold.get("status_code"))

    warm = _single_invoke(client, agent_arn, session_id, PROMPT, label="warm")
    logger.info("Warm: %.2fs  status=%s", warm["duration_seconds"], warm.get("status_code"))

    summary = {
        "agent_arn": agent_arn,
        "session_id": session_id,
        "cold": cold,
        "warm": warm,
        "delta_seconds": (cold.get("duration_seconds") or 0) - (warm.get("duration_seconds") or 0),
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote %s", RESULTS_PATH)

    print("\n=== Invoke summary ===")
    print(f"Cold: {cold.get('duration_seconds'):.2f}s status={cold.get('status_code')}")
    print(f"Warm: {warm.get('duration_seconds'):.2f}s status={warm.get('status_code')}")
    print(f"Warm speedup: {summary['delta_seconds']:.2f}s")
    if isinstance(cold.get("response_body_parsed"), dict):
        resp = cold["response_body_parsed"].get("response")
        if resp:
            print(f"Cold response (first 200 chars): {str(resp)[:200]}")
    return 0 if cold.get("status_code") == 200 and warm.get("status_code") == 200 else 6


if __name__ == "__main__":
    sys.exit(main())
