# 블로그 수정 제안: `2026-04-26-bedrock-agentcore-managed-harness-deep-dive.md`

**대상**: `content/posts/2026-04-26-bedrock-agentcore-managed-harness-deep-dive.md`  
**근거**: `<REPO>/results.md` + `artifacts/*.log`  
**원칙**: (A) 명확한 팩트 오류만 직접 수정, (B) 새 실측 인사이트는 별도 "실전 실험" 섹션으로 append, (C) 불확실한 것은 건드리지 않음.

---

## 수정 대상 #1: Terraform 지원 (Line 113) — 카테고리 **A (팩트 오류)**

**원문** (Line 113):
> `cdk/`는 AWS가 생성한 CDK 스택으로, 실제 리소스 프로비저닝을 여기서 수행합니다. **Terraform 지원은 이어서 제공될 예정이라고 공식 블로그가 예고했습니다.**

**증거**: `agentcore create --iac [CDK|Terraform]` 옵션이 v0.11.0에 이미 존재.

**수정안**:
> `cdk/`는 AWS가 생성한 CDK 스택으로, 실제 리소스 프로비저닝을 여기서 수행합니다. `agentcore create --iac [CDK|Terraform]` 옵션으로 **CDK와 Terraform 중 선택**할 수 있습니다(v0.11.0 기준 양쪽 모두 지원).

---

## 수정 대상 #2: 지원 모델 provider 개수 (Line 82) — 카테고리 **A**

**원문** (Line 82):
> 모델 provider는 **Amazon Bedrock, OpenAI, Google Gemini** 세 곳입니다.

**증거**: `agentcore create --model-provider [Bedrock|OpenAI|Anthropic|Gemini]` → Anthropic(Bedrock 외 직접 API) 옵션이 CLI에 명시.

**수정안**:
> 모델 provider는 **Amazon Bedrock, OpenAI, Anthropic(직접 API), Google Gemini** 네 곳입니다. CLI에서는 `agentcore create --model-provider` 플래그로 선택합니다.

---

## 수정 대상 #3: 지원 프레임워크 — "Strands가 엔진이다" 섹션 (Line 72-78) — 카테고리 **A**

**원문** (Line 72-78):
> ### Strands Agents가 엔진이다  
> Managed Harness가 내부에서 돌리는 에이전트 엔진은 AWS 오픈소스 프레임워크인 **Strands Agents**입니다. … 루프 제어, 도구 바인딩, 에러 복구, 스트리밍 출력이 Strands의 ReAct 스타일 루프 위에서 실행됩니다.

**증거**: `agentcore create --agent-framework [Strands|LangChain_LangGraph|GoogleADK|OpenAIAgents|AutoGen|CrewAI]` → Strands는 **기본값**이고 총 6개 프레임워크 선택 가능.

**수정안** (섹션 제목 + 첫 단락만 교체):
> ### Strands Agents가 기본 엔진이다  
> Managed Harness의 **기본 엔진**은 AWS 오픈소스 프레임워크인 **Strands Agents**입니다. 단, CLI의 `agentcore create --agent-framework` 옵션은 Strands 외에도 **LangChain/LangGraph, Google ADK, OpenAI Agents, AutoGen, CrewAI** 등 총 6개 프레임워크를 지원합니다(v0.11.0 기준). 기본값을 그대로 쓰면 루프 제어, 도구 바인딩, 에러 복구, 스트리밍 출력이 Strands의 ReAct 스타일 루프 위에서 실행됩니다.

나머지 단락(직접 Strands를 사용할 때와의 차이점 논의)은 유지.

---

## 수정 대상 #4: 프로젝트 구조 설명 (Line 99-115) — 카테고리 **A**

**원문** (Line 101-111):
> ```
> harnessSample/
> ├── agentcore/
> │   ├── agentcore.json     # 프로젝트 전체 스펙
> │   ├── aws-targets.json   # 배포 계정/리전
> │   └── cdk/               # CDK 스택
> └── app/
>     └── MyHarness/
>         ├── harness.json       # 하니스 선언
>         └── system-prompt.md   # 시스템 프롬프트
> ```

**증거**: `@aws/agentcore` v0.11.0 실측 생성물은 `harness.json`이나 `agentcore.json` 대신 `HelloAgent/.bedrock_agentcore.yaml` + `HelloAgent/src/main.py` + `HelloAgent/pyproject.toml` 구조.

