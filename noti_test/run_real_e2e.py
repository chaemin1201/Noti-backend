"""3단계: 실제 문제지 파일로 끝까지 (업로드 → 실제 AI → 검사 → 승인 → 등록). 등록은 임시 SQLite(메모리)라서 실제 DB 는 건드리지 않는다.

    python run_real_e2e.py --files "문제지 폴더" [--model 모델이름] [--rows 5] [--out 결과.json] [--hwp 파일.hwp|파일.hwpx]

- 폴더의 엑셀 1개 + cpp_week06*.docx(과제·풀이) 를 올린다. --hwp 를 주면 엑셀·워드 대신 그 한글 파일 하나만 올린다(원본 단독 경로).
- AI 는 실제로 부른다(.env 의 키). 호출 횟수 = 문제 수(+ 재시도). 정답 코드 실행 검증은 켜지 않는다(AI 가 쓴 코드를 이 PC 에서 돌리지 않음).
- 결과는 화면에 요약하고, 전체 내용은 --out JSON 으로 저장한다(키는 저장하지 않음)."""
import argparse, asyncio, glob, io, json, os, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
ap = argparse.ArgumentParser()
ap.add_argument("--files", default=os.environ.get("INTAKE_TEST_FILES", "")); ap.add_argument("--model"); ap.add_argument("--rows", type=int, default=5)
ap.add_argument("--out", default="e2e_result.json"); ap.add_argument("--hwp"); ap.add_argument("--upload", nargs="+", help="이 파일들을 한 작업으로 올린다(형식 섞어서 최대 5개). 엑셀은 --rows 행만 남긴다 (--rows 0 이면 전부)"); ap.add_argument("--xlsx", help="이 엑셀(또는 CSV) 하나만 올린다"); ap.add_argument("--wait", type=int, default=900)
args = ap.parse_args()
import logging
logging.basicConfig(level=logging.WARNING, format="   [로그] %(message)s")
logging.getLogger("app.inputdata.intake.service").setLevel(logging.INFO)      # 문제별 AI 호출 시간·토큰과 작업 요약
os.environ["INTAKE_MAX_FILES"] = "30" if not args.upload else os.environ.get("INTAKE_MAX_FILES", "5")      # --upload 는 서버 기본(5개)을 따르되 시험할 때는 환경변수 INTAKE_MAX_FILES 로 늘릴 수 있다
if args.model: os.environ["LLM_MODEL"] = args.model
os.environ.setdefault("LLM_FALLBACK_MODEL", "")                 # 응답 없는 대체 모델을 기다리지 않는다
import httpx, openpyxl
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem
from app.inputdata.intake import router as intake_router, service, config

