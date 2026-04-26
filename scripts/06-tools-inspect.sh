#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 06-tools-inspect.sh
# Purpose: Enumerate tool/gateway/memory/identity/eval subcommands and grep project
#          for "tools" bindings so we can compare against blog claims.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/06-tools-inspect.log"
mkdir -p "$ARTIFACTS"

{
  echo "==== 06-tools-inspect ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo

  for sub in gateway memory identity eval; do
    echo "============================================"
    echo "---- agentcore $sub --help ----"
    set +e
    agentcore "$sub" --help 2>&1
    set -e
    echo
  done

  # Drill into gateway / memory subcommands (one level deeper)
  for sub in "gateway create-mcp-gateway" "gateway list-mcp-gateways" \
             "memory create" "memory list" \
             "identity" "eval run"; do
    echo "============================================"
    echo "---- agentcore $sub --help ----"
    set +e
    agentcore $sub --help 2>&1 | head -60
    set -e
    echo
  done

  echo "============================================"
  echo "---- project: grep for 'tools' field in source & config ----"
  set +e
  echo "### python files"
  grep -RIn --include="*.py" -E 'tools\s*=|tools:\s*\[|from strands' "$PROJECT_DIR" 2>/dev/null | head -60
  echo
  echo "### config files"
  grep -RIn --include="*.json" --include="*.yaml" --include="*.yml" --include="*.toml" \
    -E '"tools"|tools:' "$PROJECT_DIR" 2>/dev/null | head -60
  echo
  echo "### main.py head"
  MAIN_CANDIDATES=(
    "$PROJECT_DIR/main.py"
    "$PROJECT_DIR/HelloAgent/main.py"
    "$PROJECT_DIR/HelloAgent/src/main.py"
    "$PROJECT_DIR/src/main.py"
  )
  for m in "${MAIN_CANDIDATES[@]}"; do
    if [[ -f "$m" ]]; then
      echo "### $m"
      head -80 "$m"
      echo
    fi
  done
  echo "### agent.py (if any)"
  find "$PROJECT_DIR" -maxdepth 4 -name "agent.py" -type f 2>/dev/null | while read -r f; do
    echo "### $f"
    head -80 "$f"
    echo
  done
  set -e
  echo

  echo "---- INTERPRETATION ----"
  echo "Blog claim: 'tools field connects built-in tools'."
  echo "Actual binding mechanism observed above (Strands @tool decorator?"
  echo "config-level tools array? Gateway/MCP-based?) should be summarized"
  echo "by the reader based on the grep output."
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
