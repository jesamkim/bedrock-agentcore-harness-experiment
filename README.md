# Bedrock AgentCore Harness 실험 — `@aws/agentcore` CLI v0.11.0 실측

Amazon Bedrock AgentCore Managed Harness(프리뷰), AgentCore CLI, AgentCore Skills 3종 세트를 직접 돌려본 재현 가능한 실험 노트입니다.

---

## TL;DR

- **대상**: `@aws/agentcore` v0.11.0 (실제 런너는 `bedrock-agentcore-starter-toolkit` Python CLI, npm 패키지는 이를 래핑)
- **배포 실측**: **32초** (HelloAgent 기본 템플릿, `direct_code_deploy`, us-west-2)
- **세션 격리**: 서로 다른 `sessionId` 간 코드워드 교차 오염 없음, CloudWatch log stream도 세션별 분리
- **관측성**: 메트릭 네임스페이스 `AWS/Bedrock-AgentCore`, log group `/aws/bedrock-agentcore/runtimes/<ID>-DEFAULT` 기본 생성, OTel 자동 wrap
- **정리**: `agentcore destroy --force`로 Runtime + S3 artifacts + IAM role 일관 삭제

## 레포 구조

```
.
├── README.md                       # 이 파일
├── research-findings.md            # 초기 CLI 조사 (커맨드 맵)
├── scripts/                        # 시나리오 실행 스크립트 (00~99 순차 실행)
│   ├── 00-env-check.sh             # 환경 검증
│   ├── 01-create-project.sh        # agentcore create
│   ├── 02-dev-local.sh             # agentcore dev 로컬 서버
│   ├── 03-deploy.sh                # AWS 클라우드 배포
│   ├── 04-invoke-session-isolation.sh
│   ├── 05-observability.sh         # CloudWatch metrics/logs 확인
│   ├── 06-tools-inspect.sh         # 도구/프레임워크 조사
│   ├── 99-cleanup.sh               # 전체 리소스 정리
│   └── README.md
├── artifacts/                      # 실행 결과 로그 (sanitized)
│   ├── 00-env-check.log
│   ├── 01-project-tree.log
│   ├── 02-dev-local.log
│   ├── 03-deploy.log
│   ├── 04-session-isolation.log
│   ├── 05-observability.log
│   ├── 06-tools-inspect.log
│   ├── 99-cleanup.log
│   ├── agent-arn.txt
│   └── cli-help-full.txt           # agentcore --help 전체 덤프
├── example-agent/                  # agentcore create가 생성한 기본 템플릿 (샘플)
│   ├── pyproject.toml
│   ├── README.md
│   └── src/
│       ├── main.py                 # Strands Agent + Code Interpreter + MCP
│       ├── model/load.py           # BedrockModel 로더
│       └── mcp_client/client.py    # MCP Gateway 클라이언트
└── legacy-runtime-experiment/      # 이전(Runtime 레이어) 실험 보존 — 참고용
    ├── main.py, deploy_agent.py, …
    └── artifacts/
```

## 재현 방법

### 사전 요구 사항

- AWS 계정 (프리뷰 리전 4곳: us-west-2 / us-east-1 / eu-central-1 / ap-southeast-2 중 하나)
- Python ≥ 3.10, Node ≥ 20
- AWS CLI profile 설정
- Bedrock 모델 접근 권한 (기본 템플릿은 Claude Sonnet 4.5)

### CLI 설치

```bash
# npm 래퍼 (실제는 Python starter-toolkit 번들)
npm install -g @aws/agentcore

# 또는 Python 직접
pip install bedrock-agentcore-starter-toolkit

agentcore --help
```

### 시나리오 순차 실행

`scripts/*.sh`는 모두 환경 변수 `AWS_PROFILE`, `AWS_REGION`, `PATH`를 가정합니다. 실제 환경에 맞게 수정하세요.

```bash
export AWS_PROFILE=<your-profile>
export AWS_REGION=us-west-2
export PATH="$HOME/.local/bin:$PATH"

# 순차 실행 권장
bash scripts/00-env-check.sh
bash scripts/01-create-project.sh
bash scripts/02-dev-local.sh
bash scripts/03-deploy.sh              # <-- AWS 리소스 생성 시작
bash scripts/04-invoke-session-isolation.sh
bash scripts/05-observability.sh
bash scripts/06-tools-inspect.sh
bash scripts/99-cleanup.sh             # <-- 반드시 실행 (비용 누수 방지)
```

