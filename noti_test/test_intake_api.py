"""서버 업로드 기능(intake) 통합 테스트: FastAPI + SQLite + 가짜 AI. 실제 C++ 과제 파일이 있으면 그 파일을 올려 본다.
noti_test 폴더에서:  python test_intake_api.py [--files 폴더]      (pip install fastapi httpx aiosqlite python-multipart python-docx openpyxl)
실제 AI 는 부르지 않는다(가짜 AI 가 엑셀 값으로 결과를 만든다). 서버·DB·등록·승인 흐름을 확인하는 시험이다."""
import argparse, asyncio, glob, io, json, os, sys, tempfile
import _bootstrap
_bootstrap.setup(sqlite=True)
ap = argparse.ArgumentParser(); ap.add_argument("--files", default=os.environ.get("INTAKE_TEST_FILES", ""))
args = ap.parse_args()
os.environ["INTAKE_MAX_FILES"] = "30"
try:
    import httpx, openpyxl, multipart, docx
except ImportError as e:
    print(f"⏭ 건너뜀: 패키지가 필요합니다 ({e.name}).  pip install fastapi httpx aiosqlite python-multipart python-docx openpyxl"); sys.exit(2)
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
from app.inputdata.intake import router as intake_router, service, models as intake_models, config, parsing
import re

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

def conds(t):
    out = []
    for l in (t or "").splitlines():
        l = re.sub(r"^\s*\d+[.)]\s*", "", l.strip())
        if l: out.append(l if re.match(r"^\[(필수|금지|허용|출력형식)\]", l) else "[필수] " + l)
    return out

