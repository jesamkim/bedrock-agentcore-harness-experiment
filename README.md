# Bedrock AgentCore Managed Harness 실험 (Preview, 2026-04)

<div align="center">

**AWS Bedrock AgentCore Runtime + Strands Agents 실전 검증 하네스**

`direct_code_deploy` 27.8초 배포 · 세션 격리 행동 검증 · CloudWatch Observability 자동 수집 실측

</div>

---

## 이 레포는 무엇인가

2026년 4월 22일 AWS가 발표한 [Bedrock AgentCore Managed Harness (Preview)](https://aws.amazon.com/blogs/machine-learning/get-to-your-first-working-agent-in-minutes-announcing-new-features-in-amazon-bedrock-agentcore/)를 분석한 블로그 글의 **주장을 실측으로 교차 검증**하기 위해 만든 실험 하네스입니다.

Managed Harness 자체(`agentcore create/dev/deploy` CLI 플로우, `harness.json` 스키마)는 아직 프리뷰라 재현이 제한적이므로, 이 실험은 그 아래 깔린 **AgentCore Runtime (2025-10-13 GA) + Strands Agents** 조합을 직접 배포·호출·정리하면서 다음 7개 주장을 점검합니다.

1. **3-선언 배포** (model + systemPrompt + tools) → **부분 사실** (Strands `Agent()` 생성자 한정)
2. **세션 격리 microVM** → **사실** (행동 수준 검증)
3. **Firecracker 사용** → **미확인** (공식 문서/응답 헤더에 힌트 없음)
4. **Strands가 내부 엔진** → **거짓** (프레임워크 중립, LangGraph/CrewAI 등 1급 지원)
5. **프리뷰 기능** → **거짓** (AgentCore Runtime은 2025-10-13 GA, 9개 리전 지원)
6. **관측성 내장** → **사실** (네임스페이스 `AWS/Bedrock-AgentCore`, 메트릭 8종 자동 수집)
7. **툴 호출 동작** → **사실** (42, 2122 계산 확인 / 단, Strands 1.29 `tool_uses` 메타데이터 빈 값 이슈)

전체 검증 결과와 블로그 수정 제안은 [`blog-corrections.md`](./blog-corrections.md), [`results.md`](./results.md), [`research-findings.md`](./research-findings.md) 참조.

관련 블로그: **[Bedrock AgentCore Managed Harness 심층 해부](https://jesamkim.github.io/ai-tech-blog/posts/2026-04-26-bedrock-agentcore-managed-harness-deep-dive/)**

---

## 실측 수치 요약

| 항목 | 값 | 비고 |
|---|---|---|
| **배포 시간 (direct_code_deploy)** | **27.8초** | configure 0.2s + launch 27.5s + poll 0.1s |
| Cold invoke latency | 6.57초 | 서버 핸들러 3.55초 |
| Warm invoke latency | 3.27초 | 같은 `runtimeSessionId` = warm microVM |
| 패키지 크기 | 59.26 MB | dependencies + main.py |
| `idleRuntimeSessionTimeout` | 900초 (15분) | 자동 세션 종료 |
| `maxLifetime` | 28,800초 (8시간) | 세션 최대 수명 |
| 메트릭 네임스페이스 | `AWS/Bedrock-AgentCore` | **하이픈 주의** |
| 로그 그룹 패턴 | `/aws/bedrock-agentcore/runtimes/<RUNTIME-ID>-DEFAULT` | 자동 생성 |

### 가장 흥미로운 발견

`direct_code_deploy` 모드는 **CodeBuild/ECR을 사용하지 않습니다**. 로컬 `uv`로 `aarch64-manylinux2014` 크로스 컴파일 → 59 MB ZIP → S3 업로드 구조입니다. 그래서 배포가 블로그의 "<5분" 주장과 달리 27초대에 끝납니다. 런타임 자체는 여전히 ARM64 Graviton에서 실행됩니다.

---

## 아키텍처

```
┌─────────────────────────────┐
│  Client (local machine)     │
│  ├─ uv (cross-compile)      │
│  └─ bedrock-agentcore SDK   │
└──────────┬──────────────────┘
           │ deploy (ZIP 59MB)
           ▼
┌─────────────────────────────┐
│  S3 codebuild-sources/*     │ ← direct_code_deploy 모드
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  AgentCore Runtime          │
│  ├─ microVM (per session)   │
│  ├─ ARM64 Graviton          │
│  └─ BedrockAgentCoreApp     │
│     └─ Strands Agent        │
│        ├─ Claude Sonnet 4.5 │
│        └─ @tool functions   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  CloudWatch                 │
│  ├─ /aws/bedrock-agentcore/ │
│  └─ AWS/Bedrock-AgentCore   │
│     (Latency, Sessions,     │
│      Invocations, ...)      │
└─────────────────────────────┘
```

---

## 사전 준비

- **Python 3.10+**
- **`uv`** — `direct_code_deploy`가 `aarch64-manylinux2014` 크로스 컴파일에 사용합니다. 없으면 배포 스크립트가 `RuntimeError: uv is required for direct_code_deploy deployment` 에러를 냅니다.
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **AWS 계정** — Bedrock + AgentCore 권한, `us-west-2` 리전
- **모델 액세스 활성화** — `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (날짜 포함 모델 ID 필수, 짧은 형식 `...claude-sonnet-4-5-v1:0`은 동작하지 않음)

### AWS 자격 증명

스크립트는 기본 프로파일을 읽도록 설정되어 있습니다(`os.environ.setdefault("AWS_PROFILE", "default")`). 다른 프로파일을 쓰려면 실행 시 환경 변수로 덮어쓰세요.

```bash
# 옵션 1: 기본 프로파일
aws configure

# 옵션 2: 전용 프로파일
aws configure --profile my-agentcore
export AWS_PROFILE=my-agentcore
export AWS_REGION=us-west-2
```

필요한 IAM 권한 (최소):

- `bedrock-agentcore-control:*` (Runtime 생성/삭제)
- `bedrock-agentcore:InvokeAgentRuntime`
- `bedrock:InvokeModel` (Claude Sonnet 4.5)
- `iam:CreateRole`, `PutRolePolicy`, `PassRole`, `GetRole`, `DeleteRole`
- `s3:PutObject`, `GetObject`, `DeleteObject` (`bedrock-agentcore-codebuild-sources-*` 버킷)
- `codebuild:*`, `ecr:*` (scaffold 생성만, 빌드 job은 돌지 않음)
- `logs:*` (CloudWatch 로그 그룹)

---

## 실행 방법

```bash
git clone https://github.com/jesamkim/bedrock-agentcore-harness-experiment.git
cd bedrock-agentcore-harness-experiment

pip install -r requirements.txt

# 1. 배포 (configure + launch + poll READY, 약 28초)
python deploy_agent.py

# 2. Cold vs Warm 레이턴시 측정
python invoke_session.py

# 3. 툴 호출 검증 (add_numbers, get_current_time)
python test_tools.py

# 4. 세션 격리 검증 (동시 2세션, 비밀 번호 교차 오염 없는지)
python test_isolation.py

# 5. Observability 검증 (로그 그룹 + 메트릭 네임스페이스)
python check_observability.py

# 6. 정리 (런타임 + IAM 롤 + S3 + CodeBuild + ECR 모두 삭제)
python cleanup.py
```

각 스크립트는 자신의 결과 JSON을 남기며, 뒤따르는 스크립트는 `deploy-log.json`에서 런타임 ARN을 읽습니다.

---

## 파일 구성

| 파일 | 용도 |
|------|------|
| `main.py` | 에이전트 엔트리포인트. `BedrockAgentCoreApp` + Strands `Agent()` + 2개 `@tool`. |
| `deploy_agent.py` | `bedrock_agentcore_starter_toolkit.Runtime`으로 configure + launch + poll READY. |
| `invoke_session.py` | 같은 세션에서 2회 invoke로 cold/warm 측정. |
| `test_tools.py` | 툴 호출을 유도하는 프롬프트로 `add_numbers`/`get_current_time` 검증. |
| `test_isolation.py` | 스레드 2개로 동시 세션 2개를 돌려 비밀 번호 교차 오염 검사. |
| `check_observability.py` | `/aws/bedrock-agentcore/runtimes/*` 로그 그룹 + 4개 후보 네임스페이스 메트릭 조회. |
| `cleanup.py` | 런타임 + IAM 롤 + S3 + CodeBuild 프로젝트 + ECR 레포 + 로그 그룹 일괄 삭제. |
| `requirements.txt` | `bedrock-agentcore==1.2.0`, `bedrock-agentcore-starter-toolkit==0.2.6`, `strands-agents==1.29.0`. |
| [`research-findings.md`](./research-findings.md) | Phase 1 문헌 조사 결과 (SDK 구조, API 표면, 프레임워크 중립성). |
| [`results.md`](./results.md) | Phase 3 실측 결과 상세 리포트 (14 KB). |
| [`blog-corrections.md`](./blog-corrections.md) | 블로그 12개 정정 항목. |
| `artifacts/` | 실제 실험 run의 JSON 원본 (account ID redact 완료). |

---

## Exit Codes

| 코드 | 의미 |
|------|------|
| 0 | 성공 |
| 2 | `configure()` 실패 |
| 3 | `launch()` 실패 |
| 4 | launch 후 ARN/ID 누락 |
| 5 | 타임아웃 내에 READY 도달 실패 |
| 6 | invoke 응답이 200이 아님 |
| 7 | 툴 검증 실패 |
| 8 | 세션 간 정보 오염 감지 |
| 9 | observability 단계에서 `deploy-log.json` agent_id 누락 |
| 10 | cleanup 후에도 런타임 잔존 |

---

## 주요 주의사항

- **모델 ID는 날짜 포함 형식 필수**: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` ✅ / `us.anthropic.claude-sonnet-4-5-v1:0` ❌
- **메모리 모드는 `NO_MEMORY`**: 같은 세션 안에서도 턴 간 컨텍스트 보장 없음. 이 실험은 세션 격리·툴 호출·하네스 구조 검증이지 장기 컨텍스트 테스트가 아닙니다.
- **test_isolation.py 성공 조건**: 세션 간 정보 교차 오염이 없으면 통과. 에이전트가 "기억 못 한다"고 답해도 통과입니다. 실패 조건은 다른 세션의 비밀 번호를 언급하는 경우뿐.
- **`direct_code_deploy`는 CodeBuild/ECR 미사용**: 일부 문서/블로그가 암시하는 것과 달리 CodeBuild job은 돌지 않습니다. S3 ZIP → Runtime 직배포 구조이며, 버킷 이름에만 `codebuild-sources`가 남아 있습니다.
- **CloudWatch 메트릭 네임스페이스**: `AWS/Bedrock-AgentCore`(하이픈)입니다. `AWS/BedrockAgentCore`로 찾으면 안 나옵니다.

---

## 정리 (중요)

배포된 런타임은 **시간당 비용이 발생**합니다. 실험이 끝나면 반드시 `cleanup.py`를 돌려 전체 리소스를 제거하세요. 스크립트는 다음을 삭제합니다.

- Agent Runtime (`harness_test_*`)
- IAM 실행 롤 (`AmazonBedrockAgentCoreSDKRuntime-us-west-2-*`)
- S3 업로드 prefix (`s3://bedrock-agentcore-codebuild-sources-<acct>-<region>/harness_test_*/`)
- CodeBuild 프로젝트 (scaffold만, 실제 빌드 기록 없음)
- ECR 레포지토리 (scaffold만)
- CloudWatch 로그 그룹

실제 실험 후 검증: Agent Runtime 0개, IAM 롤 0개, S3 prefix 0개, 로그 그룹 0개 — 완전 정리 확인 완료.

---

## 참고 자료

- 블로그: [Bedrock AgentCore Managed Harness 심층 해부](https://jesamkim.github.io/ai-tech-blog/posts/2026-04-26-bedrock-agentcore-managed-harness-deep-dive/)
- AWS Machine Learning Blog: [Get to your first working agent in minutes](https://aws.amazon.com/blogs/machine-learning/get-to-your-first-working-agent-in-minutes-announcing-new-features-in-amazon-bedrock-agentcore/)
- [AWS What's New: AgentCore new features](https://aws.amazon.com/about-aws/whats-new/2026/04/agentcore-new-features-to-build-agents-faster/)
- [AgentCore CLI GitHub](https://github.com/aws/agentcore-cli)
- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
- [AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)

---

## License

MIT

---

*검증일: 2026-04-26 · SDK: bedrock-agentcore 1.2.0, starter-toolkit 0.2.6, strands-agents 1.29.0 · 리전: us-west-2*
