"""
Tear down every AWS resource created by the deploy pipeline.

Order:
1. Runtime.destroy() via starter toolkit (deletes agent runtime, endpoint, memory).
2. Delete CodeBuild project if auto-created.
3. Delete ECR repository if auto-created.
4. Delete S3 code-deploy bucket if auto-created.
5. Detach + delete IAM execution role if auto-created.

Results written to cleanup-log.json. Idempotent-ish: missing resources are
logged as "already gone" rather than hard failing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("AWS_PROFILE", "default")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from bedrock_agentcore_starter_toolkit import Runtime  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup")

HERE = Path(__file__).parent.resolve()
DEPLOY_LOG = HERE / "deploy-log.json"
CLEANUP_LOG = HERE / "cleanup-log.json"


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return str(obj)


def _load_deploy() -> Dict[str, Any]:
    if not DEPLOY_LOG.exists():
        raise FileNotFoundError(f"{DEPLOY_LOG} not found — nothing to clean up")
    return json.loads(DEPLOY_LOG.read_text())


def _delete_codebuild(project_name: str) -> Dict[str, Any]:
    client = boto3.client("codebuild", region_name=os.environ["AWS_REGION"])
    try:
        client.delete_project(name=project_name)
        return {"project": project_name, "deleted": True}
    except ClientError as exc:
        return {"project": project_name, "deleted": False, "error": str(exc)}


def _delete_ecr(repo_uri: str) -> Dict[str, Any]:
    # repo_uri looks like 123456789012.dkr.ecr.us-west-2.amazonaws.com/bedrock-agentcore-<name>
    if not repo_uri or "/" not in repo_uri:
        return {"skipped": True, "reason": "no ecr_repository configured"}
    repo_name = repo_uri.split("/", 1)[1]
    client = boto3.client("ecr", region_name=os.environ["AWS_REGION"])
    try:
        client.delete_repository(repositoryName=repo_name, force=True)
        return {"repo": repo_name, "deleted": True}
    except ClientError as exc:
        return {"repo": repo_name, "deleted": False, "error": str(exc)}


def _delete_s3_bucket(s3_path: str) -> Dict[str, Any]:
    # s3_path looks like s3://bucket-name/prefix/
    if not s3_path or not s3_path.startswith("s3://"):
        return {"skipped": True, "reason": "no s3_path configured"}
    without_scheme = s3_path[len("s3://") :]
    bucket = without_scheme.split("/", 1)[0]
    s3 = boto3.resource("s3", region_name=os.environ["AWS_REGION"])
    try:
        b = s3.Bucket(bucket)
        # Delete all objects + object versions.
        b.object_versions.delete()
        b.objects.delete()
        b.delete()
        return {"bucket": bucket, "deleted": True}
    except ClientError as exc:
        return {"bucket": bucket, "deleted": False, "error": str(exc)}


def _delete_iam_role(role_arn: str) -> Dict[str, Any]:
    if not role_arn:
        return {"skipped": True, "reason": "no execution_role configured"}
    role_name = role_arn.split("/")[-1]
    iam = boto3.client("iam", region_name=os.environ["AWS_REGION"])
    out: Dict[str, Any] = {"role_name": role_name, "actions": []}
    # Detach managed policies
    try:
        attached = iam.list_attached_role_policies(RoleName=role_name)
        for p in attached.get("AttachedPolicies", []):
            iam.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
            out["actions"].append(f"detached {p['PolicyArn']}")
    except ClientError as exc:
        out["actions"].append(f"list_attached_role_policies error: {exc}")
    # Delete inline policies
    try:
        inline = iam.list_role_policies(RoleName=role_name)
        for p_name in inline.get("PolicyNames", []):
            iam.delete_role_policy(RoleName=role_name, PolicyName=p_name)
            out["actions"].append(f"deleted inline {p_name}")
    except ClientError as exc:
        out["actions"].append(f"list_role_policies error: {exc}")
    # Delete instance profiles (if any)
    try:
        iam.delete_role(RoleName=role_name)
        out["deleted"] = True
    except ClientError as exc:
        out["deleted"] = False
        out["delete_error"] = str(exc)
    return out


def _verify_runtime_gone(agent_id: str) -> Dict[str, Any]:
    control = boto3.client("bedrock-agentcore-control", region_name=os.environ["AWS_REGION"])
    try:
        control.get_agent_runtime(agentRuntimeId=agent_id)
        return {"still_exists": True}
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ResourceNotFoundException":
            return {"still_exists": False}
        return {"still_exists": "unknown", "error": str(exc)}


def main() -> int:
    deploy = _load_deploy()
    agent_id = deploy.get("agent_id")
    agent_arn = deploy.get("agent_arn")
    agent_name = deploy.get("agent_name")
    logger.info("Destroying agent_name=%s arn=%s", agent_name, agent_arn)

    os.chdir(HERE)
    runtime = Runtime()
    started = datetime.now(timezone.utc)

    destroy_output: Any
    try:
        destroy_output = runtime.destroy(dry_run=False, delete_ecr_repo=True)
    except Exception as exc:
        logger.exception("runtime.destroy() failed — falling back to raw boto3 delete")
        destroy_output = {"error": str(exc)}

    # Fallback: raw boto3 delete_agent_runtime in case toolkit destroy didn't find anything.
    raw_delete: Dict[str, Any] = {}
    if agent_id:
        control = boto3.client("bedrock-agentcore-control", region_name=os.environ["AWS_REGION"])
        try:
            control.delete_agent_runtime(agentRuntimeId=agent_id)
            raw_delete = {"attempted": True, "ok": True}
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            raw_delete = {"attempted": True, "ok": False, "error_code": code, "error": str(exc)}

    # Give the control plane a moment.
    time.sleep(5)
    verify = _verify_runtime_gone(agent_id) if agent_id else {"skipped": "no agent_id"}

    # Attempt best-effort cleanup of toolkit-created side resources.
    codebuild_result: Dict[str, Any] = {"skipped": True, "reason": "no codebuild project recorded"}
    # Toolkit usually names the project "bedrock-agentcore-<agent_name>"
    if agent_name:
        codebuild_result = _delete_codebuild(f"bedrock-agentcore-{agent_name}")

    ecr_result = _delete_ecr(deploy.get("ecr_repository") or "")
    s3_result = _delete_s3_bucket(deploy.get("s3_path") or "")
    iam_result = _delete_iam_role(deploy.get("execution_role") or "")

    finished = datetime.now(timezone.utc)
    summary = {
        "agent_name": agent_name,
        "agent_arn": agent_arn,
        "agent_id": agent_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "runtime_destroy_output": _jsonable(destroy_output),
        "raw_delete_agent_runtime": raw_delete,
        "post_delete_verify": verify,
        "codebuild_cleanup": codebuild_result,
        "ecr_cleanup": ecr_result,
        "s3_cleanup": s3_result,
        "iam_cleanup": iam_result,
    }
    CLEANUP_LOG.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Wrote %s", CLEANUP_LOG)

    print("\n=== Cleanup summary ===")
    print(f"Agent runtime still exists: {verify.get('still_exists')}")
    print(f"ECR:       {ecr_result}")
    print(f"S3:        {s3_result}")
    print(f"CodeBuild: {codebuild_result}")
    print(f"IAM role:  deleted={iam_result.get('deleted')}")
    return 0 if verify.get("still_exists") is False else 10


if __name__ == "__main__":
    sys.exit(main())