**수정안** (대체):
> ```
> my-project/
> └── HelloAgent/
>     ├── .bedrock_agentcore.yaml  # 프로젝트 설정 (agent 이름, region, runtime, deployment_type)
>     ├── pyproject.toml           # 의존성 (strands, bedrock-agentcore, mcp 등)
>     ├── src/
>     │   ├── main.py              # Strands 에이전트 코드 + @entrypoint
>     │   ├── model/load.py        # 모델 로더 (BedrockModel 인스턴스)
>     │   └── mcp_client/client.py # MCP gateway 연결
>     └── test/
> ```
> v0.11.0 기준 CLI가 생성하는 기본 구조는 JSON 선언이 아닌 **Python 코드(Strands) + YAML 설정** 조합입니다. ClassMethod 기사의 `harness.json` 형태는 다른 경로(예: 내부 SDK 또는 미공개 분기)일 가능성이 있으며, 공개 `@aws/agentcore` CLI에서는 재현되지 않았습니다.

---

## 수정 대상 #5: `harness.json` 예시 블록 (Line 51-68) — 카테고리 **A**

**원문** (Line 51-68):
> [ClassMethod의 분석]에 공개된 `harness.json` 예시는 다음처럼 간결합니다.
> ```json
> {
>   "name": "MyHarness",
>   "model": {...},
>   "tools": [...],
>   "skills": []
> }
> ```
> `tools` 배열에 `agentcore_browser`, `agentcore_gateway`, `remote_mcp_server`를 추가하면 각각 웹 브라우징, 엔터프라이즈 API 연결, 외부 MCP 서버 연결이 붙습니다.

**증거**: 공개 CLI에서 harness.json이 생성되지 않음. 도구 바인딩은 Python `tools=[]`리스트로 이뤄짐.

**수정안**: `harness.json` 예시 블록은 "ClassMethod 기사의 서술이며, 공개 CLI(`@aws/agentcore` v0.11.0)에서는 `main.py` 안의 Strands `Agent(tools=[...])` 호출로 동일 기능을 제공한다"는 단서로 대체.

구체 교체 제안:
> [ClassMethod의 분석]은 `harness.json` 기반 선언 예시를 제시합니다. 다만 2026-04-26 기준 공개된 `@aws/agentcore` CLI가 생성하는 실제 구조는 JSON 선언이 아니라 Strands Python 코드 형태입니다:
>
> ```python
> # src/main.py 기본 템플릿 (일부 발췌)
> from strands import Agent
> from strands_tools.code_interpreter import AgentCoreCodeInterpreter
> from bedrock_agentcore.runtime import BedrockAgentCoreApp
>
> app = BedrockAgentCoreApp()
>
> @app.entrypoint
> async def invoke(payload, context):
>     code_interpreter = AgentCoreCodeInterpreter(...)
>     with mcp_client as client:
>         tools = client.list_tools_sync()  # MCP 도구 자동 발견
>         agent = Agent(
>             model=load_model(),                   # Bedrock 모델
>             system_prompt="You are a helpful ...",# 시스템 프롬프트
>             tools=[code_interpreter.code_interpreter, add_numbers] + tools,
>         )
> ```
>
> 개념적으로는 여전히 `model + systemPrompt + tools` 세 축이 에이전트를 정의합니다. 표현 매체(JSON vs Python)만 다를 뿐 철학은 동일합니다.

---

## 수정 대상 #6: "수 분 내 배포" 실측 수치 보강 (Line 129) — 카테고리 **B (실전 인사이트)**

**원문** (Line 129):
> `agentcore deploy`는 내부적으로 CDK 스택을 합성해 대상 계정에 올립니다. AgentCore Runtime 엔드포인트, IAM 역할, CloudWatch 로그 그룹, 필요하다면 VPC 엔드포인트까지 자동 생성됩니다. 배포 결과로 Runtime ARN이 출력되고, 이 ARN이 API 호출 시 타겟이 됩니다.

**증거**: `artifacts/03-deploy.log` — **32초** 실측.

**수정안** (단락 끝에 추가):
> HelloAgent 기본 템플릿 기준 실측 배포 소요는 **약 32초**입니다(`direct_code_deploy` 모드, `linux/amd64`, us-west-2). 컨테이너 배포나 VPC 엔드포인트가 포함되는 production 템플릿은 더 길어질 수 있습니다.

---

## 수정 대상 #7: "실전 실험: @aws/agentcore CLI" 신규 섹션 추가 — 카테고리 **B**

블로그 Line 245 ("마무리: 첫 하니스 올리기") 앞 또는 References 직전에 새 섹션 삽입.

**제안 본문**:

