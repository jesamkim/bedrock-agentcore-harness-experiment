# 블로그 정정 사항 — AgentCore "Managed Harness" 실전 검증 결과

대상 블로그: `2026-04-26-bedrock-agentcore-managed-harness-deep-dive.md`
검증일: 2026-04-26
검증 환경: AWS 123456789012, us-west-2, bedrock-agentcore-sdk-python 1.2.0, starter-toolkit 0.2.6, strands-agents 1.29.0
검증 결과물: `results.md`, `deploy-log.json`, `invoke-results.json`, `isolation-results.json`, `observability-results.json`

---

## 1. 명칭 — "Managed Harness"는 AWS 공식 용어가 아님

**블로그 주장**: "AgentCore의 Managed Harness가 3-선언만으로 에이전트를 배포한다."

**실제**: AWS 공식 문서/SDK/CLI/What's New 어디에도 "Managed Harness"라는 용어는 없다. 블로그가 만든 비공식 라벨이다.

**정확한 구성 요소** (세 개가 합쳐진 것):
1. `BedrockAgentCoreApp` — `bedrock_agentcore.runtime.app` 의 Starlette 기반 HTTP 래퍼
2. 에이전트 프레임워크 (Strands / LangGraph / CrewAI / Autogen / OpenAI Agents / Google ADK 중 택 1)
3. **AgentCore Runtime** — 관리형 호스팅 서비스 (실제 AWS 제품명)

**정정 제안**: "Managed Harness" → "AgentCore Runtime + `BedrockAgentCoreApp` 래퍼 + (사용자 선택) Strands 에이전트" 로 표기.

---

## 2. "3-선언 배포" — 레이어가 섞인 설명

**블로그 주장**: "`model`, `systemPrompt`, `tools` 3개 필드만 선언하면 배포된다."

**실제**:
- 그 3개 필드는 **AgentCore의 배포 API가 아니라** `strands.Agent(model=..., system_prompt=..., tools=[...])` 생성자 인자다.
- AgentCore 실제 배포 API(`create_agent_runtime` 또는 toolkit `Runtime.launch()`)는 추가로 다음이 필요하다:

| 필수/사실상 필수 필드 | 이번 실험 실측 값 |
|---|---|
| `entrypoint` | `main.py` |
| `agent_name` | `harness_test_2fe9b30a` |
| `requirements_file` | `requirements.txt` |
| `runtime_type` | `PYTHON_3_10` (누락 시 `configure()` 실패) |
| `auto_create_execution_role` | `True` (자동 IAM 롤 생성) |
| `memory_mode` | `NO_MEMORY` |
| S3 아티팩트 업로드 | `bedrock-agentcore-codebuild-sources-...` 버킷에 59 MB zip |
| IAM 역할 | `AmazonBedrockAgentCoreSDKRuntime-us-west-2-5e82d0bbf1` (자동 생성) |
| `pythonRuntime`, `entryPoint`, `roleArn`, `agentRuntimeArtifact` | 제어 평면 API 필수 파라미터 |

**정정 제안**: "3-선언"이라는 표현을 유지하려면, 그것이 **Strands Agent 정의**에 국한된 표현임을 명확히 해야 한다. AgentCore 배포 전체 플로우는 `agentcore configure`(13개+ 필드) + `agentcore deploy` 두 단계다.

---

## 3. "Firecracker microVM"은 공개된 사실이 아님

**블로그 주장**: "세션마다 Firecracker microVM이 생성된다."

**실제**:
- AWS devguide는 **"microVM" 용어는 공식 사용** ("Each user session in AgentCore Runtime receives its own dedicated microVM with isolated Compute, memory, and filesystem resources").
- 그러나 **"Firecracker"라는 단어는 AgentCore 공식 문서에 전혀 등장하지 않는다.**
- 이번 실험에서 수집한 응답 헤더에도 hypervisor 관련 힌트는 없었다:
  - 보이는 것: `x-amzn-requestid`, `x-amzn-bedrock-agentcore-runtime-session-id`
  - 보이지 않는 것: VM ID, host ID, hypervisor 종류, 어떤 Firecracker 관련 문자열도 없음

**정정 제안**: "Firecracker"를 단정적으로 언급하지 말고 "microVM" 만 사용. "AWS의 경량 가상화 기술 기반 microVM (hypervisor 구체 종류는 공개되지 않음)" 정도가 안전하다.

---

## 4. "Strands가 AgentCore의 내부 엔진" — 오해

**블로그 주장**: "AgentCore의 내부 엔진은 Strands Agents이다."

**실제**:
- `bedrock-agentcore-starter-toolkit`의 템플릿 디렉터리 `create/features/` 아래에 `strands/`, `langchain_langgraph/`, `crewai/`, `openaiagents/`, `googleadk/`, `autogen/` 이 모두 1급(first-class) 지원된다.
- `BedrockAgentCoreApp`은 Starlette HTTP 서버 래퍼 — **프레임워크 중립**이다. `/invocations` POST 핸들러만 구현하면 된다.
- Strands가 `agentcore create` 의 기본 템플릿이라서 그렇게 보일 뿐, 내부 엔진 개념 자체가 없다.

