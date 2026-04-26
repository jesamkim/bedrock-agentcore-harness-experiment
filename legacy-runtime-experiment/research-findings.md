# Research Findings — AgentCore "Managed Harness" Verification

Phase 1 of 3 (Research). Prepared for the Implementer subagent.

---

## 1. What "Managed Harness" Actually Is

**Verdict: BLOG INVENTION / marketing shorthand. Not an AWS product name.**

- Searched: AWS product pages, devguide, FAQs, AWS What's New, GA announcement blog, starter-toolkit README, SDK README, npm `@aws/agentcore`, What's New Oct 2025 post. The phrase "Managed Harness" does **not appear** in any AWS source.
- The AWS-official term for the managed agent-hosting service is **"Amazon Bedrock AgentCore Runtime"** (part of Amazon Bedrock AgentCore).
- What the blog calls a "Managed Harness" most closely maps to the combination of:
  1. `BedrockAgentCoreApp` (a Starlette-based HTTP wrapper) — source: `bedrock_agentcore/runtime/app.py`.
  2. The `agentcore` CLI (`bedrock-agentcore-starter-toolkit`) that configures, packages, and deploys the app.
  3. AgentCore Runtime (the managed AWS service that runs the deployed artifact in session-isolated microVMs).
- The 3-field pattern (`model`, `system_prompt`, `tools`) the blog calls a "Managed Harness API" is actually the **Strands Agents `Agent()` constructor** — not an AgentCore API. The developer writes this inside the entrypoint function; AgentCore just hosts the process.

Source (Strands `Agent(...)` used in the default template):
`/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore_starter_toolkit/create/features/strands/templates/runtime_only/common/main.py.j2`

---

## 2. Minimal Deploy Recipe

There is **no 3-field shortcut API** on AgentCore itself. Two supported deploy paths:

### Path A — Starter Toolkit (the "easy" path the blog probably means)

```bash
pip install bedrock-agentcore strands-agents bedrock-agentcore-starter-toolkit

# 1. Write entrypoint (see section 3)
# 2. Configure
agentcore configure -e my_agent.py --disable-memory
# 3. Deploy (default now uses CodeBuild + direct_code_deploy or container)
agentcore deploy
# 4. Invoke
agentcore invoke '{"prompt": "Hello"}'
# 5. Destroy
agentcore destroy
```

Source: https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html  
CLI source: `/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore_starter_toolkit/cli/runtime/commands.py`

### Path B — Raw boto3 (what the toolkit actually calls under the hood)

```python
import boto3
control = boto3.client('bedrock-agentcore-control')
response = control.create_agent_runtime(
    name='my-agent',
    agentRuntimeArtifact={'s3': {'uri': 's3://bucket/package.zip'}},
    roleArn='arn:aws:iam::ACCT:role/AgentCoreExecutionRole',
    pythonRuntime='PYTHON_3_13',
    entryPoint=['main.py']
)
```

`create_agent_runtime` requires a packaged artifact (S3 zip or ECR container). There is **no shortcut that takes `model`+`systemPrompt`+`tools` arguments**. The skill docs at `/home/ubuntu/.agents/skills/bedrock-agentcore/SKILL.md` confirm this.

---

## 3. Working Example (smallest deploy→invoke)

From the official quickstart (verified against installed SDK):

```python
# my_agent.py
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent

app = BedrockAgentCoreApp()
agent = Agent()  # Strands — THIS is where model/system_prompt/tools live

@app.entrypoint
def invoke(payload):
    result = agent(payload.get("prompt", "Hello!"))
    return {"result": result.message}

if __name__ == "__main__":
    app.run()
```

For the 3-field version the blog describes:

```python
agent = Agent(
    model="us.anthropic.claude-sonnet-4-5-v1:0",
    system_prompt="You are a helpful assistant.",
    tools=[my_tool, other_tool],
)
```

Programmatic invoke after deploy:
```python
import json, uuid, boto3
client = boto3.client('bedrock-agentcore')
r = client.invoke_agent_runtime(
    agentRuntimeArn="<ARN>",
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps({"prompt": "Hello"}).encode(),
    qualifier="DEFAULT",
)
print(json.loads(b''.join(r["response"]).decode()))
```

Citation: https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html

---

## 4. Session Isolation — What AWS Officially Says

