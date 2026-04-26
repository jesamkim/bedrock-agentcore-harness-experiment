# AgentCore CLI 리서치 보고서

출처:
- `/usr/lib/node_modules/@aws/agentcore/README.md` (npm 패키지 v0.11.0)
- `/usr/lib/node_modules/@aws/agentcore/package.json`
- `/usr/lib/node_modules/@aws/agentcore/dist/assets/README.md` (`agentcore create` 템플릿 원본 README)
- `/usr/lib/node_modules/@aws/agentcore/dist/assets/agents/AGENTS.md`
- `/usr/lib/node_modules/@aws/agentcore/dist/schema/schemas/agentcore-project.d.ts` (Zod 스키마 타입 선언)
- `<REPO>/artifacts/cli-help-full.txt` (370 lines, 13개 주요 커맨드)

---

## 1. CLI 커맨드 완전 맵

### 프로젝트 라이프사이클
- `agentcore create` - 프로젝트 생성 (+ `create import`: Bedrock Agent 임포트)
- `agentcore dev` - 로컬 개발 서버(기본 :8080, hot reload)
- `agentcore deploy` - 3가지 모드: default(cloud), `--local`, `--local-build`
- `agentcore invoke` - `--local` / `--dev` / cloud 모두 지원
- `agentcore status` - 배포 상태
- `agentcore destroy` - 리소스 삭제

### 리소스 관리 (README에 있으나 help에는 직접 노출 안 됨)
- `agentcore add` / `agentcore remove` - agents, memory, credentials, evaluators, targets, policy
- `agentcore import` - 기존 Bedrock Agent 가져오기

### 서브커맨드 그룹
- `agentcore gateway` - 9개 서브(create-mcp-gateway, list-mcp-gateways, update-gateway 등)
- `agentcore memory` - 5개 서브(create/get/list/delete/status)
- `agentcore eval` - 3개(run, evaluator, online)
- `agentcore identity` - 9개(Cognito, AWS JWT, credential-provider, workload-identity)
- `agentcore policy` - Cedar 기반(14개 서브, policy-engine/policy/policy-generation)
- `agentcore configure` - 광범위한 플래그(vpc/subnets/security-groups/authorizer-config/disable-otel/disable-memory 등)
- `agentcore obs` - **`show`, `list` 두 개뿐** (block-level trace 시각화용)

### 유틸리티 (README 기준)
- `agentcore logs`, `agentcore traces list/get`, `agentcore validate`, `agentcore package`, `agentcore fetch access`, `agentcore update`
- README는 `logs`/`traces`를 별도 최상위 커맨드로 광고하지만 CLI v0.11.0 런타임 help에서는 `obs` 하위 `show/list`로만 보임 -> 문서와 실제 바이너리 간 불일치 가능성

---

## 2. `agentcore create` 템플릿 동작

### basic vs production
- `--template basic`: runtime 코드만 (기본값)
- `--template production`: MCP setup + IaC 포함

### 기본값
- `--agent-framework Strands` (기본, 필수 아님 — CrewAI/LangChain_LangGraph/GoogleADK/OpenAIAgents/AutoGen 선택 가능)
- `--model-provider Bedrock` (기본)
- `--iac CDK` (기본, Terraform 선택 가능)
- `--venv` (자동 venv + 의존성 설치)

### 생성되는 프로젝트 구조 (`assets/README.md` 기준)
```
my-project/
├── AGENTS.md
├── agentcore/
│   ├── agentcore.json
│   ├── aws-targets.json
│   ├── .env.local                (gitignored)
│   ├── .llm-context/             (TypeScript 타입 정의)
│   │   ├── agentcore.ts
│   │   ├── aws-targets.ts
│   │   └── mcp.ts
│   └── cdk/                      (@aws/agentcore-cdk L3 constructs)
├── app/                          (agent code)
└── evaluators/                   (optional)
```

### 사용 가능한 프레임워크 템플릿 조합
- HTTP 프로토콜: strands, langchain_langgraph, googleadk, openaiagents, autogen
- MCP 프로토콜: standalone만
- A2A 프로토콜: strands, langchain_langgraph, googleadk
- AGUI 프로토콜: strands, langchain_langgraph, googleadk

즉 **HTTP 서버는 5개 프레임워크 지원, MCP는 프레임워크 불특정(standalone)**.

---

## 3. `agentcore.json` 스키마 (Zod 기반)

