"""엑셀·CSV 열 인식 시험: 열 이름의 변형을 알아보고, 모르는 열은 버리지 않고 알린다.
실제 사례: '전체 코드', '문제 제공코드' 열을 인식하지 못하고 조용히 버려서 정답코드가 사라진 것으로 읽혔다.
noti_test 폴더에서:  python test_xlsx_columns.py"""
import asyncio, csv, io, json, os, sys, tempfile
import _bootstrap
_bootstrap.setup(sqlite=True)
os.environ["INTAKE_MAX_FILES"] = "30"
import httpx, openpyxl
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem
from app.inputdata.intake import router as intake_router, service
from app.inputdata.intake.readers import xlsx_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

tmp = tempfile.mkdtemp(); NL = chr(10)
def make_xlsx(headers, row, name="t.xlsx"):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "문제"; ws.append(headers); ws.append(row)
    p = os.path.join(tmp, name); wb.save(p); return p

print("1. 열 이름 변형을 알아본다")
H = [" 문제 이름", "문제 난이도", "문제 유형", "문제 설명", "문제 조건", "문제 제공코드", "전체 코드", "예상 출력", "입력"]
R = ["cpp01_01 예시", "EASY", "디버깅", "배열을 출력하세요", "[필수] 반복문", "int a[3];", "int main(){return 0;}", "1 2 3", "5"]
rows = xlsx_intake.read(make_xlsx(H, R))
f = rows[0]["fields"]
check("'전체 코드' → 정답코드", f.get("정답코드") == "int main(){return 0;}", f)
check("'문제 제공코드' → 제공코드", f.get("제공코드") == "int a[3];", f)
check("'예상 출력' → 출력, ' 문제 이름'(앞 공백) → 이름", f.get("출력") == "1 2 3" and f.get("이름") == "cpp01_01 예시", f)
check("정답코드와 제공코드를 읽었으니 필수 누락이 없다", rows[0]["intake"]["필수누락"] == [], rows[0]["intake"]["필수누락"])
check("모든 열을 알아본 경우 '무시한 열' 메모가 없다", not any("무시한 열" in m for m in rows[0]["intake"]["메모"]), rows[0]["intake"]["메모"])

print("2. 모르는 열은 버리지 않고 알린다")
rows = xlsx_intake.read(make_xlsx(["이름", "설명", "정답코드", "출제자", "번호"], ["X-1", "합을 구하시오", "print(1)", "홍길동", "7"], "u.xlsx"))
memo = [m for m in rows[0]["intake"]["메모"] if "무시한 열" in m]
check("엑셀: 인식하지 못한 열 이름을 메모에 적는다", len(memo) == 1 and "출제자" in memo[0] and "번호" in memo[0], memo)
csvp = os.path.join(tmp, "u.csv")
with open(csvp, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["이름", "설명", "정답코드", "작성자"]); w.writerow(["X-2", "합을 구하시오", "print(1)", "김철수"])
rows = xlsx_intake.read(csvp)
check("CSV: 인식하지 못한 열 이름을 메모에 적는다", any("무시한 열: 작성자" in m for m in rows[0]["intake"]["메모"]), rows[0]["intake"]["메모"])

print("2-2. 같은 이름이 여러 번 나오면 알린다 (AI 는 문제를 하나씩만 보므로 서버가 알려 줘야 한다)")
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "문제"; ws.append(["이름", "설명"])
for nm, ds in (("문제 D-1", "첫째"), ("문제 D-2", "둘째"), ("문제 D-1", "셋째, 이름만 같음"), ("문제 D-3", "넷째")): ws.append([nm, ds])
dp = os.path.join(tmp, "d.xlsx"); wb.save(dp)
rows = xlsx_intake.read(dp)
memo = {r["fields"]["설명"]: [m for m in r["intake"]["메모"] if "같은 이름" in m] for r in rows}
check("이름이 겹친 두 행에 메모가 붙고 행 번호가 적힌다", all(len(memo[k]) == 1 and "2번" in memo[k][0] and "행 2, 4" in memo[k][0] for k in ("첫째", "셋째, 이름만 같음")), memo)
check("겹치지 않은 행에는 메모가 없다", memo["둘째"] == [] and memo["넷째"] == [], memo)
csvd = os.path.join(tmp, "d.csv")
with open(csvd, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["이름", "설명"]); w.writerow(["X", "a"]); w.writerow(["X", "b"])
check("CSV 도 같다", all(any("같은 이름" in m for m in r["intake"]["메모"]) for r in xlsx_intake.read(csvd)))

print("3. 업로드 응답에 경고가 실린다 (가짜 AI)")
def fake_ai(user):
    rec = json.loads(user.split("입력: ", 1)[1]); name = rec["fields"]["이름"]
    p = {"problemType": "객관식", "title": name, "rating_mode": "none", "description": rec["fields"]["설명"], "options": ["a", "b"], "correct_answers": [0]}
    rv = {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}
    return json.dumps({"id": name, "payload": p, "review": rv}, ensure_ascii=False)
service._default_ai = lambda: (fake_ai, "fake")
ENGINE = None
async def main():
    global ENGINE
    engine = ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    def csv_bytes(header):
        out = io.StringIO(); w = csv.writer(out); w.writerow(header); w.writerow(["문제 W-1" if "번호" not in header else "문제 W-2", "설명입니다"] + ["x"] * (len(header) - 2)); return out.getvalue().encode("utf-8")
    r = await c.post("/intake/jobs", files=[("files", ("a.csv", csv_bytes(["이름", "설명", "출제자"]), "text/csv"))])
    body = r.json()
    check("모르는 열이 있으면 202 응답에 warnings 가 있다", r.status_code == 202 and any("출제자" in w for w in body.get("warnings", [])), body)
    for _ in range(100):
        j = (await c.get(f"/intake/jobs/{body['job_id']}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    r2 = await c.post("/intake/jobs", files=[("files", ("b.csv", csv_bytes(["이름", "설명", "정답"]), "text/csv"))])
    check("열을 모두 알아본 업로드에는 warnings 가 비어 있다", r2.status_code == 202 and r2.json().get("warnings") == [], r2.text[:200])
    return 0
async def _run():
    try: return await main()
    finally:
        if ENGINE is not None: await ENGINE.dispose()
asyncio.run(_run())
print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
