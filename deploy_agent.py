"""
Programmatic deploy of the harness-test agent to AgentCore Runtime.

Uses the bedrock-agentcore-starter-toolkit Python API (Runtime class)
which under the hood calls the `bedrock-agentcore-control` service.

Writes:
- /tmp/harness-deploy-response.json  (raw launch metadata)
- deploy-log.json                    (configure+launch timings, ARN, status poll)

Exits non-zero on any failure.
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

# Ensure profile + region are set BEFORE boto3 picks up creds.
os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from bedrock_agentcore_starter_toolkit import Runtime  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deploy_agent")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
RAW_DEPLOY_RESPONSE = Path("/tmp/harness-deploy-response.json")
READY_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 15


def _short_uid() -> str:
    return uuid.uuid4().hex[:8]


def _jsonable(obj: Any) -> Any:
    """Best-effort conversion of pydantic/BaseModel results to JSON-safe dicts."""
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:  # pragma: no cover
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:  # pragma: no cover
            pass
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return str(obj)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s", path)


def _poll_ready(
    control_client, agent_arn: str, agent_id: str, timeout: int
) -> Dict[str, Any]:
    """Poll describe_agent_runtime until READY, CREATE_FAILED, or timeout."""
    deadline = time.time() + timeout
    attempts = 0
    last_status = None
    while time.time() < deadline:
        attempts += 1
        try:
            resp = control_client.get_agent_runtime(agentRuntimeId=agent_id)
        except ClientError as exc:
            logger.warning("get_agent_runtime failed (attempt %d): %s", attempts, exc)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        status = resp.get("status")
        last_status = status
        logger.info("Poll attempt %d: status=%s", attempts, status)
        if status == "READY":
            return {"final_status": status, "attempts": attempts, "last_response": _jsonable(resp)}
        if status in {"CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"}:
            return {"final_status": status, "attempts": attempts, "last_response": _jsonable(resp)}
        time.sleep(POLL_INTERVAL_SECONDS)
    return {"final_status": f"TIMEOUT(last={last_status})", "attempts": attempts, "last_response": None}


def main() -> int:
    agent_name = f"harness_test_{_short_uid()}"
    logger.info("Deploying agent '%s' in region %s", agent_name, os.environ["AWS_REGION"])

    # Run from the project directory so the toolkit finds main.py + requirements.txt.
    os.chdir(HERE)

    runtime = Runtime()
    t0 = time.time()

    # 1. configure
    configure_started = datetime.now(timezone.utc)
    try:
        configure_result = runtime.configure(
            entrypoint="main.py",
            agent_name=agent_name,
            requirements_file="requirements.txt",
            auto_create_execution_role=True,
            auto_create_ecr=True,
            region=os.environ["AWS_REGION"],
            memory_mode="NO_MEMORY",
            deployment_type="direct_code_deploy",
            runtime_type="PYTHON_3_10",
            non_interactive=True,
            disable_otel=False,
        )
    except Exception as exc:
        logger.exception("configure() failed")
        _write_json(DEPLOY_LOG, {"stage": "configure", "error": str(exc), "agent_name": agent_name})
        return 2

    configure_finished = datetime.now(timezone.utc)
    logger.info("configure completed in %.1fs", (configure_finished - configure_started).total_seconds())

    # 2. launch (deploy)
    launch_started = datetime.now(timezone.utc)
    try:
        launch_result = runtime.launch(auto_update_on_conflict=True)
    except Exception as exc:
        logger.exception("launch() failed")
        _write_json(
            DEPLOY_LOG,
            {
                "stage": "launch",
                "error": str(exc),
                "agent_name": agent_name,
                "configure_result": _jsonable(configure_result),
            },
        )
        return 3
    launch_finished = datetime.now(timezone.utc)
    logger.info("launch completed in %.1fs", (launch_finished - launch_started).total_seconds())

    agent_arn = getattr(launch_result, "agent_arn", None)
    agent_id = getattr(launch_result, "agent_id", None)
    if not agent_arn or not agent_id:
        logger.error("launch_result missing agent_arn/agent_id: %s", _jsonable(launch_result))
        _write_json(
            DEPLOY_LOG,
            {
                "stage": "launch",
                "error": "missing agent_arn or agent_id in launch_result",
                "launch_result": _jsonable(launch_result),
            },
        )
        return 4

    _write_json(RAW_DEPLOY_RESPONSE, _jsonable(launch_result))
    logger.info("AgentRuntimeArn: %s", agent_arn)

    # 3. poll for READY
    control = boto3.client("bedrock-agentcore-control", region_name=os.environ["AWS_REGION"])
    poll_started = datetime.now(timezone.utc)
    poll_result = _poll_ready(control, agent_arn, agent_id, READY_TIMEOUT_SECONDS)
    poll_finished = datetime.now(timezone.utc)

    total_seconds = time.time() - t0
    final_status = poll_result["final_status"]
    logger.info("Final status: %s  (total %.1fs)", final_status, total_seconds)

    log_payload = {
        "agent_name": agent_name,
        "agent_arn": agent_arn,
        "agent_id": agent_id,
        "region": os.environ["AWS_REGION"],
        "account_id": getattr(configure_result, "account_id", None),
        "execution_role": getattr(configure_result, "execution_role", None),
        "ecr_repository": getattr(configure_result, "ecr_repository", None),
        "s3_path": getattr(configure_result, "s3_path", None),
        "memory_id": getattr(configure_result, "memory_id", None),
        "deployment_mode": getattr(launch_result, "mode", None),
        "codebuild_id": getattr(launch_result, "codebuild_id", None),
        "ecr_uri": getattr(launch_result, "ecr_uri", None),
        "timings": {
            "configure_seconds": (configure_finished - configure_started).total_seconds(),
            "launch_seconds": (launch_finished - launch_started).total_seconds(),
            "poll_seconds": (poll_finished - poll_started).total_seconds(),
            "total_seconds": total_seconds,
        },
        "configure_result": _jsonable(configure_result),
        "launch_result": _jsonable(launch_result),
        "poll_result": poll_result,
        "final_status": final_status,
    }
    _write_json(DEPLOY_LOG, log_payload)

    if final_status != "READY":
        logger.error("Agent did not reach READY state: %s", final_status)
        return 5

    logger.info("READY. Arn=%s  total=%.1fs", agent_arn, total_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
