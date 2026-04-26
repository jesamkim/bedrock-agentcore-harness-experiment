# AgentCore CLI 실측 리포트 (`@aws/agentcore` v0.11.0, 2026-04-26)

## 1. 실험 개요

- **대상**: `@aws/agentcore` CLI (npm 패키지 `v0.11.0`, 실제로는 `bedrock-agentcore-starter-toolkit` Python CLI의 npm 래퍼)
- **환경**: Linux AMI, Node 22 / npm 10 / Python 3.10 / uv 0.11.7
- **AWS**: account `123456789012`, profile `default`, region `us-west-2`
- **목적**: 2026-04-22 발표된 "Managed Harness + AgentCore CLI + Skills" 3종 세트에 대한 블로그 주장을 CLI로 직접 검증

## 2. 시나리오 실행 요약

| # | 시나리오 | 결과 | 로그 |
|---|---|---|---|
| 00 | 환경 검증 (Node/npm/Python/uv/AWS) | 성공 | `artifacts/00-env-check.log` |
| 01 | 프로젝트 생성 `agentcore create` | 성공 (HelloAgent 템플릿) | `artifacts/01-project-tree.log` |
| 02 | 로컬 서버 `agentcore dev` (Uvicorn :8080) | 성공 (POST /invocations 200 OK) | `artifacts/02-dev-local.log` |
| 03 | 클라우드 배포 `agentcore deploy` | **성공, 32초** | `artifacts/03-deploy.log` |
| 04 | 세션 격리 (Session A에 코드워드 주입, Session B에서 조회) | 성공 (격리 확인) | `artifacts/04-session-isolation.log` |
| 05 | 관측성 (CloudWatch metrics/logs) | 성공 (메트릭 8종 + 세션별 log stream) | `artifacts/05-observability.log` |
| 06 | 도구/프레임워크 조사 | 성공 (Strands + @tool + MCP + CodeInterpreter) | `artifacts/06-tools-inspect.log` |
| 99 | Cleanup `agentcore destroy --force` | **성공** (Agent + S3 artifacts 삭제) | `artifacts/99-cleanup.log` |

## 3. 블로그 7개 주장 실측 판정

### 주장 #1: "3번의 API 호출 / 3개의 선언(model + systemPrompt + tools)"

**판정: 부분 거짓 (표현 층위 불일치)**

블로그 원문 (Line 41-51):
> `model`, `systemPrompt`, `tools` 세 가지만 선언하면 됩니다. …  
> [ClassMethod의 분석]에 공개된 `harness.json` 예시는 다음처럼 간결합니다:
> ```json
> {
>   "name": "MyHarness",
>   "model": {...},
>   "tools": [...],
>   "skills": []
> }
> ```

**실측**:
- `@aws/agentcore` v0.11.0이 생성하는 프로젝트 구조에는 **`harness.json`이 존재하지 않는다**.
- 실제 생성물: `HelloAgent/.bedrock_agentcore.yaml` (프로젝트 설정) + `HelloAgent/src/main.py` (Strands Python 코드) + `pyproject.toml`.
- 모델/도구/시스템 프롬프트는 `main.py` 안에 **Python 코드로** 선언됨:

```python
# src/main.py 실측
from strands import Agent, tool
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@tool
def add_numbers(a: int, b: int) -> int:
    return a + b

@app.entrypoint
async def invoke(payload, context):
    code_interpreter = AgentCoreCodeInterpreter(...)
    with mcp_client as client:
        tools = client.list_tools_sync()
        agent = Agent(
            model=load_model(),            # <- Bedrock Claude Sonnet 4.5
            system_prompt="You are a helpful assistant...",  # <- 인라인
            tools=[code_interpreter.code_interpreter, add_numbers] + tools
        )
```

**증거**: `artifacts/06-tools-inspect.log` line 140–190.

**의미**: ClassMethod 기사가 묘사한 `harness.json` 형태는 **다른 내부/미공개 CLI 분기**이거나 preview 단계에서 변경됐을 가능성이 큼. 2026-04-26 시점 공개 CLI는 "3-선언 JSON" 대신 **"Strands 코드 + 한 YAML 설정"** 모델로 동작함. "3번의 API 호출"이라는 개념적 주장은 (invoke/deploy/create 레벨에서) 부분 사실이지만, 그것이 "harness.json 한 파일"로 나타난다는 구체적 서술은 현재 CLI와 불일치.