FAIL_KEYS = set()
def fake_ai(user):
    """엑셀 값으로 결과를 만드는 가짜 AI (규칙 기반). 정답코드가 없으면 보류."""
    rec = json.loads(user.split("입력: ", 1)[1]); f = rec.get("fields", {})
    if not f:                                                  # 표에 없는 문서 문제(원본 입력): 가짜 AI 는 정답을 만들 수 없으므로 보류한다
        key = rec.get("id") or "원본"
        return json.dumps({"id": key, "payload": None, "review": {"상태": "보류", "보류사유": "가짜 AI 는 원본 입력을 처리하지 않음", "입력종류": rec["입력종류"], "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["확인"], "참고": []}}, ensure_ascii=False)
    name = f["이름"].split(" ")[0]
    if name in FAIL_KEYS: raise RuntimeError("AI 서버 혼잡")
    if not f.get("정답코드"):
        return json.dumps({"id": name, "payload": None, "review": {"상태": "보류", "보류사유": "정답코드와 설명이 없음", "입력종류": rec["입력종류"], "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["원본 확인 필요"]}}, ensure_ascii=False)
    p = {"problemType": f["유형"], "title": name, "description": f["설명"], "difficulty": f.get("난이도", "EASY").lower(), "rating_mode": "none",
         "problem_condition": conds(f.get("조건")), "test_cases": [{"input": "", "expected_output": f.get("실행결과1") or f["출력"]}] if (f.get("실행결과1") or f.get("출력")) else [],
         "reference_codes": [{"language": {"c++": "cpp", "c": "c", "python": "python", "java": "java"}.get(f.get("언어", "C++").lower(), "cpp"), "code": f["정답코드"], "is_main": True}]}
    if f["유형"] == "디버깅": p["base_code"] = [{"language": "cpp", "code": f.get("제공코드") or "", "is_main": False}]
    if not p["test_cases"] and not p["problem_condition"]: p["problem_condition"] = ["[필수] 실행 화면과 같게 동작"]
    review = {"상태": "등록가능", "보류사유": None, "입력종류": rec["입력종류"], "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": []}
    if name == "C++_06_04": review["확인필요"] = ["출력 형식 확인 필요"]
    return json.dumps({"id": name, "payload": p, "review": review}, ensure_ascii=False)
service._default_ai = lambda: (fake_ai, "fake")

def make_xlsx(src, n_rows, extra_rows=()):
    """실제 엑셀에서 처음 n 개 문제 행 + 지정한 행을 골라 작은 엑셀을 만든다."""
    wb = openpyxl.load_workbook(src); ws = wb.active
    keep = set(range(1, 5)) | set(range(5, 5 + n_rows)) | set(extra_rows)
    for r in range(ws.max_row, 0, -1):
        if r not in keep: ws.delete_rows(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()

async def wait_done(c, job_id, hdr, secs=120):
    for _ in range(secs * 5):
        j = (await c.get(f"/intake/jobs/{job_id}", headers=hdr)).json()
        if j["status"] != "processing": return j
        await asyncio.sleep(0.2)
    return j

ENGINE = None


async def main():
    global ENGINE
    engine = ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)                    # expire_on_commit 기본값(True) 그대로 — 실제 서버 설정이 달라도 동작해야 한다
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        await db.commit()
    service.set_session_factory(S)
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    cur = {"u": "u1"}
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: {"sub": cur["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    H = {}
    folder = args.files
    xl = next(iter(glob.glob(os.path.join(folder, "*.xlsx"))), None) if folder else None
    docs = sorted(glob.glob(os.path.join(folder, "cpp_week06*.docx"))) if folder else []
    if not xl or len(docs) < 2:
        print("⏭ 건너뜀: 실제 문제지 폴더가 없습니다.  python test_intake_api.py --files 폴더  (또는 환경변수 INTAKE_TEST_FILES)"); sys.exit(2)
    small = make_xlsx(xl, 5, extra_rows=(15,))          # 06_03~06_07 + 상태메시지 행(C++_08_04)
    mime = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    def files(): return [("files", ("문제.xlsx", small, mime[".xlsx"]))] + [("files", (os.path.basename(p), open(p, "rb").read(), mime[".docx"])) for p in docs]

    print("1. 업로드 입력 검사")
    r = await c.post("/intake/jobs", files=[("files", ("a.exe", b"x", "application/octet-stream"))]); check("지원하지 않는 형식은 400", r.status_code == 400, r.text)
    os.environ["INTAKE_MAX_FILES"] = "5"                                                    # 전체 파일 수 제한은 형식과 상관없이 하나 (엑셀·워드·PDF·한글·PPT 모두 합쳐서)
    r = await c.post("/intake/jobs", files=[("files", (f"{i}.xlsx", small, mime[".xlsx"])) for i in range(2)] + [("files", (f"{i}.docx", b"x", mime[".docx"])) for i in range(4)])
    check("엑셀 2 + 워드 4 = 6개면 형식과 상관없이 전체 5개 제한에 걸려 400", r.status_code == 400 and "최대 5개" in r.text, r.text)
    os.environ["INTAKE_MAX_FILES"] = "30"
    r = await c.post("/intake/jobs", files=[("files", ("a.docx", b"not a docx", mime[".docx"]))]); check("깨진 워드는 422 (원인 안내)", r.status_code == 422, r.text)
    old = os.environ.get("INTAKE_MAX_FILE_MB"); os.environ["INTAKE_MAX_FILE_MB"] = "0"
    r = await c.post("/intake/jobs", files=[("files", ("a.xlsx", small, mime[".xlsx"]))]); check("너무 큰 파일은 413", r.status_code == 413, r.text)
    os.environ.pop("INTAKE_MAX_FILE_MB") if old is None else os.environ.__setitem__("INTAKE_MAX_FILE_MB", old)

    print("2. 엑셀 + 워드(과제·풀이) 업로드 → 백그라운드 처리 (정답코드 실행 검증 꺼짐)")
    FAIL_KEYS.add("C++_06_05")
    r = await c.post("/intake/jobs", files=files(), data={"auto_register": "true"}); check("202 로 받아 작업 생성", r.status_code == 202 and r.json()["input_kind"] == "혼합", r.text)
    job = r.json()["job_id"]; check("문제 8개로 나뉨 (엑셀 6 + 표에 없는 문서 문제 2)", r.json()["records_total"] == 8, r.json())
    r2 = await c.post("/intake/jobs", files=files()); check("처리 중에 또 올리면 409 (또는 이미 끝남)", r2.status_code in (409, 202), r2.text)
    j = await wait_done(c, job, H)
    check("AI 실패 1건이 있으면 paused", j["status"] == "paused" and j["counts"].get("ai_failed") == 1, j)
    check("정상은 승인 대기, 정답코드 없는 행은 보류, 설명이 원본과 다른 행(06_07)은 검사에서 막힘", j["counts"].get("needs_review") == 3 and j["counts"].get("held") == 3 and j["counts"].get("blocked") == 1, j["counts"])
    items = (await c.get(f"/intake/jobs/{job}/items", headers=H)).json()
    bl = next((i for i in items if i["status"] == "blocked"), None)
    check("막힌 이유가 항목에 적힘 (엑셀 설명을 그대로 쓴 것)", bl and bl["result_id"].startswith("C++_06_07") and "src" in bl["check_fails"][0], bl and bl["check_fails"])
    nr = [i for i in items if i["status"] == "needs_review"]
    check("승인 이유가 표시됨 (실행 미검증)", all(any("실행" in x for x in i["approval_reasons"]) for i in nr), nr[0]["approval_reasons"] if nr else "")
    check("확인필요가 있으면 그 이유도 표시", any(any("확인할 것" in x for x in i["approval_reasons"]) for i in nr))
    async with S() as db: check("DB 문제 0개", len((await db.execute(select(Problem))).scalars().all()) == 0)

    print("3. 이어서 처리(resume)")
    FAIL_KEYS.clear()
    r = await c.post(f"/intake/jobs/{job}/resume"); j = await wait_done(c, job, H)
    check("resume 후 done", r.status_code == 202 and j["status"] == "done" and j["counts"].get("ai_failed") is None, j)
    check("4개 승인 대기 + 1개 막힘 + 1개 보류", j["counts"].get("needs_review") == 4 and j["counts"].get("blocked") == 1 and j["counts"].get("held") == 3, j["counts"])

    print("4. 승인 · 수정 · 제외")
    items = (await c.get(f"/intake/jobs/{job}/items", headers=H)).json()
    held = next(i for i in items if i["status"] == "held"); rej = next(i for i in items if i["status"] == "needs_review")
    r = await c.post(f"/intake/items/{rej['item_id']}/reject"); check("제외", r.json()["status"] == "skipped", r.text)
    r = await c.post(f"/intake/jobs/{job}/approve", json={}); check("item_ids·all 없이는 400", r.status_code == 400)
    r = await c.post(f"/intake/jobs/{job}/approve", json={"all": True}); ap_ = r.json()
    check("승인 대기 3개만 등록, 막힘·보류·제외는 건드리지 않음", ap_["summary"] == {"registered": 3}, ap_)
    async with S() as db:
        ps = (await db.execute(select(Problem))).scalars().all()
        check("DB 에 3개 저장 (디버깅은 base_code 포함)", len(ps) == 3 and all(p.maker_id == "u1" for p in ps) and any(getattr(p, "base_code", None) for p in ps), [p.title for p in ps])
    r = await c.post(f"/intake/jobs/{job}/approve", json={"all": True}); check("다시 승인해도 중복 등록 없음", r.json()["summary"] == {} or "registered" not in r.json()["summary"], r.json())
    r = await c.patch(f"/intake/items/{held['item_id']}", json={"payload": {"problemType": "코딩", "title": "", "description": "d"}}); check("잘못된 수정은 422 (필드 안내)", r.status_code == 422 and any(e["field"] == "title" for e in r.json()["detail"]), r.text)
    fixed = {"problemType": "코딩", "title": "C++_08_04", "description": "원본에서 가져온 설명", "test_cases": [{"input": "", "expected_output": "1"}], "reference_codes": [{"language": "cpp", "code": "#include <iostream>\nint main(){std::cout<<1;}"}]}
    r = await c.patch(f"/intake/items/{held['item_id']}", json={"payload": fixed}); check("보류 항목을 사람이 채우면 승인 대기로", r.status_code == 200 and r.json()["status"] == "needs_review" and r.json()["edited"], r.text)
    blk = next(i for i in (await c.get(f"/intake/jobs/{job}/items?with_record=true", headers=H)).json() if i["status"] == "blocked")
    orig_desc = blk["record"]["원본조각"].split("[소스]")[0].strip()
    r = await c.patch(f"/intake/items/{blk['item_id']}", json={"payload": {**blk["payload"], "description": orig_desc}}); check("막힌 항목을 원본 설명으로 고치면 승인 대기로", r.json()["status"] == "needs_review", r.text)
    r = await c.post(f"/intake/jobs/{job}/approve", json={"item_ids": [held["item_id"], blk["item_id"], 99999]}); sm = r.json()["summary"]
    check("수정한 두 항목 등록, 없는 항목은 skipped", sm == {"registered": 2, "skipped": 1}, r.json())

    print("5. 권한 · 중복")
    cur["u"] = "u2"
    check("다른 사용자는 작업을 볼 수 없음 (404)", (await c.get(f"/intake/jobs/{job}")).status_code == 404 and (await c.post(f"/intake/items/{held['item_id']}/reject")).status_code == 404)
    check("다른 사용자의 목록은 비어 있음", (await c.get("/intake/jobs")).json() == [])
    cur["u"] = "u1"
    r = await c.post("/intake/jobs", files=files()); job2 = r.json()["job_id"]; j2 = await wait_done(c, job2, H)
    r = await c.post(f"/intake/jobs/{job2}/approve", json={"all": True}); sm = r.json()["summary"]
    check("같은 문제지를 다시 올리면 이미 등록된 3개는 중복으로 건너뜀(제외했던 1개만 새로 등록)", sm.get("duplicate") == 3 and sm.get("registered") == 1, sm)

    print("6. 정답코드 실행 검증을 켜면 (깨끗한 것은 자동 등록)")
    os.environ["INTAKE_EXEC"] = "on"; os.environ["INTAKE_EXEC_ISOLATED"] = "on"   # 실행 검증은 격리 확인까지 있어야 켜진다 (config.exec_enabled)
    async with S() as db: before = len((await db.execute(select(Problem))).scalars().all())
    small2 = make_xlsx(xl, 1)          # C++_06_03 한 개 (입력 없는 프로그램, 실행 결과 일치)
    # 다른 사용자로 올려서 중복과 무관하게 새로 등록되게 한다
    cur["u"] = "u2"
    r = await c.post("/intake/jobs", files=[("files", ("문제.xlsx", small2, mime[".xlsx"]))]); job3 = r.json()["job_id"]; j3 = await wait_done(c, job3, H)
    it3 = (await c.get(f"/intake/jobs/{job3}/items", headers=H)).json()
    check("검사 통과 + 확인필요 없음 → 승인 없이 바로 등록", j3["counts"].get("registered") == 1 and it3[0]["problem_id"], j3["counts"])
    print("7. 언어가 섞인 파일 (Python · C · Java) — 실행 검증을 켠 상태")
    import csv as _csv
    buf = io.StringIO(); w = _csv.writer(buf)
    w.writerow(["이름", "유형", "난이도", "설명", "정답코드", "언어", "출력"])
    w.writerow(["PY-1", "코딩", "easy", "1을 출력하시오", "print(1)", "Python", "1"])
    w.writerow(["C-1", "코딩", "easy", "2를 출력하시오", '#include <stdio.h>\nint main(){printf("2");return 0;}', "C", "2"])
    w.writerow(["J-1", "코딩", "easy", "3을 출력하시오", 'public class Main{public static void main(String[] a){System.out.print(3);}}', "Java", "3"])
    csv = buf.getvalue().encode("utf-8")
    cur["u"] = "u2"
    r = await c.post("/intake/jobs", files=[("files", ("mixed.csv", csv, "text/csv"))]); check("CSV 업로드 (엑셀 외 표 형식)", r.status_code == 202, r.text)
    j4 = await wait_done(c, r.json()["job_id"], H); its = (await c.get(f"/intake/jobs/{r.json()['job_id']}/items", headers=H)).json()
    st = {i["result_id"]: i for i in its}
    check("Python·C 는 실행 검증을 통과해 바로 등록", st["PY-1"]["status"] == "registered" and st["C-1"]["status"] == "registered", {k: v["status"] for k, v in st.items()})
    import shutil as _sh
    if _sh.which("javac") and _sh.which("java"):
        check("Java 도 서버가 실행해 기대 출력과 맞으면 바로 등록", st["J-1"]["status"] == "registered", (st["J-1"]["status"], st["J-1"]["approval_reasons"], st["J-1"]["check_fails"]))
    else:
        check("javac/java 가 없는 환경에서는 승인 대기 + 이유 표시", st["J-1"]["status"] == "needs_review" and any("java" in x for x in st["J-1"]["approval_reasons"]), st["J-1"]["approval_reasons"])
    os.environ.pop("INTAKE_EXEC"); os.environ.pop("INTAKE_EXEC_ISOLATED")
    print(f"\n결과: 통과 {passed} / 실패 {failed}")
    return failed

async def _run():
    """엔진을 반드시 닫는다: 열린 aiosqlite 연결이 남으면 (건너뛰어 sys.exit 할 때도) 파이썬이 종료되지 않는다."""
    try:
        return await main()
    finally:
        if ENGINE is not None: await ENGINE.dispose()


sys.exit(1 if asyncio.run(_run()) else 0)