각 단계 로그는 `artifacts/NN-*.log`로 저장됩니다.

## 핵심 관찰

### 1. 프로젝트 구조 — Strands 코드 + YAML 설정

`agentcore create` 결과:

```
my-project/
└── HelloAgent/
    ├── .bedrock_agentcore.yaml  # 프로젝트 설정 (런타임, deployment_type, 실행 role 등)
    ├── pyproject.toml           # strands-agents, bedrock-agentcore, mcp …
    └── src/
        ├── main.py              # Strands Agent + @app.entrypoint
        ├── model/load.py        # BedrockModel 로더
        └── mcp_client/client.py # streamablehttp MCP 클라이언트
```

`src/main.py` 핵심:

```python
from strands import Agent, tool
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@tool
def add_numbers(a: int, b: int) -> int:
    return a + b

@app.entrypoint
async def invoke(payload, context):
    code_interpreter = AgentCoreCodeInterpreter(
        region=REGION, session_name=context.session_id,
        auto_create=True, persist_sessions=True,
    )
    with mcp_client as client:
        tools = client.list_tools_sync()
        agent = Agent(
            model=load_model(),
            system_prompt="You are a helpful assistant ...",
            tools=[code_interpreter.code_interpreter, add_numbers] + tools,
        )
        async for event in agent.stream_async(payload.get("prompt")):
            if "data" in event and isinstance(event["data"], str):
                yield event["data"]
```

에이전트는 `model + system_prompt + tools` 세 축으로 정의되며, 표현 매체는 Python + Strands 런타임입니다.

### 2. 세션 격리 + 관측성 검증

| 검증 방식 | 결과 |
|---|---|
| Session A에 "코드워드 XRAY-1111 기억해" → Session B에 "코드워드는?" | Session B = `UNKNOWN` (격리됨) |
| CloudWatch log streams (us-west-2) | 세션마다 `[runtime-logs-session-<id>]` 독립 stream |
| `AWS/Bedrock-AgentCore` 메트릭 네임스페이스 | `Latency`, `SystemErrors`, `UserErrors`, `Throttles` 실측 확인 |
| OTel 자동 활성화 | `entryPoint=["opentelemetry-instrument", "main.py"]` 자동 wrap |

`agentcore obs list/show` 명령어로 trace를 CLI에서 바로 조회 가능합니다.

### 3. 프레임워크/IaC/Provider 선택지 (v0.11.0 기준)

```
agentcore create
  --agent-framework  [Strands|LangChain_LangGraph|GoogleADK|OpenAIAgents|AutoGen|CrewAI]
  --model-provider   [Bedrock|OpenAI|Anthropic|Gemini]
  --iac              [CDK|Terraform]
  --template         [basic|production]
```

Strands는 기본값이며, CDK/Terraform IaC와 Bedrock/OpenAI/Anthropic/Gemini 모델 provider가 선택지로 제공됩니다.

### 4. HelloAgent 기본 모델

기본 템플릿이 생성하는 `src/model/load.py`는 `global.anthropic.claude-sonnet-4-5-20250929-v1:0` (Claude Sonnet 4.5)를 참조합니다.

## legacy-runtime-experiment (참고용)

이 디렉토리에는 이전 실험(AgentCore Runtime 레이어 + Strands 직접 호출) 코드와 결과가 보존되어 있습니다. 이번 CLI 실험과는 추상화 수준이 다르므로 별도 디렉토리로 분리했습니다.

## 관련 링크

- AWS 발표: https://aws.amazon.com/blogs/machine-learning/get-to-your-first-working-agent-in-minutes-announcing-new-features-in-amazon-bedrock-agentcore/
- AgentCore CLI (npm): https://www.npmjs.com/package/@aws/agentcore
- AgentCore Starter Toolkit (Python): https://github.com/aws/bedrock-agentcore-starter-toolkit

## 라이선스

MIT. 실험 코드와 로그는 자유롭게 사용 가능합니다. AWS 계정 ID나 profile 이름은 redact된 상태로 공개되어 있으며, 실제 실행 시에는 본인 환경으로 교체하세요.