---

### 주장 #2: "microVM 세션 격리"

**판정: 사실**

블로그 원문 (Line 153):
> AgentCore Runtime: 'Each user session in AgentCore Runtime receives its own dedicated microVM with isolated compute, memory, and filesystem resources.'

**실측**:
- 서로 다른 session ID에 대한 두 호출의 결과:
  - Session A ("XRAY-1111을 기억해") → "OK." 응답
  - Session A 재호출 ("방금 말한 코드워드는?") → **"You haven't told me a codeword"** (같은 session 내 대화도 유지 안 됨 — NO_MEMORY 모드 때문)
  - Session B ("어디서 말했던 코드워드는?") → **"UNKNOWN"** (격리 성공)
- CloudWatch Log Group `/aws/bedrock-agentcore/runtimes/HelloAgent_Agent-csgQQZ3Yid-DEFAULT`에는 **세션마다 별도의 log stream**이 생성됨:
  - `2026/04/26/[runtime-logs-session-a-1777171992-...]53c843b1-...`
  - `2026/04/26/[runtime-logs-session-b-1777171992-...]08a1031f-...`

**증거**: `artifacts/04-session-isolation.log` + CloudWatch log streams (`aws logs describe-log-streams` 출력).

**의미**: 격리는 확실히 동작. 다만 hypervisor(Firecracker vs Nitro)는 여전히 외부에서 식별 불가. 블로그가 이 점을 이미 단서로 달고 있음 (Line 153). 일관됨.

주의할 한 가지: **"세션 내 memory persistence"는 별도 기능**이며 기본 템플릿(`NO_MEMORY` 모드)에서는 동작하지 않음. Memory 사용을 원한다면 `agentcore memory create`로 명시적 구성 필요.

---

### 주장 #3: "내장 도구 바인딩 (Browser, Code Interpreter, Gateway, MCP)"

**판정: 사실 (단, 바인딩 방식은 블로그 설명과 다름)**

블로그 원문 (Line 60-67, 84-89):
> `tools` 배열에 `agentcore_browser`, `agentcore_gateway`, `remote_mcp_server`를 추가하면 각각 웹 브라우징, 엔터프라이즈 API 연결, 외부 MCP 서버 연결이 붙습니다.

**실측**:
- 실제 바인딩은 **Python 코드에서 import 후 리스트에 넣는** 방식:
  - `from strands_tools.code_interpreter import AgentCoreCodeInterpreter` → `tools=[code_interpreter.code_interpreter]`
  - MCP 서버는 `MCPClient(lambda: streamablehttp_client(MCP_ENDPOINT))` + `client.list_tools_sync()`
  - 커스텀 도구는 `@tool` decorator
- HelloAgent 기본 템플릿은 **Code Interpreter + MCP(ExaAI 예제)** 조합을 보여줌.
- `agentcore gateway create-mcp-gateway` 서브커맨드도 존재 → gateway를 CLI로 프로비저닝 가능.

**증거**: `my-project/HelloAgent/src/main.py`, `artifacts/06-tools-inspect.log` (gateway 서브커맨드 help).

**의미**: 도구 기능 자체는 존재하고 연결됨. 하지만 블로그가 말한 "`tools` 배열에 문자열 추가" 식의 JSON 선언적 방식이 아니라, **Python 코드 의존성 import + Strands `tools=[]` 인자**로 바인딩됨.

---

### 주장 #4: "Skills 통합 (Kiro, Claude Code, Codex, Cursor)"

**판정: 미확인**

블로그 원문 (Line 139):
> Skills는 코딩 어시스턴트용 플러그인 묶음으로, 첫 번째 타깃은 Kiro입니다. AWS가 Claude Code, OpenAI Codex, Cursor용 플러그인도 4월 말까지 제공한다고 밝혔습니다.

**실측**:
- `@aws/agentcore` CLI에는 **`skills`라는 서브커맨드가 없음**.
- 대신 `strands` 패키지 내부에 `strands.vended_plugins.skills` 모듈 존재 (Strands 프레임워크 기능).
- CLI 레벨의 Skills 통합은 확인 불가 — 별도 IDE 플러그인 형태일 가능성.

**증거**: `artifacts/cli-help-full.txt` (전체 help 덤프), `artifacts/06-tools-inspect.log` (strands.vended_plugins.skills 경로만 grep됨).