**정정 제안**: "Strands는 AgentCore에서 기본 템플릿으로 제공되는 여러 지원 프레임워크 중 하나"로 표기. "내부 엔진"이라는 말은 삭제.

---

## 5. "프리뷰 기능" — 사실과 다름

**블로그 주장**: "AgentCore는 프리뷰(preview) 기능이라 가입/활성화가 필요하다."

**실제**:
- **2025-10-13 GA**. AWS 블로그 "Amazon Bedrock AgentCore is now generally available" (2025-10-13) 참조.
- 별도 enrollment 불필요. 표준 IAM 권한만 있으면 사용 가능.
- 9개 리전 지원: us-east-1, us-east-2, us-west-2, eu-west-1, eu-central-1, ap-south-1, ap-southeast-1, ap-southeast-2, ap-northeast-1.
- 서울 리전(ap-northeast-2)은 2026-04 기준 아직 미지원.

**정정 제안**: "프리뷰"를 "GA (2025-10 정식 출시, 현재 9개 리전 지원, 서울 리전 제외)"로 수정.

---

## 6. "CodeBuild로 arm64 빌드" — 기본값이 아님

**블로그 암시**: "배포 시 CodeBuild가 arm64 컨테이너를 빌드한다."

**실제 (이번 실험 실측)**:
- `deployment_type="direct_code_deploy"`(toolkit 0.2.6 기본값)는 **CodeBuild를 사용하지 않는다.**
- 대신 클라이언트에서 **`uv`**로 `aarch64-manylinux2014` 타깃 크로스 컴파일 → 59 MB ZIP → S3 업로드.
- 따라서 `deploy_agent.py` 실행 시 **`uv` 바이너리가 로컬에 설치되어 있어야 한다.** 없으면 `RuntimeError: uv is required for direct_code_deploy deployment but was not found.` 오류 발생.
- CodeBuild 프로젝트(`bedrock-agentcore-harness_test_2fe9b30a`)는 scaffold로 생성되지만 실제 빌드 job은 돌지 않는다.
- 이것이 블로그의 "<5분 배포" 주장보다 훨씬 빠른 **27.8초** 배포를 설명한다.
- 런타임 자체는 여전히 ARM64 Graviton에서 실행된다 — 빌드 방식만 클라이언트-side인 것.

**정정 제안**:
- "CodeBuild arm64 빌드" → "로컬 `uv` 크로스 컴파일 (`direct_code_deploy` 모드) 또는 컨테이너 이미지 배포 (`container` 모드) 선택 가능"
- 배포 시간: "수 분" → "`direct_code_deploy`는 ~30초, 컨테이너 모드는 3~5분"

---

## 7. "툴 호출" — 동작은 하지만 SDK 메타데이터 표면화는 불완전

**블로그 주장**: "에이전트가 툴을 호출하고 결과를 깔끔하게 반환한다."

**실제 (이번 실험)**:
- **서버 측 툴 실행은 정상 동작**: CloudWatch 로그에 `Tool #1: get_current_time`, `Tool #2: add_numbers` 명시적으로 기록됨.
- 응답 본문에 계산 결과가 포함됨: `17+25=42`, `888+1234=2122`, 실제 UTC 타임스탬프 (`2026-04-26T01:57:58.987633+00:00`).
- **그러나 Strands 1.29.0의 `AgentResult.tool_uses` 필드는 빈 배열**. SDK 레벨에서 툴 호출 메타데이터를 클라이언트로 surface하는 기능이 제대로 동작하지 않음.
- 툴 호출 내역을 프로그래매틱하게 확인하려면 지금은 **CloudWatch Logs**에 의존해야 한다.

**정정 제안**: 툴 호출 섹션에 "현재 Strands 1.29에서는 `AgentResult.tool_uses` 메타데이터가 일관되게 채워지지 않는 이슈가 있음. 툴 호출 이력 확인은 CloudWatch 로그를 통해 가능" 주석 추가.

---

## 8. 관측성(Observability) 네임스페이스 — 정확한 이름

**블로그 주장**: "CloudWatch에 자동으로 메트릭/로그가 쌓인다."

**실제**: 사실이다. 다만 **네임스페이스 명이 정확하지 않으면 메트릭을 못 찾는다.**

| 네임스페이스 | 존재? | 비고 |
|---|---|---|
| `AWS/BedrockAgentCore` | ❌ | 많은 블로그/가이드가 이 이름을 쓰지만 존재하지 않음 |
| `AWS/Bedrock-AgentCore` | ✅ | **하이픈 포함이 정답** (17개 메트릭) |
| `AWS/Bedrock/AgentCore` | ❌ | |
| `bedrock-agentcore` | ❌ | |

