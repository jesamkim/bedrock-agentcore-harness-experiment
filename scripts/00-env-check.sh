#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 00-env-check.sh
# Purpose: Verify CLI + toolchain + AWS identity before running scenarios.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
LOG="$ARTIFACTS/00-env-check.log"
mkdir -p "$ARTIFACTS"

{
  echo "==== 00-env-check ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo

  echo "---- which agentcore ----"
  command -v agentcore || echo "agentcore NOT FOUND in PATH"
  echo

  echo "---- agentcore --help ----"
  set +e
  agentcore --help 2>&1 | head -120
  echo "(exit=$?)"
  set -e
  echo

  echo "---- agentcore --version (if supported) ----"
  set +e
  agentcore --version 2>&1 || true
  set -e
  echo

  echo "---- node / npm versions ----"
  set +e
  node --version 2>&1 || echo "node not installed"
  npm --version 2>&1 || echo "npm not installed"
  set -e
  echo

  echo "---- python / uv ----"
  set +e
  python3 --version 2>&1
  uv --version 2>&1 || echo "uv not installed"
  set -e
  echo

  echo "---- aws sts get-caller-identity (profile=$AWS_PROFILE region=$AWS_REGION) ----"
  set +e
  aws sts get-caller-identity --region "$AWS_REGION" 2>&1
  set -e
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
