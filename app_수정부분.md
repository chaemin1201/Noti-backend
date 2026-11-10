# aprofi_backend-NCP_HelloNOTI 에 반영하기 (이 저장소 기준)

기준 파일: `Downloads\aprofi_backend-NCP_HelloNOTI (1).zip` (Python 3.11, gunicorn 워커 4개, 도커 이미지)
이 저장소의 `app/inputdata` 3개 파일(crud, routers, schemas)은 이전에 본 서버 버전과 **한 줄도 다르지 않아서**, 덮어써도 서버에서 사라지는 수정은 없습니다.

## 1. 한 번에 반영: `aprofi_반영본.zip`
저장소 루트에 그대로 풀어 덮어쓰면 됩니다 (경로가 저장소 루트 기준: `app/…`, `requirements.txt`, `Dockerfile`). 27개 파일.

| 파일 | 변경 |
|---|---|
| `app/inputdata/**` | 문제지 업로드 기능 전체로 교체 (23개 파일) |
| `app/main.py` | 2줄 추가 (라우터 연결) |
| `app/database.py` | 1줄 추가 (새 표 3개 등록) |
| `requirements.txt` | 4줄 추가 (패키지) |
| `Dockerfile` | `poppler-utils` 1단어 + LibreOffice 선택 층 |

정확한 줄 단위 변경은 `aprofi_변경내역.diff` 를 보세요 (inputdata 밖의 4개 파일).

## 2. 코드 변경 (3줄)
```diff
 app/main.py
 from app.inputdata.routers import inputdata
+from app.inputdata.intake.router import router as intake_router
 ...
 app.include_router(inputdata.router,     prefix="/api", tags=["inputdata"])
+app.include_router(intake_router,        prefix="/api", tags=["inputdata_intake"])

 app/database.py   (init_db 안, 모델 import 목록 끝)
+    from app.inputdata.intake.models import IntakeJob, IntakeItem, IntakeCapture, ProblemTitleSeq
```

## 3. 빌드 변경 — 이 저장소에 꼭 필요한 부분
이 저장소의 `requirements.txt` 에는 `python-docx`, `openpyxl`, `olefile`, `Pillow` 가 **없습니다** (도커 파일에서 이 패키지들은 코드 실행용 별도 환경(`/opt/runner-py`)에만 설치되고 앱 환경에는 없음). 앱 이미지에는 PDF 도구(poppler)와 LibreOffice 도 없습니다.

| 없으면 | 어떻게 되나 |
|---|---|
| `python-docx` | 워드 업로드 → 422 안내 "서버에 python-docx 패키지가 필요합니다" |
| `openpyxl` | 엑셀 업로드 → 422 안내 |
| `olefile` | 한글(.hwp) 업로드 → 422 안내 |
| `Pillow` | 서버는 정상. 한글 문서의 그림과 원본 캡처 이미지 변환만 빠짐 |
| `poppler-utils` | PDF 업로드 → 422 안내 (pdftotext 없음) |
| LibreOffice | 워드·PPT·한글 원본 캡처만 없음 → 읽은 글로 대신 보여 줌 (PDF 캡처는 poppler 만 있으면 됨) |

- 어느 패키지가 없어도 **서버는 정상으로 뜹니다** (시험으로 확인). 해당 형식을 올렸을 때만 안내가 나갑니다.
- `INSTALL_OFFICE=false` 로 빌드하면 LibreOffice 를 건너뛰어 이미지가 약 500MB 작아집니다.
- 한글 글꼴(`fonts-nanum`)은 이미 설치돼 있어 LibreOffice 캡처에서 한글이 깨지지 않습니다.

## 4. DB
- 새 표 4개(`intake_job`, `intake_item`, `intake_capture`, `problem_title_seq`)는 서버가 시작할 때 `create_all` 로 자동 생성됩니다. 마이그레이션 없음.
- **워커 4개**이므로 제목 번호가 겹치지 않게 DB 인덱스를 권장합니다 (번호 자체는 카운터가 겹치지 않게 주고, 이 인덱스는 마지막 안전장치). DB 에서 직접 실행:
```sql
SELECT title, count(*) FROM problem WHERE title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$' GROUP BY 1 HAVING count(*) > 1;   -- 먼저 확인 (결과가 없어야 함)
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_problem_title_code ON problem (title) WHERE title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$';
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_problem_maker_content_hash ON problem (maker_id, temporary_field_str_2) WHERE is_deleted = false AND temporary_field_str_2 IS NOT NULL;
```

## 5. 환경변수
- AI 키: 이 저장소의 `docker-compose-prod.yml` 이 `.env` 로 `OPENAI_API_KEY` 를 이미 넘깁니다. 업로드 기능은 같은 키를 자동으로 찾아 씁니다 (기본 모델 `gpt-4.1-mini`). 따로 추가할 변수는 없습니다.
- 선택: `INTAKE_CONCURRENCY`(기본 20), `INTAKE_DAILY_JOBS`(30), `INTAKE_DAILY_PROBLEMS`(500) 등은 `inputdata_구조설명서.pdf` 5절.