**로그 그룹 패턴**: `/aws/bedrock-agentcore/runtimes/<RUNTIME-ID>-DEFAULT`
**게재 메트릭**: `Latency`, `SystemErrors`, `UserErrors`, `Throttles`, `Sessions`, `Invocations`, `Errors`, `Duration`
**차원**: `{Resource: <runtime ARN>, Operation: InvokeAgentRuntime, Name: <agent-name>::DEFAULT}`

**정정 제안**: 블로그에 메트릭 네임스페이스를 명시할 때 `AWS/Bedrock-AgentCore` (하이픈 주의)로 표기.

---

## 9. VTEX / Rodrigo Moreira 인용구

**블로그**: Rodrigo Moreira (VTEX) 발언을 인용.

**실제**: 공개 웹에서 **원 출처를 찾지 못함**. AWS GA 발표 블로그, AgentCore 제품 페이지, 접근 가능한 AWS 자료에서 해당 인용구를 확인할 수 없었다.

**정정 제안**:
- (a) 블로그에 인용의 1차 출처 URL (AWS case study, press release 등) 명시 — 있다면
- (b) 확인 불가 시 해당 인용구 제거 또는 "출처: 내부 자료" 주석

---

## 10. 기타 실측 세부사항 (블로그 강화용)

실험에서 확인된 구체적 수치/사실로, 블로그의 기술 신뢰성을 올리는 데 사용 가능:

| 항목 | 실측 값 |
|---|---|
| 배포 시간 (direct_code_deploy) | 27.8초 (configure 0.2초 + launch 27.5초 + poll 0.1초) |
| Cold invoke latency | 6.57초 (클라이언트 측정, 서버 핸들러 3.55초) |
| Warm invoke latency | 3.27초 (서버 핸들러 3.17초) |
| Warm speedup | ~3.3초 |
| 패키지 크기 | 59.26 MB (dependencies + main.py) |
| `idleRuntimeSessionTimeout` | 900초 (15분 — idle 세션 자동 종료) |
| `maxLifetime` | 28,800초 (8시간 — 세션 최대 수명) |
| `requireMMDSV2` | true (IMDSv2 강제) |
| `networkMode` | PUBLIC (VPC 구성 가능) |
| `agentRuntimeVersion` | 자동으로 1부터 시작, 업데이트 시 증가 |
| `workloadIdentityDetails.workloadIdentityArn` | 각 런타임에 자동 생성 |
| IAM 역할 네이밍 | `AmazonBedrockAgentCoreSDKRuntime-<region>-<hash>` |
| IAM eventual consistency | 신규 롤 어시움 실패 시 자동 재시도 (1/4 … 4/4) |
| 세션 격리 헤더 | `x-amzn-bedrock-agentcore-runtime-session-id` 만 노출 (VM ID 등 내부 식별자 없음) |
| 세션 어피니티 | session ID 같으면 같은 microVM으로 라우팅 (warm) |
| 모델 ID (올바른 형식) | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (**날짜 포함 필수**) |

---

## 11. 블로그 수정 우선순위

**반드시 수정 (사실 오류)**:
1. "프리뷰" → "GA (2025-10-13)"
2. "Strands가 내부 엔진" → "Strands는 기본 템플릿/지원 프레임워크 중 하나"
3. "Firecracker" 단정 → "microVM (hypervisor 종류 비공개)"
4. CodeBuild arm64 빌드 주장 → `direct_code_deploy`는 `uv` 로컬 크로스컴파일

**수정 권장 (오해 소지)**:
5. "Managed Harness" 용어 사용 시 반드시 "(필자 지칭)" 주석
6. "3-선언"은 Strands Agent 정의에 한정된 설명임을 명시
7. 메트릭 네임스페이스 `AWS/Bedrock-AgentCore` (하이픈)

**추가 권장 (신뢰도 강화)**:
8. Rodrigo Moreira 인용구 출처 명시 or 제거
9. 배포 시간 실측치(27초) 반영
10. Strands `tool_uses` 메타데이터 이슈 주석

---

## 12. 종합 판정

| 블로그 핵심 주장 | 판정 | 비고 |
|---|---|---|
| 3-선언 배포 | **부분 사실** | Strands 정의는 맞음. AgentCore 배포 표면은 아님. |
| 세션 격리 (microVM) | **사실** | 행동 관찰로 확인 |
| Firecracker | **미확인** | 공개 증거 없음 |
| Strands 내부 엔진 | **거짓** | 프레임워크 agnostic |
| 프리뷰 기능 | **거짓** | GA |
| 관측성 내장 | **사실** | 네임스페이스만 정확히 |
| 툴 호출 동작 | **사실 (행동)** | SDK 메타데이터는 부분 동작 |

**요약**: 블로그의 *기술적 방향성과 주요 주장의 의도*는 대부분 옳으나, **용어/사실 관계 7개 지점**에서 수정이 필요하다. 위 1~8 항목은 블로그에 수정 반영할 것을 권장한다.
