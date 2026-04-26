#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 02-dev-local.sh
# Purpose: Run `agentcore dev` in background, probe with invoke --dev, then kill.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/02-dev-local.log"
DEV_LOG="$ARTIFACTS/02-dev-server.log"
mkdir -p "$ARTIFACTS"

# Pick the directory that actually contains the agent (agentcore scaffold may nest under HelloAgent)
CWD="$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/HelloAgent" ]]; then
  CWD="$PROJECT_DIR/HelloAgent"
fi

{
  echo "==== 02-dev-local ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "working dir: $CWD"
  echo

  cd "$CWD"

  echo "---- launching agentcore dev in background (port 8080) ----"
  set +e
  ( agentcore dev --port 8080 >"$DEV_LOG" 2>&1 ) &
  DEV_PID=$!
  set -e
  echo "dev PID=$DEV_PID"
  echo

  echo "---- waiting 5s for dev server to boot ----"
  sleep 5

  echo "---- probe via agentcore invoke --dev ----"
  set +e
  agentcore invoke --dev --port 8080 '{"prompt":"Say hello in one short sentence."}' 2>&1
  INVOKE_RC=$?
  set -e
  echo "(invoke exit=$INVOKE_RC)"
  echo

  if [[ $INVOKE_RC -ne 0 ]]; then
    echo "---- fallback: curl localhost:8080 ----"
    set +e
    curl -sS -X POST -H "Content-Type: application/json" \
      -d '{"prompt":"Say hello"}' \
      http://localhost:8080/invocations 2>&1
    echo
    curl -sS http://localhost:8080/ping 2>&1 || true
    set -e
    echo
  fi

  echo "---- dev server log (tail 60) ----"
  tail -60 "$DEV_LOG" 2>/dev/null || echo "(no dev log)"
  echo

  echo "---- shutting down dev server ----"
  set +e
  kill "$DEV_PID" 2>/dev/null
  sleep 1
  pkill -f "agentcore dev" 2>/dev/null
  pkill -f "uvicorn" 2>/dev/null
  set -e
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
