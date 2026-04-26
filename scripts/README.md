# AgentCore CLI Test Scenario Scripts

Bash scripts that exercise `@aws/agentcore` CLI v0.11.0 end-to-end.
Do NOT run these from inside another agent session — the Validator runs them.

## Prerequisites

- CLI installed at `/home/user/.local/bin/agentcore`
- `AWS_PROFILE=default`, `AWS_REGION=us-west-2` (account `123456789012`)
- `uv` at `/home/user/.local/bin/uv`
- Every script self-exports `PATH`, `AWS_PROFILE`, `AWS_REGION`

Logs go to `../artifacts/` (each script writes its own `NN-*.log` via `tee`).

## Execution Order

Run sequentially from `<REPO>/`:

```bash
bash scripts/00-env-check.sh
bash scripts/01-create-project.sh
bash scripts/02-dev-local.sh
bash scripts/03-deploy.sh              # ~several minutes, cloud build
bash scripts/04-invoke-session-isolation.sh
bash scripts/05-observability.sh
bash scripts/06-tools-inspect.sh
bash scripts/99-cleanup.sh             # tears down cloud resources
```

## Script Summary

| # | Script | Purpose |
|---|--------|---------|
| 00 | `00-env-check.sh` | Verify `agentcore`, node/npm, uv, `aws sts get-caller-identity`. |
| 01 | `01-create-project.sh` | Scaffold `HelloAgent` (Strands + Bedrock, basic template, non-interactive, no-venv) and dump the resulting tree + config. |
| 02 | `02-dev-local.sh` | Start `agentcore dev` in background on :8080, probe with `agentcore invoke --dev` (curl fallback), then kill. |
| 03 | `03-deploy.sh` | Cloud deploy with `--auto-update-on-conflict`, measure wall time, extract `agentRuntimeArn` to `../artifacts/agent-arn.txt`. |
| 04 | `04-invoke-session-isolation.sh` | Plant codeword `XRAY-1111` in Session A, ask in Session B — verify session isolation. Session IDs are padded to >=33 chars (AgentCore requirement). |
| 05 | `05-observability.sh` | `agentcore obs list` / `show`; `aws cloudwatch list-metrics --namespace AWS/Bedrock-AgentCore`; list log groups under `/aws/bedrock-agentcore`. |
| 06 | `06-tools-inspect.sh` | Dump `gateway` / `memory` / `identity` / `eval` subcommand help; grep the generated project for `tools=`/`"tools":` bindings to compare against blog claims. |
| 99 | `99-cleanup.sh` | `agentcore destroy --force`, then report remaining CloudFormation / ECR / S3 / CodeBuild / IAM footprints (report-only — does not delete extras). |

## Conventions

- Header: `#!/usr/bin/env bash`, `set -euo pipefail`, PATH + AWS_PROFILE + AWS_REGION export
- Timestamps: `date -u +"%Y-%m-%dT%H:%M:%SZ"` at START / END of each script
- `set +e` around each probed command so one failure does not hide subsequent logs
- Output teed to `../artifacts/NN-*.log` for post-run analysis
- Project directory auto-detected: `my-project/` OR `my-project/HelloAgent/`
- Secrets / ARNs are NOT redacted in logs (redact at README publish time)