### 최상위 스키마: `AgentCoreProjectSpecSchema`
**필수 필드** (명시적):
- `name` (ZodString)
- `version` (ZodNumber)

**기본값 있음 (`ZodDefault`)**:
- `managedBy`: "CDK"
- `runtimes`: `[]`
- `memories`: `[]`
- `credentials`: `[]`
- `evaluators`: `[]`
- `onlineEvalConfigs`: `[]`
- `agentCoreGateways`: `[]`

**선택 필드**:
- `$schema`, `tags`

따라서 **최소 유효 JSON은**:
```json
{"name": "my-project", "version": 1}
```
블로그 "3개 선언만으로" 주장은 **name/version만 강제이므로 엄밀히 2개**. 하지만 실제 쓸모 있으려면 runtimes 배열에 최소 1개가 필요.

### `Runtime` 스키마 (runtimes 배열 내 아이템)
**필수**: `name`, `build` (CodeZip|Container), `entrypoint`, `codeLocation`
**선택**: `description`, `dockerfile`, `runtimeVersion` (Python 3.10-3.14 or Node 18/20/22), `envVars`, `networkMode` (PUBLIC|VPC), `networkConfig` (subnets+securityGroups), `instrumentation.enableOtel`, `protocol` (HTTP|MCP|A2A|AGUI), `requestHeaderAllowlist`, `executionRoleArn`, `authorizerType` (AWS_IAM|CUSTOM_JWT), `authorizerConfiguration` (OIDC JWT 상세), `lifecycleConfiguration` (idle/maxLifetime), `filesystemConfigurations` (sessionStorage.mountPath)

### Memory 스키마
- 필수: `name`, `eventExpiryDuration`
- 전략 타입: `SEMANTIC`, `SUMMARIZATION`, `USER_PREFERENCE`, `EPISODIC`

### Credential 스키마
- Discriminated union: `ApiKeyCredentialProvider` | `OAuthCredentialProvider`

### Gateway/Target 스키마
- targetType: `lambda`, `mcpServer`, `openApiSchema`, `smithyModel`, `apiGateway`, `lambdaFunctionArn`
- compute.host: `Lambda` | `AgentCoreRuntime`
- 구현 언어: Python 또는 TypeScript

### Evaluator 스키마
- level: `SESSION` | `TRACE` | `TOOL_CALL`
- config: `llmAsAJudge` 또는 `codeBased` (managed/external Lambda)

---

## 4. 지원 프레임워크/모델 프로바이더

### 프레임워크 (README Table 기준)
| Framework | Notes |
|---|---|
| Strands Agents | AWS-native, streaming (기본값) |
| LangChain/LangGraph | Graph-based workflows |
| CrewAI | Multi-agent orchestration |
| Google ADK | Gemini only |
| OpenAI Agents | OpenAI only |
| AutoGen | HTTP 템플릿에만 존재 |

**결론**: Strands는 "기본값"이지 "유일"하지 않다. 6개 중 5개가 실제 템플릿 디렉터리를 가진다.

### 모델 프로바이더 (README)
| Provider | Default Model |
|---|---|
| Amazon Bedrock (no key) | `us.anthropic.claude-sonnet-4-5-20250514-v1:0` |
| Anthropic (key) | `claude-sonnet-4-5-20250514` |
| Google Gemini (key) | `gemini-2.5-flash` |
| OpenAI (key) | `gpt-4.1` |

**확인**: Bedrock 기본 모델 = Sonnet **4.5** (블로그 주장과 일치). 단, 실제 모델 ID 문자열은 `20250514-v1:0`로 2025년 5월 스냅샷. 2026년 현 시점 기준으로는 오래된 기본값일 수 있음.

---

## 5. 관측성 기능 (중요!)

### CLI 런타임 help (v0.11.0) 기준
```
agentcore obs
├── show  - Show trace details with full visualization
└── list  - List all traces in a session with numbered index
```
**`logs`, `traces list`, `traces get`가 obs 하위에 없음**. help에는 `--help` 덤프에서도 없다.

### README 주장 vs 실제
- README "Observability" 섹션: `logs`, `traces list`, `traces get`, `status`를 최상위 커맨드로 광고
- 실제 설치된 0.11.0 바이너리: `obs show` / `obs list`만 존재
- **문서 드리프트** (npm README는 로드맵/미래 기능을 반영, CLI 런타임은 현재 구현만 반영)