## 6. 워커 4개에서 알아 둘 점
- 처리는 업로드를 받은 워커 안에서 백그라운드로 돕니다. 서버를 재시작하면 처리 중이던 작업은 `processing` 에서 멈추고, 몇 분 뒤 `resume` 으로 이어서 처리할 수 있습니다 (진행 표시가 DB 에 있어 다른 워커에서도 판별됨).
- 작업 동시 처리 수(`INTAKE_CONCURRENT_JOBS=2`)와 AI 동시 호출 수는 워커마다 따로 셉니다. AI 서비스가 429 를 자주 내면 `INTAKE_CONCURRENCY` 를 낮추세요.
- Python 3.11 에서 문법 호환을 확인했습니다 (3.12 전용 문법 없음).

## 7. 확인하지 못한 것
- 도커 이미지 빌드(이 PC 에는 도커가 없음): `Dockerfile` 의 LibreOffice 층은 문법만 확인
- 실제 Postgres·실제 AI·실제 파일로 처리한 결과
- 이 저장소 코드 위에서 전체 시험 46개 중 45개 통과. 실패 1개는 위 4번의 `uq_problem_title_code` 인덱스가 없어서 생기는 차이입니다.
- nginx(이 저장소)는 `/media` 만 처리하고 API 는 거치지 않습니다. API 앞에 다른 프록시(로드밸런서·Cloudflare 등)가 있다면 **업로드 크기 제한**(최대 파일 5개 × 20MB)을 확인하세요.

## 8. 반영 순서
1. 백업: 서버의 `app/inputdata`, `main.py`, `database.py`, `requirements.txt`, `Dockerfile`
2. `aprofi_반영본.zip` 을 저장소 루트에 풀어 덮어쓰기
3. 이미지 다시 빌드 → 개발 서버에 배포
4. `/docs` 에 `inputdata_intake` 태그가 보이는지 확인, 파일 하나(`문제지_샘플/객관식_테스트.docx`)를 올려 결과 확인
5. 문제 없으면 운영 배포, 있으면 백업으로 복구

## 9. 테스트 서버에서 쓸 때

**임시 작업 데이터**: 업로드·처리 중에 쌓이는 `intake_job` · `intake_item` · `intake_capture` 는 최종 저장 내용이 아니라 **작업용 데이터**입니다. 등록된 문제는 `problem` 표에 따로 저장되고, 작업 데이터를 지워도 문제는 그대로입니다.
- 기본 **30일 뒤 자동 삭제** (`INTAKE_JOB_DAYS`, 0 이면 안 지움). 새 작업을 올릴 때 함께 정리합니다. 처리 중인 작업은 지우지 않습니다.
- 바로 지우려면 `DELETE /api/intake/jobs/{job_id}` (본인 작업만, 처리 중이면 409).
- 테스트가 끝난 뒤 한 번에 비우려면 DB 에서 (등록된 문제는 영향 없음):
```sql
DELETE FROM intake_capture; DELETE FROM intake_item; DELETE FROM intake_job;
```

**한꺼번에 등록**: 문제를 하나씩 등록하지 않고 `POST /api/intake/jobs/{id}/approve` 한 번으로 여러 개를 등록합니다. 고친 문제는 `edits` 로 같이 보내면 수정 저장 + 재검사 + 등록이 한 번의 호출에서 끝납니다 (문제 100개 중 20개를 고쳐도 호출 1번). 자세한 방법은 `프론트_전달문서_최신.docx` 3-6절.

**AI 호출량** (실제 AI 로 문서 8개·문제 106개를 처리했을 때): AI 호출 약 190번(문제당 평균 1.8번), 입력 토큰 약 75만(그중 85%는 캐시), 출력 약 8만. 테스트 서버에서 줄이려면 환경변수로:

| 설정 | 효과 |
|---|---|
| `INTAKE_FILL_META=off` | 부제목·문제의도를 채우는 짧은 호출(약 100번)을 건너뜀. 부제목은 원래 이름만 쓰고 AI 키워드는 안 채움 |
| `INTAKE_REPAIR_ROUNDS=0` | 검사에서 막힌 결과를 AI 가 다시 쓰는 호출을 건너뜀 |
| `INTAKE_CONCURRENCY=5` | 동시에 보내는 AI 호출 수를 낮춤 (호출 수는 같고 한꺼번에 몰리는 것을 줄임, 처리 시간은 늘어남) |
| `INTAKE_DAILY_JOBS` · `INTAKE_DAILY_PROBLEMS` | 하루에 올릴 수 있는 작업·문제 수 상한 (기본 30 · 500) |
| `INTAKE_CAPTURE=off` | 원본 캡처(문서 변환)를 끔. LibreOffice 가 없는 테스트 서버에 맞음 |