**microVM is officially documented. Firecracker is NOT named publicly.**

Exact AWS wording (from devguide `runtime-sessions.html`):

> "Each user session in AgentCore Runtime receives its own dedicated microVM with isolated Compute, memory, and filesystem resources. This prevents one user's agent from accessing another user's data. After session completion, the entire microVM is terminated and memory is sanitized…"

> "AgentCore Runtime provisions a dedicated execution environment (microVM) for each session. Context is preserved between invocations to the same session."

> "Amazon Bedrock AgentCore uses the session header to route requests to the same microVM instance."

Source URL: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html

Verdict on blog: "microVM" claim = correct. "Firecracker" claim = plausible but not confirmed by AWS publicly; the blog should not assert it as fact.

---

## 5. Strands as Internal Engine?

**Verdict: FALSE. Strands is one of several supported frameworks, not the internal engine.**

- AWS FAQs list Strands alongside LangGraph, CrewAI, etc. as optional frameworks.
- The AgentCore SDK (`bedrock_agentcore.runtime.BedrockAgentCoreApp`) is a **Starlette HTTP server wrapper** — framework-agnostic. You can deploy any Python agent code (pure functions, LangGraph, CrewAI, Autogen, etc.) as long as it exposes an `/invocations` endpoint.
- Evidence: the `agentcore create` CLI has feature modules for `strands/`, `langchain_langgraph/`, `crewai/`, `openaiagents/`, `googleadk/`, `autogen/` — all first-class.
- Strands IS the default template when using `agentcore create`, which is probably why the blog author inferred it was "internal". It is not.

Source: `/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore_starter_toolkit/create/features/` (directory listing).

---

## 6. Preview vs GA, Regions

**GA — NOT preview.** Generally available since **October 13, 2025**.

Source: AWS blog "Amazon Bedrock AgentCore is now generally available" (October 13, 2025).

**Supported regions (9, per FAQ):**
- US East (N. Virginia) `us-east-1`
- US East (Ohio) `us-east-2`
- US West (Oregon) `us-west-2` ← our target
- Europe (Dublin) `eu-west-1`
- Europe (Frankfurt) `eu-central-1`
- Asia Pacific (Mumbai) `ap-south-1`
- Asia Pacific (Singapore) `ap-southeast-1`
- Asia Pacific (Sydney) `ap-southeast-2`
- Asia Pacific (Tokyo) `ap-northeast-1`

No enrollment needed. Standard IAM permissions suffice.

Confirmed on our account (`123456789012`, us-west-2): `aws bedrock-agentcore-control list-agent-runtimes` returned an existing runtime `deep_insight_runtime_vpc` with status `READY`.

---

## 7. VTEX / Rodrigo Moreira Quote

**Could not verify.** Google search for "VTEX" + "Rodrigo Moreira" + "AgentCore" returned no direct hits reachable by WebFetch. The AWS GA announcement and product page do not include this quote in the parts we fetched. It may exist in a press release or AWS case study not indexed in our fetched pages, but we cannot confirm.

Recommendation: the blog author should cite the primary source (AWS case study URL or press release URL) before publishing, or drop the quote.

---

## 8. Gotchas & Gaps (things the blog got wrong or glossed over)

1. **"Managed Harness" is not a real product name.** The blog invented a label. Use "AgentCore Runtime" + "BedrockAgentCoreApp" + "Strands `Agent()`" to describe the same thing accurately.
2. **"3-field deploy" conflates two layers.** Those 3 fields are the Strands `Agent()` constructor, not an AgentCore deploy API. AgentCore's `create_agent_runtime` needs an S3 zip or ECR image — never a 3-field call.
3. **"Preview" is wrong.** GA since Oct 2025.
4. **"Firecracker" is not public knowledge.** microVM is documented; the specific hypervisor is AWS-internal.
5. **Strands ≠ internal engine.** It's the default template only.
6. **Cold start matters.** Each new session = new microVM = cold start cost; session affinity via session header is required to avoid it.
7. **arm64 only.** All AgentCore deployments run on arm64; packaging dependencies must target aarch64-manylinux2014.
8. **IAM eventual consistency.** `create_agent_runtime` after a fresh role create needs retry (toolkit handles this via `retry_create_with_eventual_iam_consistency`).
9. **There are now TWO toolkits:** the Python `bedrock-agentcore-starter-toolkit` (what we have installed, described as "legacy" on GitHub) and a newer npm `@aws/agentcore` CLI. For this experiment, stick with the Python toolkit — it matches our installed version (1.2.0 / 0.2.6) and the blog's Python orientation.