### OpenTelemetry
- `@opentelemetry/*` 여러 패키지 의존 (api, exporter-metrics-otlp-http, otlp-transformer, resources, sdk-metrics)
- Runtime 스키마에 `instrumentation.enableOtel: boolean` (default true)
- `configure --disable-otel` 플래그 존재

---

## 6. 특정 키워드 존재/부재

| 키워드 | 결과 |
|---|---|
| **Firecracker** | `/usr/lib/node_modules/@aws/agentcore/`의 어느 문서·코드에도 없음 |
| **microVM / micro-vm / micro VM** | 없음 |
| **Skills** (AgentCore 기능으로) | 없음. "skill"은 npm 패키지 설명·README 어디에도 등장하지 않음 |
| **CodeZip** | 있음 (build 타입 중 하나) |
| **Container** | 있음 (ARM64 CodeBuild) |
| **ECR / CodeBuild** | 있음 (destroy 및 deploy 설명에 등장) |
| **Session storage** | 있음 (`filesystemConfigurations.sessionStorage.mountPath`) |
| **VPC mode** | 있음 (networkMode PUBLIC|VPC) |

**결론**: 블로그가 "Firecracker microVM 격리"나 "Skills 기능"을 CLI 레벨에서 증명되는 기능인 것처럼 서술했다면, **CLI/npm 패키지 레벨에서는 근거 없음**. AWS 문서/서비스 내부 런타임 구현에 대한 주장이라면 별도 확인 필요(본 리서치 범위 밖).

---

## 7. 블로그 주장별 예비 검증 매트릭스

| 블로그 주장 | 예비 판정 | 근거 |
|---|---|---|
| "3-선언만으로 에이전트 배포" | **부분 참** | name+version만 필수, 하지만 runtime 최소 1개 + entrypoint+codeLocation 필요 -> 실질 4-5 필드 |
| "Sonnet 4.5가 기본 모델" | **참** | README 명시, `us.anthropic.claude-sonnet-4-5-20250514-v1:0` |
| "Strands가 유일한 프레임워크" | **거짓** | 6개 지원(기본값일 뿐). LangChain, CrewAI, GoogleADK, OpenAI, AutoGen 모두 템플릿 존재 |
| "Strands가 기본 프레임워크" | **참** | `--agent-framework`의 default value |
| "Firecracker microVM 사용" | **근거 없음(로컬)** | CLI/npm에 언급 전무. AWS 런타임 구현 주장이면 별도 검증 필요 |
| "Skills 기능 존재" | **거짓** | CLI·README·스키마에 `skill` 키워드 완전 부재 |
| "obs logs/traces 커맨드" | **문서 드리프트** | README는 있다고 하지만 v0.11.0 help에는 `obs show/list`만. 블로그가 README만 근거로 썼다면 실제 동작과 불일치 |
| "CDK + L3 construct 자동 생성" | **참** | `agentcore/cdk/` 디렉터리 + `@aws/agentcore-cdk` 언급 |
| "ECR + CodeBuild로 ARM64 컨테이너" | **참** | deploy help에 "Build ARM64 containers in the cloud with CodeBuild" 명시 |
| "CodeZip (direct code deploy)도 지원" | **참** | build 타입에 CodeZip 존재, deploy help에도 direct_code_deploy 설명 |
| "Multi-protocol (HTTP/MCP/A2A/AGUI)" | **참** | Runtime protocol enum에 4개 값 모두 존재 |
| "VPC 모드 지원" | **참** | `networkMode: VPC`, `configure --vpc --subnets --security-groups` |
| "Memory 4가지 전략" | **참** | SEMANTIC, SUMMARIZATION, USER_PREFERENCE, EPISODIC |
| "Cedar policy 엔진" | **참** | `agentcore policy` 서브커맨드 14개 |

---

## 8. 블로그 검증 시 추가로 할 것

1. `agentcore create --non-interactive --template basic` 실행해서 실제로 생성되는 파일 트리 스냅샷을 README 기대값과 대조
2. 생성된 `agentcore.json` 초기값에 `version`이 무슨 숫자로 들어가는지 확인(1 예상)
3. `agentcore validate` 실행으로 Zod 스키마가 실제로 name/version만 없으면 reject하는지 확인
4. `agentcore obs --help`의 결과와 README 주장 간 차이를 실측으로 기록(블로그에 "문서가 현실보다 앞서감" 주석을 달 수 있음)
5. Firecracker/microVM 주장은 AWS 공식 AgentCore Runtime 문서(블로그/프로덕트 페이지)에서만 확인 가능 — CLI 범위 밖임을 블로그에서 명시
