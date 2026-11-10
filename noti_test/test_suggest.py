"""조건 예시 시험: 정답 코드가 쓰는 것을 읽어 '무엇을 사용해서 작성해야 하는지' 조건 하나를 만든다 (AI 호출 없음).
noti_test 폴더에서:  python test_suggest.py"""
import asyncio, os, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401
from app.inputdata.intake import router as intake_router
from app.inputdata.intake.checks import suggest
from app.inputdata.intake.models import IntakeItem, IntakeJob

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

def P(code, ptype="코딩", conds=None, tcs=None):
    return {"problemType": ptype, "title": "t", "description": "d", "problem_condition": conds if conds is not None else [],
            "test_cases": tcs or [], "reference_codes": [{"language": "python", "code": code, "is_main": True}]}
def ex(code, **kw):
    r = suggest.example_condition(P(code, **kw), kw.get("conds")); return r["text"] if r else None

print("1. 정답 코드가 쓰는 것 → 조건 하나")
check("np.random.random() 을 쓰면 그 함수를 쓰라는 조건", ex("import numpy as np\na = np.random.random((3, 6))\nprint(a)") == "[필수] np.random.random() 함수를 사용한다")
check("math 함수", ex("import math\nprint(math.sqrt(16))") == "[필수] math.sqrt() 함수를 사용한다")
check("for 반복문만 쓰면 for 조건", ex("t = 0\nfor i in range(1, 11):\n    t += i\nprint(t)") == "[필수] for 반복문을 사용한다")
check("while 만 쓰면 while 조건", ex("i = 0\nwhile i < 3:\n    i += 1") == "[필수] while 반복문을 사용한다")
check("Java extends 는 상속 조건", ex("class A {}\nclass B extends A {}") == "[필수] 상속(extends)을 사용한다")
check("Java interface/implements", ex("interface I {}\nclass C implements I {}") == "[필수] 인터페이스를 사용한다")
check("C++ 이동 생성자(X&&)", ex("class P { P(P&& o) noexcept {} };") == "[필수] 이동 생성자를 구현한다")
check("C++ 복사 생성자(const X&)", ex("class P { P(const P& o) {} };") == "[필수] 복사 생성자를 구현한다")
check("다른 메서드를 두 번 부르는 것(main 이 show 를 부름)은 재귀가 아니다", ex("class A {\n  static void show() { System.out.println(1); }\n  public static void main(String[] a) { show(); show(); }\n}") != "[필수] 재귀 호출을 사용한다")
check("함수 g 가 다른 함수 f 를 부르는 것은 재귀가 아니다", ex("def f(x):\n    return x\ndef g(y):\n    return f(y) + f(y)\nprint(g(1))") != "[필수] 재귀 호출을 사용한다")
check("Java 재귀 (자기 본문에서 자기를 부름)", ex("static int fact(int n) {\n  if (n <= 1) return 1;\n  return n * fact(n - 1);\n}") == "[필수] 재귀 호출을 사용한다")
check("np.array 만 쓰는 코드보다 다른 np 함수를 먼저 고른다", ex("import numpy as np\na = np.array([1, 2])\nb = np.arange(24)") == "[필수] np.arange() 함수를 사용한다")
check("Scanner(입력 도구)만 쓰는 코드는 예시로 삼지 않는다", ex("Scanner sc = new Scanner(System.in);") is None)
check("재귀 함수", ex("def f(n):\n    return 1 if n <= 1 else n * f(n - 1)") == "[필수] 재귀 호출을 사용한다")
check("리스트 컴프리헨션", ex("a = [x * 2 for x in range(3)]") == "[필수] 리스트 컴프리헨션을 사용한다")
check("람다식", ex("f = lambda x: x + 1") == "[필수] 람다식을 사용한다")
check("try/except", ex("try:\n    x = 1\nexcept ValueError:\n    pass") == "[필수] 예외 처리(try)를 사용한다")
check("내장 함수(sorted)", ex("print(sorted([3, 1, 2]))") == "[필수] sorted() 함수를 사용한다")
check("Java 클래스(ArrayList)", ex("ArrayList<Integer> a = new ArrayList<>();") == "[필수] ArrayList 클래스를 사용한다")
check("기대 출력이 모두 소수점 둘째 자리면 출력형식 조건", ex("print(1)", tcs=[{"expected_output": "0.31\n0.48"}, {"expected_output": "1.25"}]) == "[출력형식] 소수점 둘째 자리까지 출력한다")