---

## 9. Recommended Path for Phase 2 (Implementer)

Given findings, the Implementer should:

### Goal
Prove (or disprove) the blog's "3 declarations → deployable agent" claim by executing the **smallest possible deploy→invoke→destroy** cycle on our us-west-2 account.

### Concrete steps
1. **Write `main.py`** exactly matching the blog's 3-field pattern:
   ```python
   from bedrock_agentcore import BedrockAgentCoreApp
   from strands import Agent, tool

   app = BedrockAgentCoreApp()

   @tool
   def get_time() -> str:
       from datetime import datetime
       return datetime.utcnow().isoformat()

   agent = Agent(
       model="us.anthropic.claude-sonnet-4-5-v1:0",   # pick a model available in us-west-2
       system_prompt="You are a concise assistant.",
       tools=[get_time],
   )

   @app.entrypoint
   def invoke(payload):
       return {"result": str(agent(payload.get("prompt", "hi")))}

   if __name__ == "__main__":
       app.run()
   ```
2. **Write `requirements.txt`** with `bedrock-agentcore`, `strands-agents`.
3. **Verify local**: `python main.py &` + `curl localhost:8080/invocations`. (Tests the Starlette wrapper.)
4. **Deploy**:
   - `agentcore configure -e main.py -n harness_test --disable-memory --region us-west-2`
   - `agentcore deploy` — this is where the blog's claim is tested. If it "just works" with the 3-field pattern, blog's spirit is validated (even if terminology is wrong).
5. **Invoke**: `agentcore invoke '{"prompt": "What time is it?"}'` — verify tool call works, note latency, note session ID.
6. **Re-invoke with same session ID** to prove session affinity / microVM persistence.
7. **Destroy**: `agentcore destroy` — ensure clean teardown (also removes CodeBuild project, ECR images, optional execution role).

### Things to measure for the Validator (Phase 3)
- Total time from `configure` → `READY` status (blog claims < 5 min).
- Cold-start latency on first invoke.
- Warm invoke latency on same session.
- CloudWatch log group name and whether OTel traces appear (built-in observability claim).
- Number of files the developer had to write (the blog's "just 3 declarations" implicit claim).
- IAM role: did `agentcore deploy` auto-create one? (It should, via `get_or_create_runtime_execution_role`.)

### Key risks for Implementer
- **Model ID**: use us-west-2-available inference profile (`us.anthropic.claude-sonnet-4-5-v1:0` or `us.anthropic.claude-haiku-4-5-v1:0`). Don't use `global.` IDs that may not be supported.
- **IAM eventual consistency**: first deploy may retry silently; that's normal.
- **CodeBuild is now default** (not container). Deployment type `direct_code_deploy` zips the code; no Docker needed.
- **Profile**: use `AWS_PROFILE=<your-profile>` for all CLI/boto3 calls.

---

## Sources Cited

| # | Source | Used For |
|---|--------|----------|
| 1 | `/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore/runtime/app.py` | Verifying BedrockAgentCoreApp is Starlette wrapper |
| 2 | `/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore_starter_toolkit/cli/runtime/commands.py` | Verifying `configure`/`deploy`/`invoke`/`destroy` CLI |
| 3 | `/home/ubuntu/.local/lib/python3.10/site-packages/bedrock_agentcore_starter_toolkit/create/features/strands/templates/runtime_only/common/main.py.j2` | Confirming 3-field pattern is Strands, not AgentCore |
| 4 | `/home/ubuntu/.agents/skills/bedrock-agentcore/SKILL.md` | Verified `create_agent_runtime` API shape |
| 5 | https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/quickstart.html | Minimal deploy recipe |
| 6 | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html | microVM session isolation wording |
| 7 | https://aws.amazon.com/bedrock/agentcore/faqs/ | Regions, framework support |
| 8 | https://aws.amazon.com/blogs/aws/introducing-amazon-bedrock-agentcore-securely-deploy-and-operate-ai-agents-at-any-scale/ | GA Oct 13 2025, session isolation phrasing |
| 9 | Live AWS CLI test (us-west-2) | Confirmed API availability on our account |
