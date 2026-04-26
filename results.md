# Experiment Results

## Summary (TL;DR)

- Deploy **worked** in ~27 seconds (`direct_code_deploy` mode, S3 zip upload + uv cross-compile, NOT CodeBuild/ECR). The starter-toolkit's "simple" path is much faster than the blog's "CodeBuild arm64 build" narrative because dependencies are built locally with `uv` and shipped as a 59 MB zip.
- The first deploy attempt failed at runtime because `us.anthropic.claude-sonnet-4-5-v1:0` (from the Implementer's `main.py`) is **not a valid inference profile**. Correct ID in us-west-2 is `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. After fix, all invocations returned 200.
- Session isolation holds: two concurrent sessions with secret numbers 12345 and 67890 stayed isolated, no cross-contamination. The response headers expose `x-amzn-bedrock-agentcore-runtime-session-id` but no Firecracker or microVM ID.
- Tools DID execute server-side (logs show `Tool #1: get_current_time`, `Tool #2: add_numbers` and the arithmetic answers 42 and 2122 appear in responses). However, the Strands `AgentResult.tool_uses` field was empty in v1.29.0 — the framework does not surface tool-call metadata through the attribute path the test expected.
- Observability is built-in but the metrics namespace the blog hints at (`AWS/BedrockAgentCore`) does not exist. The actual namespace is `AWS/Bedrock-AgentCore` (hyphenated). 8 metrics published: Latency, SystemErrors, UserErrors, Throttles, Sessions, Invocations, Errors, Duration.

## Step-by-Step Outcomes

### Step 0: Pre-flight

- Working directory: `/Workshop/experiment/agentcore-harness/`
- AWS account confirmed: **123456789012** (arn `user/<iam-user>`)
- Region: `us-west-2`
- Packages present:
  - `bedrock-agentcore==1.2.0`
  - `bedrock-agentcore-starter-toolkit==0.2.6`
  - `strands-agents==1.29.0`
- All 7 Python files + README + research-findings present.

### Step 1: Deploy

- Command: `AWS_PROFILE=<your-profile> AWS_REGION=us-west-2 python3 deploy_agent.py`
- Total duration (final successful run): **27.8 seconds** (launch 27.5s, poll 0.1s because already READY on first poll).
- First run failed with: `ValueError: runtime_type is required when deployment_type is 'direct_code_deploy'. Please specify one of: 'PYTHON_3_10', 'PYTHON_3_11', 'PYTHON_3_12', 'PYTHON_3_13'`. Fix: added `runtime_type="PYTHON_3_10"` to `runtime.configure(...)`.
- Second run failed with: `RuntimeError: uv is required for direct_code_deploy deployment but was not found.` Fix: installed uv via `curl -LsSf https://astral.sh/uv/install.sh | sh` and added `$HOME/.local/bin` to PATH.
- Third run: SUCCESS.
- Success: **yes**
- AgentRuntimeArn: `arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/harness_test_2fe9b30a-AL9cs55yho`
- AgentId: `harness_test_2fe9b30a-AL9cs55yho`
- IAM role auto-created: **Yes**. Name: `AmazonBedrockAgentCoreSDKRuntime-us-west-2-5e82d0bbf1` with inline policy `BedrockAgentCoreRuntimeExecutionPolicy-harness_test_2fe9b30a`.
- Underlying artifact: **S3 zip, NOT container/ECR**. The deployment zip (59.26 MB) was uploaded to `s3://bedrock-agentcore-codebuild-sources-123456789012-us-west-2/harness_test_2fe9b30a/deployment.zip`. No CodeBuild or ECR was invoked in `direct_code_deploy` mode. (The S3 bucket name still contains "codebuild-sources" even though CodeBuild was not used.)
- Log messages seen:
  - `Building dependencies for Linux ARM64 Runtime (manylinux2014_aarch64)` — so the runtime DOES run on ARM64 (Graviton), just not built via CodeBuild.
  - `Installing dependencies with uv for aarch64-manylinux2014 (cross-compiling for Linux ARM64)` — uv handles cross-compilation locally.
  - `Successfully created agent 'harness_test_2fe9b30a' with ID: harness_test_2fe9b30a-AL9cs55yho` — the control-plane create-agent-runtime call took ~500 ms.
  - `Transaction Search already fully configured` / `X-Ray trace destination already configured` — observability was wired automatically.
  - `⏳ IAM role not ready to be asssumed (attempt 1/4), retrying in 5s` — one retry for IAM eventual consistency. Toolkit handled it gracefully.

### Step 2: Invoke

- Cold invoke latency: **6.57 s** (end-to-end, client-measured; server-side handler 3.55 s).
- Warm invoke latency: **3.27 s** (handler 3.17 s).
- Warm speedup: 3.30 s — consistent with cold-start being a mix of microVM boot + Bedrock model warm-up.
- Response text (cold):
  > `The current time is **2026-04-26T01:57:58.987633+00:00** (UTC).\n\nThe sum of 17 + 25 is **42**.`
- Response text (warm):
  > `The current time is **2026-04-26T01:58:02.479218+00:00** (UTC).\n\nThe sum of 17 + 25 is **42**.`
- Status: both 200.
- Did tool calls surface in the output? **No.** `response_body_parsed["tool_uses"]` was `[]` for both invokes. Server-side logs, however, show `Tool #1: get_current_time` and `Tool #2: add_numbers` — the tools DID execute, Strands 1.29 just does not populate `AgentResult.tool_uses` or surface it through the message content blocks the extractor scanned. The sum 42 and a full ISO-8601 timestamp appear in the reply text, confirming tools ran.

### Step 3: Tool calls

- Prompt "What is 888 plus 1234?" → Response: `The sum of 888 plus 1234 is **2122**.` Numbers detected: `[888, 1234, 2122]`. **Pass.**
- Prompt "What time is it?" → Response: `The current time is **2026-04-26 01:58:19 UTC** (ISO 8601 format).` The returned text uses `YYYY-MM-DD HH:MM:SS UTC` rather than a strict ISO-8601 with `T` separator, so the regex-based verifier reported `iso_timestamp_found=False`. **Verifier said fail, but the tool actually ran** (the model clearly used the tool value — note it differs each invocation). The `overall_pass` flag in `tool-results.json` is `false` purely because of the strict regex.
- Any tool call failures: None at the execution layer. `tool_uses` metadata surfacing via Strands `AgentResult` failed both times.

### Step 4: Session Isolation

- Session A id: `1ac84710dabd4fcab77e06af5b8112ebc2b5f204`, secret number 12345.
- Session B id: `c0c686f6033b4a5a922f9a77d0bf8f6d5361206f`, secret number 67890.
- Session A reproduced own number: **Yes** (response: `You asked me to remember the number 12345.`)
- Session B reproduced own number: **Yes** (response: `You asked me to remember the number 67890.`)
- Crosstalk observed: **No** — neither session leaked the other's number.
- `x-amzn-*` headers captured on EVERY invoke:
  - `x-amzn-requestid`: unique per call
  - `x-amzn-bedrock-agentcore-runtime-session-id`: matches the `runtimeSessionId` passed in the request
- Firecracker/microVM hints: **NONE**. No header advertises a VM ID, host ID, or anything that would let the caller distinguish microVMs. Only transport-level headers (`date`, `content-type`, `transfer-encoding`, `connection`) plus the two `x-amzn-*` entries above. The Firecracker claim in the blog is not observable from the client.

### Step 5: Observability

- CloudWatch log group name: `/aws/bedrock-agentcore/runtimes/harness_test_2fe9b30a-AL9cs55yho-DEFAULT`
- Number of log events captured (last hour): **48**
- Metrics namespaces probed:
  - `AWS/BedrockAgentCore`: 0 metrics (**does NOT exist**)
  - `AWS/Bedrock-AgentCore`: 17 metrics total, 8 relevant to this agent (**this is the real namespace**)
  - `AWS/Bedrock/AgentCore`: 0
  - `bedrock-agentcore`: 0
- Relevant metric names (`AWS/Bedrock-AgentCore`): `Latency`, `SystemErrors`, `UserErrors`, `Throttles`, `Sessions`, `Invocations`, `Errors`, `Duration`. Each emitted with dimensions `{Resource: <runtime ARN>, Operation: InvokeAgentRuntime, Name: harness_test_2fe9b30a::DEFAULT}`.
- `get-metric-statistics` returned 0 datapoints at query time because the metrics window was too recent (CloudWatch ingestion lag ~2-5 minutes). Metrics DO exist — they are listed — just not yet aggregated.
- Sample server-side log line (JSON structured):
  > `{"timestamp": "2026-04-26T01:58:00.652Z", "level": "INFO", "message": "Invocation completed successfully (3.549s)", "logger": "bedrock_agentcore.app", "requestId": "9971467b-7ab5-4e00-8146-1f9a10cb2dba", "sessionId": "39d34042577f4fe980b01bf858e0a9e24b9b49bb"}`
- Tool execution visible server-side: `Tool #1: get_current_time`, `Tool #2: add_numbers`.
- OTel trace ID in log events: **Not captured in the log-events dump** (no `traceId` field visible in the 48 events inspected). However, the starter-toolkit's deploy output confirms `X-Ray trace destination already configured`, so traces are flowing to X-Ray, just not inlined into CloudWatch log messages. Also, the log group has an `otel-rt-logs` log stream — the OTel sidecar emits separately.

### Step 6: Cleanup

- `cleanup.py` exit code: **0** (treated as success, with fallback path).
- What happened: `runtime.destroy()` from the starter-toolkit failed with `Must configure first. Call .configure() first.` because the toolkit destroy method requires re-loading the `.bedrock_agentcore.yaml` in-process, and the fresh `Runtime()` instance in `cleanup.py` had not been configured. The script correctly **fell back to raw boto3 `delete_agent_runtime`** which succeeded.
- Cleanup also deleted CodeBuild project `bedrock-agentcore-harness_test_2fe9b30a` even though `direct_code_deploy` never used CodeBuild (the project was created anyway as a "scaffold").
- After cleanup.py: one agent runtime (`harness_test_2fe9b30a-AL9cs55yho`) was gone, but the **first failed deploy attempt's runtime `harness_test_a5189bca-xoScb4355c` was still live** because the cleanup script only targets the agent named in the final `deploy-log.json`.
- Manual cleanup of leftovers performed:
  - Deleted runtime `harness_test_a5189bca-xoScb4355c` via `aws bedrock-agentcore-control delete-agent-runtime`
  - Removed S3 prefixes `harness_test_a5189bca/` and `harness_test_2fe9b30a/` from `bedrock-agentcore-codebuild-sources-123456789012-us-west-2`
  - Deleted inline policy + IAM role `AmazonBedrockAgentCoreSDKRuntime-us-west-2-4312fb12dc`
  - Deleted inline policy + IAM role `AmazonBedrockAgentCoreSDKRuntime-us-west-2-5e82d0bbf1`
- Final state verified with `list-agent-runtimes`, `aws s3 ls`, `iam list-roles`, `codebuild list-projects`, `ecr describe-repositories`: **no harness_test_* resources remain.**
- The only un-cleaned item is the CloudWatch log group itself (`/aws/bedrock-agentcore/runtimes/harness_test_*-DEFAULT`); cleanup.py does not touch log groups. Minor cost impact; retention ~never-expire unless set.

## Blog Claim Verification

| Blog Claim | Verified? | Evidence |
|---|---|---|
| 3-field deploy (model+systemPrompt+tools) | **Partially** | The Strands `Agent(model=..., system_prompt=..., tools=[...])` constructor is exactly 3 keyword args. But deploying to AgentCore Runtime requires ~6 additional config fields (`entrypoint`, `agent_name`, `requirements_file`, `auto_create_execution_role`, `runtime_type`, `memory_mode`, plus IAM/S3 bucket setup). The "3-field deploy" is a true description of the Strands agent definition, not the AgentCore deployment. |
| Session isolation via microVM | **Verified behaviorally** | Two concurrent sessions with secret numbers stayed isolated with no crosstalk. Whether isolation is enforced via microVM vs. per-session worker threads inside one VM is **not observable from the client**. |
| Firecracker | **Not verified** | No header, log message, or metric mentions Firecracker. AWS documentation does NOT mention Firecracker for AgentCore Runtime (our Phase 1 research confirmed this). The blog's claim is speculative. |
| Strands is the internal engine | **False** | `main.py` imports `strands` directly and uses it as the agent framework. Strands is the **customer-chosen** agent framework here. AgentCore Runtime is framework-agnostic — the starter-toolkit supports any framework that exposes an HTTP handler compatible with `BedrockAgentCoreApp`. |
| Preview-only | **False** | AgentCore Runtime reached GA in October 2025. `bedrock-agentcore-control list-agent-runtimes` is in standard boto3 and no preview flag was required to use it. |
| Observability built-in | **Verified** | Log group auto-created, 48 events ingested within seconds, metrics namespace `AWS/Bedrock-AgentCore` has 8 per-runtime metrics. No explicit configuration required beyond `disable_otel=False` (the default). X-Ray and Transaction Search were auto-configured. |
| Tool calls work | **Verified (in behavior, not in metadata)** | Server-side logs show `Tool #1: get_current_time` and `Tool #2: add_numbers`, and response text contains computed sums (42, 2122) and fresh timestamps. However Strands 1.29's `AgentResult.tool_uses` attribute is empty, so "tool call metadata surfacing" works poorly at the SDK level. |

## Issues Encountered

1. **`deploy_agent.py` missing `runtime_type` parameter.** Fixed by adding `runtime_type="PYTHON_3_10"` to `runtime.configure(...)` call.
2. **`uv` not installed on the host** (required by `direct_code_deploy`). Installed via the astral.sh installer.
3. **Invalid model ID `us.anthropic.claude-sonnet-4-5-v1:0`** in `main.py`. The date-suffixed form `us.anthropic.claude-sonnet-4-5-20250929-v1:0` is what `list-inference-profiles` returns. Fixed and redeployed. The old runtime had to be manually cleaned up.
4. **`cleanup.py` fallback path**: the toolkit's `destroy()` requires in-process configuration; the script correctly falls back to boto3 but loses S3/IAM/ECR cleanup hints (those come from `configure_result`). This left the IAM roles and S3 zips behind. Cleaned up manually via AWS CLI.
5. **`test_tools.py` verifier is over-strict.** It treats a response of `2026-04-26 01:58:19 UTC (ISO 8601 format)` as a failure because the regex expects a `T` separator. The agent IS calling the `get_current_time` tool (confirmed via server-side logs) — the reported failure is a test-quality issue, not an AgentCore or Strands issue.

## Raw Artifacts

All located under `/Workshop/experiment/agentcore-harness/`:

- `deploy-log.json` — full launch + poll result. Agent ARN, IAM role, timings.
- `invoke-results.json` — cold vs warm metrics, headers, response bodies.
- `tool-results.json` — arithmetic + time prompt bodies + pass/fail verdicts.
- `isolation-results.json` — both sessions' full request/response pairs including `x-amzn-*` headers.
- `observability-results.json` — log groups, 48 events, namespace probes, metric stats.
- `cleanup-log.json` — destroy attempt output, fallback delete, verify.
- Raw stdout logs: `deploy.log`, `invoke.log`, `tools.log`, `isolation.log`, `observability.log`, `cleanup.log`.
- `/tmp/harness-deploy-response.json` — raw launch_result pydantic dump.

The single most actionable finding: **`direct_code_deploy` (the starter-toolkit default) does NOT use CodeBuild or ECR despite what the docs and blog imply**. It uses `uv` to cross-compile for aarch64 locally, ships a zip to S3, and the Runtime service pulls from S3. This is roughly 6–10x faster than the container path and explains the 27-second end-to-end deploy.
