#!/usr/bin/env python3
"""noti_test 폴더의 로컬 테스트를 모두 실행하고 요약한다. (AI·서버 접속 불필요)

실행:  cd "C:\\project\\Noti backend\\noti_test"  →  python run_all_tests.py
- 수정본이 적용되지 않은 기능이 필요한 테스트는 실패가 아니라 '건너뜀'으로 표시한다.
- AI 가 프롬프트대로 하는지 보는 테스트는 별도다: python run_ai_tests.py --api ... (README.md 참고)
"""
import importlib.util, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import _bootstrap
_bootstrap.setup()

need_pkg = {"pydantic": "pydantic", "sqlalchemy": "sqlalchemy", "fastapi": "fastapi", "aiosqlite": "aiosqlite", "httpx": "httpx"}
missing = [p for p in need_pkg if importlib.util.find_spec(p) is None]
if missing:
    print("설치가 필요한 패키지:", ", ".join(missing), "\n  pip install " + " ".join(missing) + "\n")

F = _bootstrap.features() if not {"pydantic", "sqlalchemy", "fastapi"} & set(missing) else {}
P = ["중복 방지", "그래픽 문제 허용"]
# (이름, 명령, 기대 종료 코드, 필요한 수정본 기능, 필요한 패키지)
TESTS = [
    ("스키마 검증", ["test_schemas.py"], 0, [], []),
    ("실제 DB 등록 (SQLite)", ["test_local_sqlite.py"], 0, [], ["aiosqlite"]),
    ("중복 방지 흐름 (가짜 DB)", ["test_inputdata_flow.py"], 0, P, []),
    ("등록 스크립트", ["test_register.py"], 0, P, ["httpx"]),
    ("검사기: 정상 사례", ["protocol_check.py", "golden_cases.jsonl"], 0, ["그래픽 문제 허용"], []),
    ("검사기: 틀린 사례는 모두 차단", ["protocol_check.py", "bad_cases.jsonl"], 0, [], []),
    ("검사기: 프롬프트 예시", ["protocol_check.py", "prompt_examples.jsonl"], 0, [], []),
    ("AI 테스트 도구: 좋은 모의 AI는 통과", ["run_ai_tests.py", "--mock", "good"], 0, ["그래픽 문제 허용"], []),
    ("AI 테스트 도구: 나쁜 모의 AI는 실패", ["run_ai_tests.py", "--mock", "bad"], 1, [], []),
    ("한글 읽기·자동 번호 (합성 데이터)", ["test_hwp_text.py"], 0, [], []),
    ("프롬프트 점검 (규칙 표지·예시·중복·길이)", ["test_prompt_lint.py", "--max-chars", "22000"], 0, [], []),
    ("엑셀 열 인식·미인식 열 경고", ["test_xlsx_columns.py"], 0, [], ["aiosqlite", "httpx"]),
    ("엑셀 값 변경 감지 · AI 출력 JSON 복구", ["test_fidelity.py"], 0, [], []),
    ("마크다운 강조 검사 (코드의 ** 는 제외)", ["test_md_check.py"], 0, [], []),
    ("설명 저장 형식 (부제목·문제의도·설명 JSON)", ["test_desc_pack.py"], 0, [], []),
    ("PDF 읽기·번호 제목 나누기 (한글 인코딩)", ["test_pdf_reading.py"], 0, [], []),
    ("서술형 모범 답안 직접 입력 (needs_input)", ["test_subjective.py"], 0, [], []),
    ("문서 속 그림을 AI 에 보내기 (워드·한글·요청)", ["test_images.py"], 0, [], []),
    ("Java·JavaScript 서버 실행 검증", ["test_run_langs.py"], 0, [], []),
    ("PPT 읽기 · 여러 형식 문제지 한 번에 (혼합)", ["test_pptx_mixed.py"], 0, [], []),
    ("입력 종류별 프롬프트 줄이기", ["test_prompt_trim.py"], 0, [], []),
    ("완성된 엑셀 행은 짧은 호출로 (토큰 절약)", ["test_light_rows.py"], 0, [], ["aiosqlite", "httpx"]),
    ("짧은 문제 묶어서 호출 (INTAKE_BATCH)", ["test_batch.py"], 0, [], ["aiosqlite", "httpx"]),
    ("OpenAI 호환 AI 호출 (다른 서비스의 API)", ["test_llm_openai.py"], 0, [], []),
    ("동시 처리 · 그림 줄여 다시 보내기 (가짜 AI)", ["test_concurrency.py"], 0, [], []),
    ("AI 출력 형식 실수 바로잡기 (모델이 달라도)", ["test_normalize.py"], 0, [], []),
    ("멈춘 AI 호출 다시 보내기 (헤징)", ["test_hedge.py"], 0, [], []),
    ("등록 제목 코드 · 부제목 이동", ["test_title_code.py"], 0, [], []),
    ("승인 화면 API (수정 후 재검사 · 원본 보기 · 그림 주소)", ["test_item_edit.py"], 0, [], []),
    ("조건 추천 (걸러내기 + API)", ["test_suggest.py"], 0, [], []),
    ("원본 캡처 (쪽 짝짓기 · 저장 · 보관 기간)", ["test_capture.py"], 0, [], []),
    ("한꺼번에 등록 · 임시 작업 데이터 정리", ["test_bulk_register.py"], 0, [], []),
    ("정답 코드 실행 출력으로 기대 출력 채우기", ["test_exec_fill.py"], 0, [], []),
    ("막힐 AI 결과를 이유와 함께 돌려보내 고쳐 쓰기", ["test_repair.py"], 0, [], []),
    ("업로드·코드 실행 보안 (압축 폭탄, 위험 호출, 그림 폭탄)", ["test_security.py"], 0, [], []),
    ("텍스트 인코딩·제목 모양, DB(SQLite) 읽기", ["test_formats_new.py"], 0, [], []),
    ("스캔 PDF · 구형 .ppt 읽기", ["test_scan_ppt.py"], 0, [], []),
    ("옛 서버 이름과의 호환 (덮어써도 오류 없음)", ["test_compat.py"], 0, [], []),
    ("실제 서버 API 호출 도구 (모의 서버)", ["test_real_server_client.py"], 0, [], []),
    ("AI 사용 보안 (개인정보 지우기, 하루 한도)", ["test_ai_security.py"], 0, [], []),
    ("부제목·문제의도 채우기 (짧은 호출)", ["test_meta_fill.py"], 0, [], []),
    ("비어 있는 제공 코드·정답 코드 채우기", ["test_code_fill.py"], 0, [], []),
    ("새 형식 업로드 (DB·텍스트·PPT) 전체 흐름", ["test_upload_formats.py"], 0, [], []),
    ("입력값 섞임 검사 (기대 출력)", ["test_echo_check.py"], 0, [], []),
    ("자동 등록 정책 (보통)", ["test_policy.py"], 0, [], []),
    ("사후 점검 표시 (AI 가 푼 정답)", ["test_audit.py"], 0, [], ["aiosqlite", "httpx"]),
    ("실행 격리 점검 (모의 + 리눅스에서는 실제)", ["check_exec_isolation.py"], 0, [], []),
    ("업로드 기능(intake) 흐름 (가짜 AI)", ["test_intake_api.py"], 0, ["문제지 업로드 기능"], ["aiosqlite", "httpx"]),
]
env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
rows, bad = [], False
for name, cmd, want, needs, pkgs in TESTS:
    miss_p = [p for p in pkgs if p in missing]; miss_f = [n for n in needs if not F.get(n)]
    if miss_p: rows.append((name, "건너뜀", f"패키지 필요: {', '.join(miss_p)}")); continue
    if miss_f: rows.append((name, "건너뜀", f"수정본 미적용: {', '.join(miss_f)}")); continue
    r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l for l in out.splitlines() if l.strip()]
    summ = next((l.strip() for l in reversed(lines) if l.strip().startswith(("결과", "합계"))), lines[-1].strip() if lines else "")
    if r.returncode == 2: rows.append((name, "건너뜀", summ[:90])); continue
    ok = r.returncode == want
    rows.append((name, "통과" if ok else "실패", summ[:90]))
    if not ok:
        bad = True
        print(f"--- {name}: 실패 (종료 코드 {r.returncode}, 기대 {want}) ---"); print("\n".join(lines[-14:])); print()
print(f"{'테스트':<34}{'결과':<6}요약")
for n, st, s in rows: print(f"{n:<34}{st:<6}{s}")
sk = [r for r in rows if r[1] == "건너뜀"]
print(f"\n통과 {sum(1 for r in rows if r[1] == '통과')} · 실패 {sum(1 for r in rows if r[1] == '실패')} · 건너뜀 {len(sk)}")
if sk and F and not all(F.values()): print("수정본이 적용되지 않은 기능:", ", ".join(k for k, v in F.items() if not v), "→ apply 폴더의 파일을 복사하세요 (README.md)")
sys.exit(1 if bad else 0)