print("2. 건너뛰기와 없음")
check("이미 같은 조건이 있으면 건너뛰고 다음으로 눈에 띄는 것", ex("import numpy as np\nfor i in range(3):\n    np.random.random()", conds=["[필수] random 함수를 사용한다"]) == "[필수] for 반복문을 사용한다")
check("for 조건이 이미 있으면 for 는 건너뜀", ex("for i in range(3):\n    print(sorted([1]))", conds=["[필수] for 반복문을 사용한다"]) == "[필수] sorted() 함수를 사용한다")
check("글자 값 속의 for 는 코드가 아니다", ex('print("for while class")') is None)
check("주석 속의 for 는 코드가 아니다", ex("print(1)  # for 반복문 안 씀") is None)
check("쓸 만한 것이 없으면 None", ex("print(1 + 2)") is None)
check("객관식은 None", suggest.example_condition({"problemType": "객관식", "reference_codes": [{"code": "for i in x: pass"}]}) is None)
check("정답 코드가 없으면 None", suggest.example_condition({"problemType": "코딩", "reference_codes": []}) is None)
r = suggest.example_condition(P("for i in range(3):\n    pass"))
check("근거 문장이 함께 온다 (정답 코드가 for 를 씁니다)", r["reason"] == "정답 코드가 for 반복문을 씁니다", r)
check("만든 조건은 항상 [태그] 형식이다", all(suggest.COND_RE.match(x) for x in [ex("for i in x: pass"), ex("x = lambda: 1"), ex("import math\nmath.pi.real()")] if x))

print("3. API")
def coding(code="for i in range(3):\n    print(i)", **kw):
    p = P(code, **kw); p.update(title="PY11_0001", description="0부터 2까지 출력하시오.", rating_mode="none", difficulty="easy", tags=[]); return p
async def scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        db.add(IntakeJob(job_id="J1", maker_id="u1", status="done", input_kind="원본", file_names=["a.docx"], options={}, records_total=3))
        db.add(IntakeItem(job_id="J1", seq=0, out_index=0, source_key="A", result_id="A", status="needs_review", payload=coding(), review={"상태": "등록가능"}, record=None))
        db.add(IntakeItem(job_id="J1", seq=1, out_index=0, source_key="B", result_id="B", status="needs_review",
                          payload={"problemType": "객관식", "title": "PY11_0002", "description": "d", "options": ["a", "b"], "correct_answers": [0], "rating_mode": "none"}, review={}, record=None))
        db.add(IntakeItem(job_id="J1", seq=2, out_index=0, source_key="C", result_id="C", status="held", payload=None, review={"상태": "보류"}, record=None))
        await db.commit()
        ids = (await db.execute(select(IntakeItem.item_id).order_by(IntakeItem.seq))).scalars().all()
    who = {"u": "u1"}
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": who["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30)
    a, b, h = ids
    r = {}
    r["items"] = {i["source_key"]: i for i in (await c.get("/intake/jobs/J1/items")).json()}
    r["post"] = await c.post(f"/intake/items/{a}/suggest-conditions", json={})
    r["form"] = await c.post(f"/intake/items/{a}/suggest-conditions", json={"payload": coding("import numpy as np\nnp.random.random()")})
    r["cur"] = await c.post(f"/intake/items/{a}/suggest-conditions", json={"conditions": ["[필수] for 반복문을 사용한다"]})
    r["mc"] = await c.post(f"/intake/items/{b}/suggest-conditions", json={})
    r["held"] = await c.post(f"/intake/items/{h}/suggest-conditions", json={})
    r["nocode"] = await c.post(f"/intake/items/{a}/suggest-conditions", json={"payload": coding("   ")})
    who["u"] = "u2"; r["other"] = await c.post(f"/intake/items/{a}/suggest-conditions", json={}); who["u"] = "u1"
    await engine.dispose()
    return r
r = asyncio.run(scenario())
check("항목 조회에 condition_example 이 바로 들어 있다 (버튼 없이)", r["items"]["A"]["condition_example"] == {"text": "[필수] for 반복문을 사용한다", "reason": "정답 코드가 for 반복문을 씁니다"}, r["items"]["A"].get("condition_example"))
check("객관식·보류 항목은 condition_example 이 None", r["items"]["B"]["condition_example"] is None and r["items"]["C"]["condition_example"] is None)
check("POST 도 같은 예시를 돌려준다", r["post"].status_code == 200 and r["post"].json()["example"]["text"] == "[필수] for 반복문을 사용한다", r["post"].text)
check("화면에서 방금 고친 정답 코드(저장 전)를 보고 다시 만든다", r["form"].json()["example"]["text"] == "[필수] np.random.random() 함수를 사용한다", r["form"].text)
check("화면의 지금 조건과 겹치면 건너뛴다 → 없음 + 안내", r["cur"].json()["example"] is None and r["cur"].json()["message"], r["cur"].text)
check("객관식은 400", r["mc"].status_code == 400, r["mc"].text)
check("보류(내용 없음)는 400", r["held"].status_code == 400, r["held"].text)
check("정답 코드가 비면 400 + 안내", r["nocode"].status_code == 400 and "정답 코드" in r["nocode"].json()["detail"], r["nocode"].text)
check("다른 사용자는 404", r["other"].status_code == 404, r["other"].status_code)

print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
