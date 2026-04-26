#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 05-observability.sh
# Purpose: Inspect traces via `agentcore obs {list,show}` and CloudWatch metrics
#          for AWS/Bedrock-AgentCore namespace.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/05-observability.log"
mkdir -p "$ARTIFACTS"

CWD="$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/HelloAgent" ]]; then
  CWD="$PROJECT_DIR/HelloAgent"
fi

{
  echo "==== 05-observability ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "working dir: $CWD"
  echo

  cd "$CWD"

  echo "---- agentcore obs --help ----"
  set +e
  agentcore obs --help 2>&1
  set -e
  echo

  echo "---- agentcore obs list --help ----"
  set +e
  agentcore obs list --help 2>&1
  set -e
  echo

  echo "---- agentcore obs list ----"
  set +e
  agentcore obs list 2>&1 | tee "$ARTIFACTS/05-obs-list.raw"
  set -e
  echo

  echo "---- agentcore obs show --help ----"
  set +e
  agentcore obs show --help 2>&1
  set -e
  echo

  echo "---- attempt to show first trace (if any) ----"
  # Try to grab first trace id / index from list output
  set +e
  FIRST_ID=$(grep -oE '[a-f0-9]{16,}' "$ARTIFACTS/05-obs-list.raw" 2>/dev/null | head -1)
  if [[ -n "${FIRST_ID:-}" ]]; then
    echo "trying trace id: $FIRST_ID"
    agentcore obs show "$FIRST_ID" 2>&1 || agentcore obs show --trace-id "$FIRST_ID" 2>&1 || true
  else
    # fallback to numeric index (the CLI description mentions "numbered index")
    echo "trying numeric index 1"
    agentcore obs show 1 2>&1 || true
  fi
  set -e
  echo

  echo "---- CloudWatch metrics: AWS/Bedrock-AgentCore ----"
  set +e
  aws cloudwatch list-metrics \
    --namespace AWS/Bedrock-AgentCore \
    --region "$AWS_REGION" \
    --output json 2>&1 | head -200
  set -e
  echo

  echo "---- CloudWatch log groups (filter bedrock-agentcore) ----"
  set +e
  aws logs describe-log-groups \
    --region "$AWS_REGION" \
    --log-group-name-prefix "/aws/bedrock-agentcore" \
    --output json 2>&1 | head -100
  aws logs describe-log-groups \
    --region "$AWS_REGION" \
    --log-group-name-prefix "bedrock-agentcore" \
    --output json 2>&1 | head -100
  set -e
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
