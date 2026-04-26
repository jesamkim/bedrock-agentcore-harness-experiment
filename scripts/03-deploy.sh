#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 03-deploy.sh
# Purpose: Cloud deploy HelloAgent via `agentcore deploy --auto-update-on-conflict`,
#          measure wall time, extract agentRuntimeArn.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/03-deploy.log"
ARN_FILE="$ARTIFACTS/agent-arn.txt"
mkdir -p "$ARTIFACTS"

CWD="$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/HelloAgent" ]]; then
  CWD="$PROJECT_DIR/HelloAgent"
fi

{
  echo "==== 03-deploy ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "working dir: $CWD"
  echo

  cd "$CWD"

  START_EPOCH=$(date +%s)
  echo "deploy START epoch: $START_EPOCH"
  echo

  echo "---- agentcore deploy --auto-update-on-conflict ----"
  set +e
  agentcore deploy --auto-update-on-conflict 2>&1
  DEPLOY_RC=$?
  set -e
  END_EPOCH=$(date +%s)
  ELAPSED=$(( END_EPOCH - START_EPOCH ))
  echo
  echo "deploy END epoch: $END_EPOCH"
  echo "deploy elapsed: ${ELAPSED}s"
  echo "deploy exit=$DEPLOY_RC"
  echo

  echo "---- agentcore status --verbose ----"
  set +e
  agentcore status --verbose 2>&1
  set -e
  echo

  echo "---- extract agentRuntimeArn ----"
  # Grep ARN from deploy log (already teed above) or run status json again
  set +e
  ARN=$(agentcore status --verbose 2>&1 | grep -oE 'arn:aws:bedrock-agentcore[^" ]+' | head -1)
  if [[ -z "${ARN:-}" ]]; then
    ARN=$(grep -oE 'arn:aws:bedrock-agentcore[^" ]+' "$LOG" 2>/dev/null | head -1 || true)
  fi
  set -e
  if [[ -n "${ARN:-}" ]]; then
    echo "$ARN" > "$ARN_FILE"
    echo "ARN saved to: $ARN_FILE"
    echo "ARN: $ARN"
  else
    echo "!!!! could not extract ARN — inspect $LOG manually"
  fi
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
