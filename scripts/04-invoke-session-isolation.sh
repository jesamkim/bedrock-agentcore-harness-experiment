#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 04-invoke-session-isolation.sh
# Purpose: Verify session isolation — two different session-ids must NOT share memory.
#          Session A plants codeword XRAY-1111. Session B asks for it; expected: unknown.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/04-session-isolation.log"
mkdir -p "$ARTIFACTS"

CWD="$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/HelloAgent" ]]; then
  CWD="$PROJECT_DIR/HelloAgent"
fi

# AgentCore session IDs must be >=33 chars per server-side validation.
SESSION_A="session-a-$(date +%s)-aaaaaaaaaaaaaaaaaa"
SESSION_B="session-b-$(date +%s)-bbbbbbbbbbbbbbbbbb"

{
  echo "==== 04-invoke-session-isolation ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "SESSION_A=$SESSION_A"
  echo "SESSION_B=$SESSION_B"
  echo "working dir: $CWD"
  echo

  cd "$CWD"

  echo "---- SESSION A: plant codeword ----"
  set +e
  agentcore invoke \
    --session-id "$SESSION_A" \
    '{"prompt":"Remember the codeword XRAY-1111. Say OK."}' 2>&1
  RC_A=$?
  set -e
  echo "(session A exit=$RC_A)"
  echo

  sleep 2

  echo "---- SESSION A: self-check (should still know codeword) ----"
  set +e
  agentcore invoke \
    --session-id "$SESSION_A" \
    '{"prompt":"What codeword did I just tell you? Repeat it exactly."}' 2>&1
  set -e
  echo

  echo "---- SESSION B: new session, ask for codeword (should NOT know) ----"
  set +e
  agentcore invoke \
    --session-id "$SESSION_B" \
    '{"prompt":"What is the codeword I told you earlier? If you do not know, say UNKNOWN."}' 2>&1
  RC_B=$?
  set -e
  echo "(session B exit=$RC_B)"
  echo

  echo "---- agentcore status ----"
  set +e
  agentcore status --verbose 2>&1
  set -e
  echo

  echo "---- VERDICT (manual grep) ----"
  echo "Expected:"
  echo "  SESSION_A response: contains 'XRAY-1111' or 'OK'"
  echo "  SESSION_B response: does NOT contain 'XRAY-1111' (ideally says UNKNOWN)"
  echo "Session IDs differ: $([[ "$SESSION_A" != "$SESSION_B" ]] && echo YES || echo NO)"
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