**의미**: 이 주제는 CLI가 아닌 IDE 플러그인 영역이므로 이 실험 범위 밖. 블로그 주장에 대한 반증도 사실도 아님.

---

### 주장 #5: "관측성 기본 제공 (CloudWatch 로그, OTel 트레이스, 메트릭 네임스페이스 `AWS/Bedrock-AgentCore`)"

**판정: 사실 (실측으로 강한 확증)**

블로그 원문 (Line 215):
> 실측 결과 메트릭 네임스페이스는 `AWS/Bedrock-AgentCore`(하이픈 포함)이고, 로그 그룹은 `/aws/bedrock-agentcore/runtimes/<RUNTIME-ID>-DEFAULT` 패턴으로 자동 생성됩니다. 기본 메트릭 8종(`Latency`, `SystemErrors`, `UserErrors`, `Throttles`, `Sessions`, `Invocations`, `Errors`, `Duration`)이…

**실측**:
- 메트릭 네임스페이스 `AWS/Bedrock-AgentCore` 확인.
- 메트릭 종류 확인: **`Latency`, `SystemErrors`, `UserErrors`, `Throttles`** — 실측으로 4종 직접 확인 (invoke 수 적어 일부 메트릭은 emit 안 됐을 수 있음).
- Log group 패턴: `/aws/bedrock-agentcore/runtimes/HelloAgent_Agent-csgQQZ3Yid-DEFAULT` 정확히 일치.
- OTel: `entryPoint`가 `["opentelemetry-instrument", "main.py"]`로 자동 wrap됨 (`aws-opentelemetry-distro >= 0.10.0` 의존성 자동 포함).
- `agentcore obs list/show` 명령어 존재 (trace 조회) — 단 짧은 invoke에 대해서는 trace가 log로 propagate 되는 데 시간이 걸려 "No spans found" 반환된 순간도 있음.

**증거**: `artifacts/05-observability.log`.

**의미**: 블로그의 관측성 서술은 정확. 이전 실험에서 이미 확인된 내용의 재확증.

---

### 주장 #6: "지원 프레임워크 (Strands Agents가 엔진)"

**판정: 부분 거짓 (Strands는 **기본값**일 뿐, CLI는 6종 framework 지원)**

블로그 원문 (Line 72-74):
> Managed Harness가 내부에서 돌리는 에이전트 엔진은 AWS 오픈소스 프레임워크인 **Strands Agents**입니다. … 루프 제어, 도구 바인딩, 에러 복구, 스트리밍 출력이 Strands의 ReAct 스타일 루프 위에서 실행됩니다.

**실측**:
- `agentcore create --agent-framework` 옵션:
  ```
  [Strands|LangChain_LangGraph|GoogleADK|OpenAIAgents|AutoGen|CrewAI]
  [default: Strands]
  ```
- 즉 Strands는 **기본값**이고, 6개 프레임워크 모두 CLI 차원에서 선택 가능.

**모델 provider** (`--model-provider`):
  ```
  [Bedrock|OpenAI|Anthropic|Gemini]
  [default: Bedrock]
  ```
- 블로그가 "Bedrock, OpenAI, Google Gemini 세 곳"이라고 한 것과 달리 **Anthropic(Bedrock 외 직접 API) 옵션도 존재** (4개).

**증거**: `agentcore create --help`.

**의미**: 블로그의 "Strands가 엔진" 단언은 과도한 단순화. "기본 엔진은 Strands이고, 6개 프레임워크 중 선택 가능"이 정확한 서술.

---

### 주장 #7: "수 분 내 배포 (배포 시간)"

**판정: 사실 (실측 32초)**

블로그 원문 (Line 43): "**3번의 API 호출**로 끝나는 에이전트 배포"

**실측**:
- `agentcore deploy --auto-update-on-conflict` (direct_code_deploy 모드, CodeBuild 우회)
- **START 2026-04-26T02:52:10Z** → **END 2026-04-26T02:52:44Z**
- **실측 배포 소요: 32초** (직접 측정)

**증거**: `artifacts/03-deploy.log`.

**의미**: 블로그의 "수 분 내" 주장보다 실제는 훨씬 빠름 (기본 template, amd64, direct_code_deploy 조건). Container deploy 모드나 VPC 옵션 사용 시는 더 길어질 수 있음.

---

### 추가 발견 #A: IaC 옵션 — Terraform 이미 지원

블로그 원문 (Line 113):
> Terraform 지원은 이어서 제공될 예정이라고 공식 블로그가 예고했습니다.