```markdown
## 실전 실험: `@aws/agentcore` CLI v0.11.0 동작 검증

2026-04-26에 `@aws/agentcore` CLI를 실제 계정(us-west-2)에 올려 주요 동작을 확인했습니다. 배포–호출–정리까지 전체 사이클을 직접 돌려본 결과 중 블로그 내용과 어긋나는 부분과, 실측으로 확인된 수치를 간단히 정리합니다.

**확인된 것**
- 배포 소요: **32초** (HelloAgent 기본 템플릿, direct_code_deploy 모드)
- 세션 격리: 서로 다른 sessionId로 보낸 요청이 코드워드를 공유하지 않음(블로그 Line 151-155 주장 재확인). CloudWatch log stream도 세션별로 분리되어 생성됨.
- 관측성: 메트릭 네임스페이스 `AWS/Bedrock-AgentCore`, 로그 그룹 `/aws/bedrock-agentcore/runtimes/<RUNTIME-ID>-DEFAULT` 패턴 일치. `Latency`, `SystemErrors`, `UserErrors`, `Throttles` 등 8종 메트릭 기본 emit.
- `agentcore destroy --force`로 Agent Runtime, S3 deployment artifacts, 실행 IAM 역할이 일관되게 정리됨.

**블로그 서술과 실제가 달랐던 부분**
- `harness.json` 기반 선언 구조는 공개 CLI(`@aws/agentcore` v0.11.0)에서는 생성되지 않습니다. 실제 템플릿은 `.bedrock_agentcore.yaml` + Strands 기반 `src/main.py` 구조입니다.
- 기본 프레임워크는 Strands이지만, CLI 옵션으로 LangChain/LangGraph, Google ADK, OpenAI Agents, AutoGen, CrewAI도 선택 가능합니다.
- Terraform IaC는 이미 지원됩니다(`agentcore create --iac [CDK|Terraform]`).
- 기본 모델은 HelloAgent 템플릿 기준 `global.anthropic.claude-sonnet-4-5-20250929-v1:0`입니다.

검증 스크립트와 로그는 [bedrock-agentcore-harness-experiment](https://github.com/jesamkim/bedrock-agentcore-harness-experiment) 레포에 공개되어 있습니다.
```

---

## 수정 대상 #8: 기본 모델 ID "Sonnet 4.6" 언급 (Line 47, 82) — 카테고리 **C (불확실)**

**원문** (Line 47):
> | `model` | 추론을 담당할 LLM | `global.anthropic.claude-sonnet-4-6` |
> (Line 82): Bedrock에서는 Claude Sonnet 4.6이 기본값이고 Opus 4.6도 선택할 수 있습니다.

**증거**: 이번 실험에서 HelloAgent 기본 템플릿은 `global.anthropic.claude-sonnet-4-5-20250929-v1:0`을 사용. 단, 블로그가 말하는 "기본값"은 `harness.json`의 기본값일 수도, Managed Harness preview 버전의 기본값일 수도 있음.

**수정 여부**: **수정하지 않음 (카테고리 C)**  
이유: 공개 CLI의 기본 템플릿은 4.5이지만, AWS가 발표한 Managed Harness 문서 어딘가에서 4.6을 명시했다면 블로그 주장이 맞을 수 있음. 양쪽 모두 증거가 1차 확인되지 않은 상태이므로 원문 유지.

단, **주장 #7(신규 섹션)에 "HelloAgent 템플릿 기본은 Sonnet 4.5"로 사실만 명시**하는 것으로 보완.

---

## 수정하지 않을 항목 (카테고리 C - 증거 부족)

- "VTEX 피드백" (Line 221): 블로그가 이미 재확인 어려움을 명시.
- "microVM hypervisor 종류 미공개" (Line 153): 블로그 원문이 이미 한계를 서술.
- "프리뷰 4개 리전" (Line 209): 이번 실험은 us-west-2만 검증. 나머지 3개 리전은 확인 안 함.
- "Skills IDE 플러그인" (Line 139): CLI 검증 범위 밖.
- "Sonnet 4.6 기본값" (Line 82): 공개 CLI는 4.5이지만 Managed Harness 기본이 실제 4.6일 가능성 남음.

## 반영 후 권장 체크

1. `git diff` 로 변경 범위 확인 — 8개 수정 예상.
2. Hugo build 테스트: `cd <blog-repo> && hugo --minify` (에러 없어야 함).
3. `grep -n "harness.json" content/posts/2026-04-26-...md` — 유지된 `harness.json` 언급은 "ClassMethod 기사" 맥락 내에만 남아야 함.
