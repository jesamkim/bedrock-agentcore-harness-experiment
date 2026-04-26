"""
Explicit tool-calling verification.

Sends two prompts that should each trigger a different tool, then verifies
the responses contain plausible tool output (correct sum, ISO timestamp).

Writes tool-results.json. Exits non-zero if either verification fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
logger = logging.getLogger("test_tools")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
RESULTS_PATH = HERE / "tool-results.json"


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


def _invoke(client, agent_arn: str, prompt: str) -> Dict[str, Any]:
    session_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
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
            "started_at": started_at.isoformat(),
            "duration_seconds": time.perf_counter() - started,
        }
    body = _read_stream(r.get("response"))
    parsed: Any
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    return {
        "prompt": prompt,
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "duration_seconds": time.perf_counter() - started,
        "status_code": (r.get("ResponseMetadata") or {}).get("HTTPStatusCode"),
        "request_id": (r.get("ResponseMetadata") or {}).get("RequestId"),
        "response_body_raw": body,
        "response_body_parsed": parsed,
    }


def _tool_names_from(parsed: Any) -> list[str]:
    if isinstance(parsed, dict):
        tu = parsed.get("tool_uses")
        if isinstance(tu, list):
            return [t.get("name") for t in tu if isinstance(t, dict) and t.get("name")]
    return []


def _extract_response_text(parsed: Any) -> str:
    if isinstance(parsed, dict):
        r = parsed.get("response")
        if isinstance(r, str):
            return r
        if isinstance(r, (list, dict)):
            return json.dumps(r)
    return str(parsed)


def _verify_sum(parsed: Any) -> Dict[str, Any]:
    text = _extract_response_text(parsed)
    tool_names = _tool_names_from(parsed)
    expected = 888 + 1234  # 2122
    numbers_found = [int(n) for n in re.findall(r"\b\d{3,6}\b", text)]
    return {
        "expected": expected,
        "numbers_found_in_response": numbers_found,
        "tool_names_reported": tool_names,
        "contains_expected": expected in numbers_found,
        "add_numbers_called": "add_numbers" in tool_names,
        "pass": (expected in numbers_found) or ("add_numbers" in tool_names),
    }


ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _verify_time(parsed: Any) -> Dict[str, Any]:
    text = _extract_response_text(parsed)
    tool_names = _tool_names_from(parsed)
    iso_match = ISO_RE.search(text)
    return {
        "iso_timestamp_found": bool(iso_match),
        "iso_match": iso_match.group(0) if iso_match else None,
        "tool_names_reported": tool_names,
        "get_current_time_called": "get_current_time" in tool_names,
        "pass": bool(iso_match) or ("get_current_time" in tool_names),
    }


def main() -> int:
    agent_arn = _load_arn()
    client = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])

    logger.info("Prompt 1: arithmetic")
    sum_invoke = _invoke(client, agent_arn, "What is 888 plus 1234?")
    sum_check = _verify_sum(sum_invoke.get("response_body_parsed"))
    logger.info("sum check: %s", sum_check)

    logger.info("Prompt 2: current time")
    time_invoke = _invoke(client, agent_arn, "What time is it?")
    time_check = _verify_time(time_invoke.get("response_body_parsed"))
    logger.info("time check: %s", time_check)

    overall = sum_check["pass"] and time_check["pass"]
    summary = {
        "agent_arn": agent_arn,
        "sum_test": {"invoke": sum_invoke, "verification": sum_check},
        "time_test": {"invoke": time_invoke, "verification": time_check},
        "overall_pass": overall,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote %s", RESULTS_PATH)

    print("\n=== Tool test summary ===")
    print(f"add_numbers (888+1234=2122): pass={sum_check['pass']} found={sum_check['numbers_found_in_response'][:6]}")
    print(f"get_current_time: pass={time_check['pass']} iso={time_check['iso_match']}")
    return 0 if overall else 7


if __name__ == "__main__":
    sys.exit(main())