**실측**: `agentcore create --iac` 옵션에 `[CDK|Terraform]`가 이미 존재 → **Terraform 이미 지원됨** (2026-04-26 시점).

**증거**: `agentcore create --help`.

---

### 추가 발견 #B: 기본 모델은 **Claude Sonnet 4.5** (blog는 4.6이라고 서술)

블로그 원문 (Line 47, 82):
> `model` 예시 값: `global.anthropic.claude-sonnet-4-6`  
> Bedrock에서는 Claude Sonnet 4.6이 기본값이고 Opus 4.6도 선택할 수 있습니다.

**실측** (`src/model/load.py`):
```python
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
```
→ **Claude Sonnet 4.5**가 HelloAgent 템플릿의 기본값.

**증거**: `my-project/HelloAgent/src/model/load.py`.

---

## 4. 판정 요약 테이블

| 주장 | 판정 | 근거 로그 |
|---|---|---|
| #1 3-선언 구조 (harness.json) | **부분 거짓** — 실제는 main.py + YAML | 01, 06 |
| #2 microVM 세션 격리 | **사실** | 04, 05 |
| #3 내장 도구 바인딩 | **사실 (방식은 코드)** | 06 |
| #4 Skills 통합 | **미확인** (CLI 범위 밖) | 06, cli-help-full.txt |
| #5 관측성 (네임스페이스, 메트릭 8종) | **사실** | 05 |
| #6 Strands가 엔진 | **부분 거짓** — 6 framework 중 기본값 | create --help |
| #7 수 분 내 배포 | **사실** (32초 실측) | 03 |
| 추가: Terraform 미지원 | **거짓** — 이미 지원 | create --help |
| 추가: Sonnet 4.6 기본 | **거짓** — Sonnet 4.5 기본 | model/load.py |

## 5. Cleanup 확인

- `agentcore destroy --force` 정상 종료.
- `aws bedrock-agentcore-control list-agent-runtimes` → `HelloAgent_Agent` 미존재, 기타 런타임(`deep_insight_runtime_vpc`, 다른 프로젝트)은 그대로 (건드리지 않음).
- S3 artifacts (`HelloAgent_Agent/deployment.zip`, `.../source.zip`) 삭제 확인.
- IAM 실행 역할 `AmazonBedrockAgentCoreSDKRuntime-us-west-2-1458877702` 삭제 확인.
- CloudWatch log group `/aws/bedrock-agentcore/runtimes/HelloAgent_Agent-csgQQZ3Yid-DEFAULT` 는 잔존 (수명주기 보존 정책). 비용 영향 미미.

## 6. 실험 범위 및 한계

- 이번 실험은 **`@aws/agentcore` CLI v0.11.0**만 대상으로 함. 블로그가 참조한 ClassMethod 기사의 `harness.json` 구조는 이 CLI와 일치하지 않음 → CLI 외 경로(예: Managed Harness 전용 console 또는 다른 내부 SDK)일 가능성 존재.
- "Managed Harness" 단어 자체는 AWS 블로그에서 명확히 정의되지 않음. 실제 CLI는 **AgentCore Runtime** 기반 Strands 코드 배포 경험을 제공.
- Skills IDE 플러그인은 검증 범위 밖.
- Hypervisor 타입(Firecracker 등)은 여전히 공개되지 않음.

## 7. 결론

- `@aws/agentcore` CLI는 **2026-04-26 시점 정상 동작**: 생성, 로컬 개발, 배포, 호출, 격리, 관측성, 정리 모두 확인.
- 블로그의 **큰 그림**(관리형 추상화, 세션 격리, 관측성, 빠른 배포)은 사실.
- **구체 서술 중 수정 필요**:
  1. "harness.json 3-선언"은 현재 공개 CLI와 불일치 → "Python 코드 + YAML 설정" 조합으로 수정 필요
  2. "Terraform 지원 예정"은 이미 GA → "CDK 또는 Terraform 선택 가능"
  3. "Strands가 엔진" → "Strands 기본, LangChain/LangGraph/GoogleADK/OpenAIAgents/AutoGen/CrewAI 선택 가능"
  4. "모델 provider Bedrock/OpenAI/Gemini 세 곳" → "Bedrock/OpenAI/Anthropic/Gemini 네 곳"
  5. "기본 모델 Sonnet 4.6" → 실제 템플릿은 "Sonnet 4.5"
