# Noti 로컬 테스트 키트

## 1. 설치 위치
`Noti backend` 폴더(안에 `inputdata`, `models`, `test.py`가 있는 곳) 안에 이 `noti_test` 폴더를 통째로 넣습니다.

```
Noti backend\
  inputdata\inputdata\...        (기존)
  models\models\...              (기존)
  noti_test\                     (이 폴더)
```
`app` 패키지가 없어도 됩니다. 테스트가 `models\models`, `inputdata\inputdata` 폴더를 `app.*` 경로에 자동으로 연결하고,
없는 `app.database`, `app.security`는 임시로 대신 만듭니다. (실제 프로젝트에 `app`이 있으면 그것을 씁니다.)

## 2. 설치와 실행 (Windows PowerShell)
```
pip install fastapi sqlalchemy pydantic aiosqlite httpx
cd "C:\project\Noti backend\noti_test"
python run_all_tests.py
```
결과는 통과 / 실패 / 건너뜀으로 나옵니다. **건너뜀은 실패가 아닙니다.** 수정본이 필요한 테스트를 아직 적용하지 않았다는 뜻입니다.

## 3. 수정본 적용 (apply 폴더)
아래처럼 복사하면 건너뜀이 사라지고 모든 테스트가 실행됩니다.

| apply 폴더의 파일 | 복사할 위치 (Noti backend 기준) |
|---|---|
| schemas.py | inputdata\inputdata\schemas.py (덮어쓰기) |
| dedupe.py | inputdata\inputdata\dedupe.py (새 파일) |
| crud_inputdata.py | inputdata\inputdata\crud\inputdata.py (덮어쓰기) |
| router_inputdata.py | inputdata\inputdata\routers\inputdata.py (덮어쓰기) |

복사 전에 원본을 백업하세요. 변경 내용은 apply 폴더가 아니라 대화에서 드린 schemas.diff, dedupe.diff로 볼 수 있습니다.

## 4. 이 키트가 테스트하는 것
| 테스트 | 대상 | 종류 |
|---|---|---|
| test_schemas.py | 입력 스키마(제목·설명 검증, 그래픽 문제, 정규화) | 코드 |
| test_local_sqlite.py | 실제 모델·crud·라우터를 실제 DB(SQLite)에 연결해 등록·중복 방지 | 코드 |
| test_inputdata_flow.py | 중복 방지 흐름(가짜 DB) | 코드 |
| test_register.py | 등록 스크립트 register.py → 라우터 | 코드 |
| protocol_check.py + jsonl | 검사기가 맞는 것은 통과, 틀린 것은 차단하는지 | 검사기 |
| run_ai_tests.py --mock | AI 테스트 도구 자체 | 도구 |

위 테스트는 모두 **코드를 테스트**합니다. 프롬프트를 테스트하지는 않습니다.

## 5. 프롬프트 테스트 (AI 필요, 별도)
프롬프트가 규칙대로 동작하는지는 실제 AI의 출력을 채점해야 알 수 있습니다. **Google(Gemini) 키로도 됩니다.**

### 키 설정: .env 파일 (권장)
`.env.example`을 복사해 `.env`로 만들고 값을 채웁니다. (이 폴더, 상위 폴더 2단계까지 `.env`를 찾습니다.)
```
copy .env.example .env
notepad .env
```
```
GEMINI_API_KEY=발급받은키
LLM_MODEL=모델이름          # 모르면 아래 "모델 이름 찾기"로 자동으로 찾을 수 있습니다
```
- 환경변수로 설정해도 됩니다. PowerShell: `$env:GEMINI_API_KEY="키"` / `$env:LLM_MODEL="모델이름"`
- Anthropic 키를 쓰려면 `ANTHROPIC_API_KEY=키`. 키가 하나뿐이면 자동으로 선택하고, 둘 다 있으면 Google이 우선입니다 (`--provider anthropic`으로 지정 가능).
- **`.env`는 git에 올리지 마세요.** `.gitignore`에 `.env` 한 줄을 추가하세요. 키 값은 화면에 출력되지 않습니다.

### 자주 나오는 오류
| 메시지 | 원인과 해결 |
|---|---|
| `HTTP 404 ... no longer available to new users` | 그 모델은 이 프로젝트에서 쓸 수 없습니다. |
| `HTTP 400/403 ... API key` | 키가 잘못됐습니다. AI Studio에서 키를 다시 복사해 `.env`의 `GEMINI_API_KEY`를 확인하세요 |
| `HTTP 503 ... high demand` | 구글 서버가 일시적으로 혼잡합니다(코드 문제가 아닙니다). 도구가 3→8→20→45초 간격으로 자동 재시도하고, 그래도 안 되면 "호출 실패"로 표시합니다. 잠시 뒤 다시 하거나 아래 대체 모델을 설정하세요 |
| `HTTP 429` | 호출 한도 초과입니다. 서버가 알려 준 시간만큼 기다렸다가 다시 시도합니다. 계속되면 `--runs 1`, `--only`로 줄이세요. 한도가 0이라고 나오면 모델을 바꾸세요 |
키·모델 설정 오류는 다시 시도해도 같은 결과이므로 테스트가 첫 호출에서 바로 멈춥니다.
호출 실패(혼잡·한도)는 프롬프트 규칙 위반이 아니므로 통과율에서 빼고 따로 세어 보여 줍니다.

### 실행
```
python run_ai_tests.py --api --runs 3
```
- 같은 입력을 3번씩 보내 결과가 일정한지 봅니다. 호출이 늘어나므로 무료 등급은 속도 제한(429)에 걸릴 수 있고, 걸리면 자동으로 잠시 기다렸다가 다시 시도합니다.
- 처음에는 `--only T1,T3`처럼 일부만, `--runs 1`로 시작하세요.
- 키가 없으면 채팅에서 프롬프트와 `test_pack.jsonl`의 입력을 하나씩 넣어 응답을 받고, `{"test":"T1","text":"응답 전체"}` 형식의 줄로 저장해 `python run_ai_tests.py --from-file 파일.jsonl`로 채점합니다.

### 모델이 달라도 되는가
프롬프트는 특정 AI에 맞춘 것이 아니라 규칙과 예시로 쓴 일반 지시문입니다. 다만 모델마다 JSON 한 줄 형식을 지키는 정도와 규칙 준수가 다릅니다.
테스트가 바로 그것을 재는 도구이므로, 쓰실 모델로 직접 돌려 통과율을 확인하세요. 코드 블록(```)으로 감싸는 정도는 자동으로 무시됩니다.

## 6. 한계
- SQLite 시험이라 Postgres 전용 동작(ARRAY, JSONB, enum)은 검증하지 못합니다. 실제 Postgres에서는
  `python test_local_sqlite.py --db postgresql+asyncpg://사용자:비밀번호@localhost/테스트DB --users 실제사용자ID1,실제사용자ID2`
  (테스트 전용 DB를 쓰세요. 시작할 때 테이블을 지우고 다시 만듭니다.)
- 실제 서버, 인증, 플랫폼 채점 동작은 이 키트의 범위 밖입니다.