ENGINE = None
MIME = {".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".txt": "text/plain", ".db": "application/octet-stream", ".csv": "text/csv"}


def small_xlsx(src, n_rows, extra_rows=()):
    wb = openpyxl.load_workbook(src); ws = wb.active
    keep = set(range(1, 5)) | set(range(5, 5 + n_rows)) | set(extra_rows)
    for r in range(ws.max_row, 0, -1):
        if r not in keep: ws.delete_rows(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def brief(it):
    p = it.get("payload") or {}; rv = it.get("review") or {}
    return {"id": it["result_id"], "status": it["status"], "type": p.get("problemType"), "title": p.get("title"),
            "tests": len(p.get("test_cases") or []), "conds": len(p.get("problem_condition") or []),
            "code_lang": [c.get("language") for c in (p.get("reference_codes") or [])],
            "확인필요": rv.get("확인필요") or [], "참고": rv.get("참고") or [], "조언수": len(rv.get("조언") or []), "보류사유": rv.get("보류사유"),
            "check_fails": it.get("check_fails") or [], "approval_reasons": it.get("approval_reasons") or [], "error": it.get("error")}


async def main():
    global ENGINE
    _tmp = os.path.join(os.environ.get("TEMP", "."), "noti_e2e_tmp.db")
    if os.path.exists(_tmp): os.remove(_tmp)                       # 이전 실행의 임시 DB 를 지우고 새로 시작 (동시 처리 시 메모리 DB 는 연결마다 비어 있어서 파일 DB 를 쓴다)
    engine = ENGINE = create_async_engine("sqlite+aiosqlite:///" + os.path.join(os.environ.get("TEMP", "."), "noti_e2e_tmp.db").replace(chr(92), "/"), connect_args={"timeout": 30})
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120)
    print(f"실행 검증(서버에서 정답 코드 실행): {'켜짐' if config.exec_enabled() else '꺼짐'} | 모델: {os.environ.get('LLM_MODEL') or '(.env)'}")

    if args.upload:
        files = []
        for u in args.upload:
            ext = os.path.splitext(u)[1].lower()
            data = small_xlsx(u, args.rows) if (ext == ".xlsx" and args.rows > 0) else open(u, "rb").read()      # --rows 0 이면 엑셀을 줄이지 않고 전부 올린다
            files.append(("files", (os.path.basename(u), data, MIME.get(ext, "application/octet-stream"))))
    elif args.xlsx:
        ext = os.path.splitext(args.xlsx)[1].lower()
        files = [("files", (os.path.basename(args.xlsx), open(args.xlsx, "rb").read(), MIME.get(ext, "text/csv")))]
    elif args.hwp:
        ext = os.path.splitext(args.hwp)[1].lower()
        files = [("files", (os.path.basename(args.hwp), open(args.hwp, "rb").read(), MIME[ext]))]
    else:
        folder = args.files
        xl = next(iter(glob.glob(os.path.join(folder, "*.xlsx"))), None) if folder else None
        docs = sorted(glob.glob(os.path.join(folder, "cpp_week06*.docx"))) if folder else []
        if not xl or len(docs) < 2: raise SystemExit("엑셀 1개와 cpp_week06*.docx 2개가 있는 폴더를 --files 로 주세요.")
        files = [("files", ("문제.xlsx", small_xlsx(xl, args.rows, extra_rows=(15,)), MIME[".xlsx"]))] + \
                [("files", (os.path.basename(p), open(p, "rb").read(), MIME[".docx"])) for p in docs]
    import time as _time; _t0 = _time.time()                       # 업로드부터 AI 처리 완료까지 걸린 시간을 재기 위한 시작 시각
    print("1. 업로드:", [f[1][0] for f in files])
    r = await c.post("/intake/jobs", files=files)
    if r.status_code != 202: raise SystemExit(f"업로드 실패 {r.status_code}: {r.text[:300]}")
    job = r.json()["job_id"]; print(f"   → 작업 {r.json()['records_total']}문제, 입력 종류 {r.json()['input_kind']}")

    async def wait(secs):
        for _ in range(secs * 2):
            j = (await c.get(f"/intake/jobs/{job}")).json()
            if j["status"] != "processing": return j
            await asyncio.sleep(0.5)
        return j
    print("2. 실제 AI 처리 중 … (문제당 수 초~수 분)")
    j = await wait(args.wait)
    for attempt in range(2):                                          # AI 실패가 있으면 이어서 처리를 두 번까지
        if j["status"] in ("paused", "failed") and j["counts"].get("ai_failed"):
            print(f"   AI 실패 {j['counts']['ai_failed']}건 → 이어서 처리({attempt + 1})"); await asyncio.sleep(20)
            await c.post(f"/intake/jobs/{job}/resume"); j = await wait(args.wait)
    print(f"   작업 상태: {j['status']} | 처리 {j['records_done']}/{j['records_total']} | 상태별 {j['counts']}")
    print(f"   소요 시간: 업로드부터 처리 완료까지 {_time.time() - _t0:.0f}초 (문제 {j['records_total']}개, 문제당 평균 {(_time.time() - _t0) / max(1, j['records_total']):.1f}초)")
    if j.get("message"): print(f"   작업 메시지: {j['message']}")
    if j["status"] in ("failed", "paused") and not j.get("records_done"):
        print("   → AI 처리가 시작되지 않았습니다. 위 메시지와 [로그] 줄을 확인하세요 (키·한도·모델 오류일 수 있습니다). 결과는 저장하지 않습니다.")
        return 1
    items = (await c.get(f"/intake/jobs/{job}/items", params={"limit": 200, "with_record": True})).json()
    tc = {t: 0 for t in ("코딩", "디버깅", "객관식", "단답형", "주관식")}
    for it in items:
        t = (it.get("payload") or {}).get("problemType")
        if t: tc[t] = tc.get(t, 0) + 1          # 보류 문제는 유형이 정해지지 않았으므로 유형별 개수에 넣지 않는다 (상태별 개수의 '보류'에 나온다)
    print("   유형별 개수:", " · ".join(f"{k} {v}" for k, v in tc.items()))          # 0 개인 유형도 보여 준다
    print("3. 항목별 결과")
    for it in items:
        b = brief(it)
        print(f"   [{str(b['status']):12}] {str(b['id'] or '(처리 전)'):12} {str(b['type'] or ''):4} 테스트 {b['tests']} 조건 {b['conds']} 코드 {b['code_lang']}")
        for m in b["check_fails"]: print(f"        ✗ 검사 실패: {str(m)[:130]}")
        for m in b["approval_reasons"]: print(f"        · 승인 이유: {str(m)[:100]}")
        for m in b["확인필요"][:3]: print(f"        ? 확인필요: {str(m)[:130]}")
        for m in b["참고"][:2]: print(f"        · 참고(승인 무관): {str(m)[:110]}")
        if b["보류사유"]: print(f"        ⏸ 보류사유: {b['보류사유'][:130]}")
        if b["error"]: print(f"        ⚠ 오류: {b['error'][:100]}")
    print("4. 승인(사람이 확인했다고 가정하고 전체 승인) → 임시 DB 등록")
    ap_ = (await c.post(f"/intake/jobs/{job}/approve", json={"all": True})).json()
    print("   승인 결과:", ap_["summary"])
    async with S() as db:
        rows = (await db.execute(select(Problem.problem_id, Problem.title))).all()
    print(f"   임시 DB 에 저장된 문제: {len(rows)}개 {[r[1] for r in rows]}")
    after = (await c.get(f"/intake/jobs/{job}/items", params={"limit": 200})).json()
    json.dump({"job": j, "before": items, "items": after, "registered": [list(r) for r in rows], "seconds": round(_time.time() - _t0, 1)}, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)      # before: 승인 전 상태(보고서용), items: 전체 승인 뒤
    print(f"전체 결과 저장: {os.path.abspath(args.out)}")
    return 0


async def _run():
    try: return await main()
    finally:
        if ENGINE is not None: await ENGINE.dispose()

sys.exit(asyncio.run(_run()))
