#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE=default
export AWS_REGION=us-west-2

# 01-create-project.sh
# Purpose: Scaffold HelloAgent via `agentcore create` non-interactive; record generated tree.

ROOT="<REPO>"
ARTIFACTS="$ROOT/artifacts"
PROJECT_DIR="$ROOT/my-project"
LOG="$ARTIFACTS/01-project-tree.log"
mkdir -p "$ARTIFACTS" "$PROJECT_DIR"

{
  echo "==== 01-create-project ===="
  echo "START: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "project dir: $PROJECT_DIR"
  echo

  cd "$PROJECT_DIR"

  # Primary attempt: non-interactive
  echo "---- attempt 1: agentcore create --non-interactive ----"
  set +e
  agentcore create \
    --project-name HelloAgent \
    --template basic \
    --agent-framework Strands \
    --model-provider Bedrock \
    --non-interactive \
    --no-venv 2>&1
  RC=$?
  set -e
  echo "(exit=$RC)"
  echo

  if [[ $RC -ne 0 ]]; then
    echo "!!!! non-interactive failed, falling back to `yes` pipe"
    set +e
    yes "" | agentcore create \
      --project-name HelloAgent \
      --template basic \
      --agent-framework Strands \
      --model-provider Bedrock \
      --no-venv 2>&1
    RC2=$?
    set -e
    echo "(fallback exit=$RC2)"
    if [[ $RC2 -ne 0 ]]; then
      echo "!!!! FAILED to create project in both modes"
    fi
  fi
  echo

  echo "---- generated file tree (max 50) ----"
  set +e
  find "$PROJECT_DIR" -type f 2>/dev/null | head -50
  set -e
  echo

  echo "---- agentcore.json (if present) ----"
  CFG_CANDIDATES=(
    "$PROJECT_DIR/agentcore.json"
    "$PROJECT_DIR/HelloAgent/agentcore.json"
    "$PROJECT_DIR/.agentcore.json"
    "$PROJECT_DIR/.bedrock_agentcore.yaml"
  )
  for cfg in "${CFG_CANDIDATES[@]}"; do
    if [[ -f "$cfg" ]]; then
      echo "### $cfg"
      cat "$cfg"
      echo
    fi
  done
  # Fallback: any json/yaml under project
  echo "---- any config files found ----"
  find "$PROJECT_DIR" -maxdepth 3 -type f \( -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" \) 2>/dev/null | head -20
  echo

  echo "---- main.py / agent entrypoint ----"
  find "$PROJECT_DIR" -maxdepth 3 -type f -name "*.py" 2>/dev/null | head -10
  echo

  echo "END: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} 2>&1 | tee "$LOG"

echo "log saved: $LOG"
