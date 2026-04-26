"""
Post-invoke observability check.

- Discovers CloudWatch log groups under /aws/bedrock-agentcore/runtimes/<RUNTIME-ID>-*
- Pulls recent log events (FilterLogEvents)
- Queries CloudWatch metrics in AWS/BedrockAgentCore (and a couple of
  nearby namespaces) for Invocations, Errors, Latency, SessionCount

Writes observability-results.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("check_observability")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
RESULTS_PATH = HERE / "observability-results.json"

CANDIDATE_NAMESPACES = [
    "AWS/BedrockAgentCore",
    "AWS/Bedrock-AgentCore",
    "AWS/Bedrock/AgentCore",
    "bedrock-agentcore",
]
METRIC_NAMES = ["Invocations", "Errors", "Latency", "InvocationLatency", "SessionCount"]


def _load_runtime_info() -> Dict[str, Any]:
    if not DEPLOY_LOG.exists():
        raise FileNotFoundError(f"{DEPLOY_LOG} not found; run deploy_agent.py first")
    data = json.loads(DEPLOY_LOG.read_text())
    return {
        "agent_arn": data.get("agent_arn"),
        "agent_id": data.get("agent_id"),
        "agent_name": data.get("agent_name"),
    }


def _find_log_groups(logs, agent_id: str) -> List[Dict[str, Any]]:
    """AgentCore log groups use pattern /aws/bedrock-agentcore/runtimes/<id>-..."""
    prefixes = [
        f"/aws/bedrock-agentcore/runtimes/{agent_id}",
        "/aws/bedrock-agentcore/runtimes/",
    ]
    seen: Dict[str, Dict[str, Any]] = {}
    for prefix in prefixes:
        try:
            paginator = logs.get_paginator("describe_log_groups")
            for page in paginator.paginate(logGroupNamePrefix=prefix, PaginationConfig={"MaxItems": 50}):
                for group in page.get("logGroups", []):
                    name = group["logGroupName"]
                    if agent_id in name:
                        seen[name] = group
        except ClientError as exc:
            logger.warning("describe_log_groups(%s) failed: %s", prefix, exc)
    return list(seen.values())


def _filter_events(logs, group_name: str, start_time_ms: int, limit: int = 50) -> Dict[str, Any]:
    try:
        resp = logs.filter_log_events(
            logGroupName=group_name,
            startTime=start_time_ms,
            limit=limit,
        )
        events = [
            {
                "timestamp": e.get("timestamp"),
                "logStreamName": e.get("logStreamName"),
                "message": e.get("message", "")[:500],
            }
            for e in resp.get("events", [])
        ]
        return {"count": len(events), "events": events}
    except ClientError as exc:
        return {"error": str(exc)}


def _list_metrics(cloudwatch, namespace: str, agent_id: str) -> Dict[str, Any]:
    try:
        resp = cloudwatch.list_metrics(Namespace=namespace)
        metrics = resp.get("Metrics", [])
        relevant = [
            m
            for m in metrics
            if any(
                agent_id in str(dim.get("Value", ""))
                for dim in m.get("Dimensions", [])
            )
        ]
        return {"total_in_namespace": len(metrics), "relevant_to_agent": relevant[:25]}
    except ClientError as exc:
        return {"error": str(exc)}


def _get_metric_stats(
    cloudwatch, namespace: str, metric_name: str, agent_id: str, start: datetime, end: datetime
) -> Dict[str, Any]:
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[{"Name": "AgentRuntimeId", "Value": agent_id}],
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=["Sum", "Average", "Maximum"],
        )
        return {
            "label": resp.get("Label"),
            "datapoints": resp.get("Datapoints", []),
        }
    except ClientError as exc:
        return {"error": str(exc)}


def main() -> int:
    info = _load_runtime_info()
    agent_id = info["agent_id"]
    if not agent_id:
        logger.error("agent_id missing from deploy-log.json")
        return 9
    logger.info("Checking observability for agent_id=%s", agent_id)

    logs = boto3.client("logs", region_name=os.environ["AWS_REGION"])
    cloudwatch = boto3.client("cloudwatch", region_name=os.environ["AWS_REGION"])

    groups = _find_log_groups(logs, agent_id)
    logger.info("Found %d log group(s) for this agent", len(groups))
    start_ms = int((time.time() - 60 * 60) * 1000)  # last 60 min
    per_group_events = {}
    for g in groups:
        per_group_events[g["logGroupName"]] = _filter_events(logs, g["logGroupName"], start_ms, limit=50)

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=1)

    namespace_probes: Dict[str, Any] = {}
    metric_stats: Dict[str, Any] = {}
    for ns in CANDIDATE_NAMESPACES:
        namespace_probes[ns] = _list_metrics(cloudwatch, ns, agent_id)
        for name in METRIC_NAMES:
            metric_stats.setdefault(ns, {})[name] = _get_metric_stats(
                cloudwatch, ns, name, agent_id, start_dt, end_dt
            )

    summary = {
        "agent_id": agent_id,
        "agent_arn": info["agent_arn"],
        "agent_name": info["agent_name"],
        "region": os.environ["AWS_REGION"],
        "log_groups": [
            {"name": g["logGroupName"], "creation_time": g.get("creationTime"), "retention": g.get("retentionInDays")}
            for g in groups
        ],
        "log_events_by_group": per_group_events,
        "namespace_probes": namespace_probes,
        "metric_stats": metric_stats,
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote %s", RESULTS_PATH)

    print("\n=== Observability summary ===")
    print(f"Log groups found: {len(groups)}")
    for g in groups:
        evs = per_group_events.get(g["logGroupName"], {})
        print(f"  - {g['logGroupName']} events={evs.get('count', evs.get('error'))}")
    for ns, probe in namespace_probes.items():
        rel = probe.get("relevant_to_agent", [])
        total = probe.get("total_in_namespace", 0)
        print(f"Namespace {ns}: total={total} relevant-to-agent={len(rel) if isinstance(rel, list) else rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
