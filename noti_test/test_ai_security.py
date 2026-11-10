"""AI 서비스를 쓸 때의 보안 장치 시험 (가짜 AI): 개인정보를 보내기 전에 지우는지, 하루 사용 한도가 지켜지는지.
noti_test 폴더에서:  python test_ai_security.py        (httpx, aiosqlite 필요)"""
import asyncio, csv, io, json, os, sys, tempfile
import _bootstrap
_bootstrap.setup(sqlite=True)
import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401,E401
from app.inputdata.intake import router as intake_router, service, config, parsing
os.environ["INTAKE_FILL_META"] = "off"          # 이 시험은 AI 호출 횟수를 세므로 부제목·문제의도를 채우는 추가 호출은 끈다 (test_meta_fill.py 가 따로 확인)

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
for v in ("INTAKE_DAILY_PROBLEMS", "INTAKE_DAILY_JOBS", "INTAKE_REDACT_PII"): os.environ.pop(v, None)

print("1. 개인정보 지우기 (글)")
t, n = parsing.redact_text("C++_06_클래스와객체 학번 : 20231234 이름 : 홍길동" + NL + "문제 본문입니다.")
check("제목 줄의 '학번 :' 뒤는 줄 끝까지 지우고 제목 앞부분은 남긴다", t.startswith("C++_06_클래스와객체") and "20231234" not in t and "홍길동" not in t and "문제 본문입니다." in t and n >= 1, t)
t, n = parsing.redact_text("성명 : 김철수" + NL + "학과: 컴퓨터" + NL + "합을 구하시오.")
check("'성명·학과 :' 로 시작하는 줄은 줄 전체를 지운다", t == "합을 구하시오." and n == 2, repr(t))
t, n = parsing.redact_text("연락처 010-1234-5678, 메일 a.b@school.ac.kr, 주민 900101-1234567")
check("휴대전화·이메일·주민등록번호는 [삭제됨] 으로 바꾼다", t.count("[삭제됨]") == 3 and "5678" not in t and "school" not in t and "1234567" not in t, t)
t, n = parsing.redact_text("부모클래스 이름: People" + NL + "책의 이름과 가격을 저장한다." + NL + "12345678 을 8자리로 출력")
check("문제 속의 '이름' 낱말과 8자리 숫자는 지우지 않는다 (내용이 망가지지 않게)", n == 0 and t.count("이름") == 2 and "12345678" in t, (n, t))
t, n = parsing.redact_text("이름: 문제1" + NL + "합", labels=False)
check("엑셀·DB 값(labels=False)은 전화번호 같은 것만 지우고 이름 열 같은 값은 둔다", n == 0 and t.startswith("이름: 문제1"))

print("2. 입력 레코드와 AI 로 가는 글")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "자바_문제.txt")
    open(p, "w", encoding="utf-8").write("자바 실습 학번 : 20231234 이름 : 홍길동" + NL + NL + "문제 1: 두 수의 합을 출력하시오. 문의 010-1234-5678" + NL + "입력: 3 4" + NL + "출력: 7" + NL + NL + "문제 2: 짝수인지 판단하시오." + NL + "입력: 4" + NL + "출력: 짝수")
    kind, recs = parsing.build_records(None, [p], labels=["자바_문제.txt"])
    body = " ".join(r["원본조각"] for r in recs)
    check("원본 문서의 학번·전화번호가 레코드(DB 에 저장되는 입력)에서 지워진다", "20231234" not in body and "010-1234-5678" not in body and "[삭제됨]" in body, body[:200])
    check("지웠다는 메모가 남는다", any("개인정보" in m for r in recs for m in r["intake"]["메모"]), [r["intake"]["메모"] for r in recs])
    os.environ["INTAKE_REDACT_PII"] = "off"
    kind, recs2 = parsing.build_records(None, [p], labels=["자바_문제.txt"])
    check("INTAKE_REDACT_PII=off 이면 지우지 않는다", "010-1234-5678" in " ".join(r["원본조각"] for r in recs2))
    os.environ.pop("INTAKE_REDACT_PII")
    x = os.path.join(d, "문제.csv")
    with open(x, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["이름", "유형", "설명", "정답코드", "출력", "언어"]); w.writerow(["E_01", "코딩", "문의는 a@b.com 로", "print(1)", "1", "Python"])
    kind, recs3 = parsing.build_records(x, [], labels=[], table_labels=["문제.csv"])
    f0 = recs3[0]["fields"]
    check("엑셀 값의 이메일은 지우되 이름 열(문제 이름)은 그대로 둔다", "a@b.com" not in f0["설명"] and f0["이름"] == "E_01", f0)

