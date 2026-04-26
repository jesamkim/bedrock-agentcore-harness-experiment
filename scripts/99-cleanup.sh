#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 99-cleanup.sh
# Purpose: Tear down HelloAgent cloud resources (via destroy --force) and
#          audit remaining CloudFormation / ECR / S3 footprints (report-only).

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/99-cleanup.log"
mkdir -p "$ARTIFACTS"

CWD="$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/HelloAgent" ]]; then
  CWD="$PROJECT_DIR/HelloAgent"
fi

{
  echo "==== 99-cleanup ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "working dir: $CWD"
  echo

  cd "$CWD"

  echo "---- agentcore destroy --help ----"
  set +e
  agentcore destroy --help 2>&1
  set -e
  echo

  echo "---- agentcore destroy --dry-run (preview) ----"
  set +e
  agentcore destroy --dry-run 2>&1
  set -e
  echo

  echo "---- agentcore destroy --force (real) ----"
  set +e
  # --force skips interactive y/n. Also pipe `yes` as belt-and-suspenders.
  yes y | agentcore destroy --force 2>&1
  DESTROY_RC=$?
  set -e
  echo "(destroy exit=$DESTROY_RC)"
  echo

  echo "---- agentcore status --verbose (post-destroy) ----"
  set +e
  agentcore status --verbose 2>&1
  set -e
  echo

  echo "---- CloudFormation stacks still active ----"
  set +e
  aws cloudformation list-stacks \
    --region "$AWS_REGION" \
    --query "StackSummaries[?StackStatus!='DELETE_COMPLETE'].[StackName,StackStatus,CreationTime]" \
    --output table 2>&1 | head -80
  set -e
  echo

  echo "---- ECR repositories (report only, NOT deleted) ----"
  set +e
  aws ecr describe-repositories \
    --region "$AWS_REGION" \
    --query "repositories[?contains(repositoryName, 'agentcore') || contains(repositoryName, 'hello')].[repositoryName,createdAt]" \
    --output table 2>&1 | head -80
  set -e
  echo

  echo "---- S3 buckets (report only, NOT deleted) ----"
  set +e
  aws s3api list-buckets \
    --query "Buckets[?contains(Name, 'agentcore') || contains(Name, 'helloagent') || contains(Name, 'bedrock')].[Name,CreationDate]" \
    --output table 2>&1 | head -80
  set -e
  echo

  echo "---- CodeBuild projects (report only) ----"
  set +e
  aws codebuild list-projects --region "$AWS_REGION" --output json 2>&1 | head -60
  set -e
  echo

  echo "---- IAM roles with 'agentcore' in name (report only) ----"
  set +e
  aws iam list-roles \
    --query "Roles[?contains(RoleName, 'agentcore') || contains(RoleName, 'AgentCore') || contains(RoleName, 'HelloAgent')].[RoleName,CreateDate]" \
    --output table 2>&1 | head -80
  set -e
  echo

  echo "NOTE: this script only reports leftover resources; it does NOT delete"
  echo "      ECR repos / S3 buckets / IAM roles. Delete manually if needed."
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