print("3. 하루 사용 한도 (업로드 API)")
HEAD = ["이름", "유형", "설명", "정답코드", "입력", "출력", "조건", "언어"]
def csv_bytes(n, tag):
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD)
    for i in range(1, n + 1): w.writerow([f"{tag}_{i:02d}", "코딩", f"{i}를 출력하시오", f"print({i})", "", str(i), "정수만 출력", "Python"])
    return buf.getvalue().encode("utf-8-sig")
SENT = []
def ai(user, images=None, info=None, system=None):
    SENT.append(user)
    f = json.JSONDecoder().raw_decode(user.split("입력: ", 1)[1])[0]["fields"]
    p = {"problemType": "코딩", "title": f["이름"], "description": f["설명"], "rating_mode": "none", "problem_condition": ["[필수] 정수만 출력"],
         "test_cases": [{"input": "", "expected_output": f["출력"], "is_hidden": False}], "reference_codes": [{"language": "python", "code": f["정답코드"], "is_main": True}]}
    return json.dumps({"id": f["이름"], "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)

async def scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        await db.commit()
    service.set_session_factory(S)
    service._default_ai = lambda: (ai, "fake")
    who = {"u": "u1"}
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": who["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    async def up(n, tag):
        r = await c.post("/intake/jobs", files=[("files", (f"{tag}.csv", csv_bytes(n, tag), "text/csv"))])
        if r.status_code == 202:
            job = r.json()["job_id"]
            for _ in range(300):
                if (await c.get(f"/intake/jobs/{job}")).json()["status"] != "processing": break
                await asyncio.sleep(0.05)
        return r
    out = {}
    os.environ["INTAKE_DAILY_PROBLEMS"] = "8"; os.environ["INTAKE_LIGHT_ROWS"] = "off"
    out["a1"] = await up(5, "A")
    out["a2"] = await up(5, "B")                                  # 5 + 5 > 8
    who["u"] = "u2"; out["other"] = await up(5, "C")              # 다른 사용자는 따로 센다
    who["u"] = "u1"
    out["pv"] = await c.post("/intake/preview", files=[("files", ("P.csv", csv_bytes(20, "P"), "text/csv"))])      # 미리보기는 세지 않는다
    out["a3"] = await up(3, "D")                                  # 5 + 3 = 8 은 허용
    os.environ.pop("INTAKE_DAILY_PROBLEMS"); os.environ["INTAKE_DAILY_JOBS"] = "3"
    out["j"] = await up(1, "E")                                   # u1 은 이미 작업 2개: 3번째는 허용
    out["j2"] = await up(1, "F")                                  # 4번째는 거절
    os.environ["INTAKE_DAILY_JOBS"] = "0"
    out["j3"] = await up(1, "G")                                  # 0 = 제한 없음
    os.environ.pop("INTAKE_DAILY_JOBS"); os.environ.pop("INTAKE_LIGHT_ROWS", None)
    await engine.dispose()
    return out
o = asyncio.run(scenario())
check("한도 안이면 올라간다 (5문제)", o["a1"].status_code == 202, o["a1"].text[:120])
check("오늘 문제 수 한도(8)를 넘으면 429 와 이유", o["a2"].status_code == 429 and "문제 수" in o["a2"].json()["detail"] and "5개" in o["a2"].json()["detail"], o["a2"].text[:160])
check("다른 사용자는 따로 센다", o["other"].status_code == 202, o["other"].text[:120])
check("미리보기는 한도에 세지 않는다", o["pv"].status_code == 200, o["pv"].status_code)
check("딱 한도(5+3=8)까지는 허용", o["a3"].status_code == 202, o["a3"].text[:160])
check("작업 수 한도(3개)까지는 허용하고 그 다음은 429", o["j"].status_code == 202 and o["j2"].status_code == 429 and "작업 수" in o["j2"].json()["detail"], (o["j"].status_code, o["j2"].status_code))
check("한도 0 은 제한 없음", o["j3"].status_code == 202, o["j3"].text[:120])
check("한도를 넘긴 업로드는 AI 를 한 번도 부르지 않는다 (비용이 들지 않음)", len(SENT) == 5 + 5 + 3 + 1 + 1, len(SENT))

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
