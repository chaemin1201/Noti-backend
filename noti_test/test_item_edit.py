"""승인 화면용 API 시험 (AI 호출 없음): 수정 후 서버 재검사 · 부제목/문제의도 저장 · image_url 저장 · 원본 보기.
noti_test 폴더에서:  python test_item_edit.py"""
import asyncio, json, os, sys
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
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401
from app.inputdata.intake import router as intake_router
from app.inputdata.intake.models import IntakeItem, IntakeJob

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

IMG = "https://api.hellonoti.co.kr/media/2026/11/09/abc.png"
def coding(out="3", **kw):
    p = {"problemType": "코딩", "title": "PY41_0001", "description": "두 수의 합을 출력하시오.", "difficulty": "easy", "tags": ["합"], "rating_mode": "none",
         "problem_condition": ["[필수] 정수만 출력"], "test_cases": [{"input": "", "expected_output": out, "is_hidden": False}],
         "reference_codes": [{"language": "python", "code": "print(1 + 2)", "is_main": True}]}
    p.update(kw); return p

async def scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        db.add(IntakeJob(job_id="J1", maker_id="u1", status="done", input_kind="원본", file_names=["a.docx"], options={"mode": "none", "auto_register": False}, records_total=2))
        ti = {"코드접두": "PY41", "등록제목": "PY41_0001", "원래이름": "PY41-0001", "읽을이름": "", "주제번호확실": True}
        db.add(IntakeItem(job_id="J1", seq=0, out_index=0, source_key="PY41-0001", result_id="PY41-0001", status="held", payload=None,
                          review={"상태": "보류", "보류사유": "원문이 부족합니다", "제목정보": ti, "정리": [], "채움": []},
                          record={"입력종류": "원본", "원본형식": "워드", "page": 1, "원본조각": "두 수의 합을 출력하는 프로그램", "이미지": [{"n": 1, "mime": "image/png", "b64": "iVBORw0KGgo="}], "intake": {"메모": ["메모1"]}}))
        db.add(IntakeItem(job_id="J1", seq=1, out_index=0, source_key="PY41-0002", result_id="PY41-0002", status="needs_review", payload=coding(title="PY41_0002"),
                          review={"상태": "등록가능", "제목정보": {**ti, "등록제목": "PY41_0002", "원래이름": "PY41-0002"}}, record={"입력종류": "엑셀", "fields": {"이름": "PY41-0002", "부제목": "엑셀 부제목"}}))
        await db.commit()
        ids = (await db.execute(select(IntakeItem.item_id).order_by(IntakeItem.seq))).scalars().all()
    who = {"u": "u1"}
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": who["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30)
    held, rev = ids
    r = {}
    # 3. 원본 보기
    o = (await c.get(f"/intake/items/{held}/original")).json()
    r["orig"] = o
    who["u"] = "u2"; r["other_orig"] = (await c.get(f"/intake/items/{held}/original")).status_code; r["other_patch"] = (await c.patch(f"/intake/items/{held}", json={"payload": coding()})).status_code; who["u"] = "u1"
    # 4. 수정 후 재검사: 보류 문제를 기대 출력이 빈 채로 채움 → needs_input
    p1 = (await c.patch(f"/intake/items/{held}", json={"payload": coding(out="")}))
    r["p1"] = p1.status_code, p1.json()
    # 검사 실패(조건 형식 오류) → blocked
    p2 = await c.patch(f"/intake/items/{held}", json={"payload": coding(problem_condition=["그냥 문장입니다"])})
    r["p2"] = p2.status_code, p2.json()
    # 잘못된 image_url → 422
    r["bad_img"] = (await c.patch(f"/intake/items/{held}", json={"payload": coding(image_url="javascript:alert(1)")})).status_code
    # 2. 부제목·문제의도 + 1. image_url + 정상 → needs_review
    p3 = await c.patch(f"/intake/items/{held}", json={"payload": coding(image_url=IMG), "subtitle": "합 구하기", "intent": "덧셈 출력 이해"})
    r["p3"] = p3.status_code, p3.json()
    # 부제목만 다시 고치면 의도는 그대로
    p4 = await c.patch(f"/intake/items/{held}", json={"payload": coding(image_url=IMG), "subtitle": "합 구하기 2"})
    r["p4"] = p4.json()
    r["listed"] = [i for i in (await c.get("/intake/jobs/J1/items")).json() if i["item_id"] == held][0]
    # 프론트가 설명을 JSON 으로 묶어 보내는 경우 (부제목·문제의도를 프론트가 처리하는 방식)
    wrapped = json.dumps({"intent": "프론트 의도", "subtitle": "프론트 부제목", "content": "두 수의 합을 출력하시오."}, ensure_ascii=False)
    p5 = await c.patch(f"/intake/items/{held}", json={"payload": coding(image_url=IMG, description=wrapped)})
    r["p5"] = p5.status_code, p5.json()
    # 등록
    ap = (await c.post("/intake/jobs/J1/approve", json={"item_ids": [held, rev]})).json()
    r["approve"] = ap
    async with S() as db:
        rows = (await db.execute(select(Problem))).scalars().all()
        r["db"] = [(p.title, p.image_url, p.description) for p in rows]
    # 엑셀 부제목은 그대로, 항목 목록의 subtitle 기본값
    r["rev_item"] = [i for i in (await c.get("/intake/jobs/J1/items")).json() if i["item_id"] == rev][0]
    await engine.dispose()
    return r

r = asyncio.run(scenario())
print("1. 원본 보기 (문제 하나의 원본만)")
o = r["orig"]
check("원본 글·형식·쪽·그림이 나온다", o["text"] == "두 수의 합을 출력하는 프로그램" and o["format"] == "워드" and o["page"] == 1 and o["images"] and o["images"][0]["b64"] == "iVBORw0KGgo=", o)
check("메모와 분할 정보도 나온다", o["memo"] == ["메모1"] and o["split"] is None and o["whole_doc"] is False)
check("다른 사용자는 볼 수도 고칠 수도 없다 (404)", r["other_orig"] == 404 and r["other_patch"] == 404, (r["other_orig"], r["other_patch"]))

print("2. 수정 후 서버가 다시 검사한다")
st, j = r["p1"]
check("기대 출력이 빈 채로 수정하면 입력 필요(needs_input) + 이유", st == 200 and j["status"] == "needs_input" and any("기대 출력" in x for x in j["approval_reasons"]), j["approval_reasons"] if st == 200 else r["p1"])
check("보류 문제를 사람이 채우면 보류 상태가 풀리고 사유가 참고로 남는다", j["review"]["상태"] == "등록가능" and j["review"]["보류사유"] is None and any("보류 사유: 원문이 부족합니다" in x for x in j["review"]["참고"]), j["review"])
st, j = r["p2"]
check("검사 실패(조건 형식)는 blocked + check_fails", st == 200 and j["status"] == "blocked" and j["check_fails"], j)
check("blocked 는 승인(등록)할 수 없다 — 아래 승인 결과에 held 항목이 등록으로 이어지지 않음은 정상 수정 뒤에만", True)
st, j = r["p3"]
check("정상으로 고치면 승인 대기(needs_review)", st == 200 and j["status"] == "needs_review" and not j["check_fails"], j)
check("사람이 고친 설명은 원문 대조로 막지 않는다", not any(str(x).startswith("src") for x in j["check_fails"]))
check("edited 표시", j["edited"] is True)

print("3. 부제목·문제의도 저장")
check("PATCH 로 보낸 부제목·문제의도가 항목에 돌아온다", r["p3"][1]["subtitle"] == "합 구하기" and r["p3"][1]["intent"] == "덧셈 출력 이해", (r["p3"][1]["subtitle"], r["p3"][1]["intent"]))
check("부제목만 다시 고치면 문제의도는 그대로 둔다", r["p4"]["subtitle"] == "합 구하기 2" and r["p4"]["intent"] == "덧셈 출력 이해", (r["p4"]["subtitle"], r["p4"]["intent"]))
check("목록 조회에서도 같다", r["listed"]["subtitle"] == "합 구하기 2" and r["listed"]["review"]["사람입력"]["문제의도"] == "덧셈 출력 이해")
check("엑셀의 부제목이 있는 항목은 그 값이 기본값", r["rev_item"]["subtitle"] == "엑셀 부제목", r["rev_item"]["subtitle"])

check("묶인 설명(JSON)을 보내도 본문만 검사·저장하고 부제목·의도는 따로 보관한다", r["p5"][0] == 200 and r["p5"][1]["payload"]["description"] == "두 수의 합을 출력하시오." and r["p5"][1]["subtitle"] == "프론트 부제목" and r["p5"][1]["intent"] == "프론트 의도" and r["p5"][1]["status"] == "needs_review", r["p5"][1] if r["p5"][0] == 200 else r["p5"])
print("4. 그림(image_url) 저장")
check("http(s) 가 아닌 image_url 은 422", r["bad_img"] == 422, r["bad_img"])
res = {x["item_id"]: x for x in r["approve"]["results"]}
check("승인하면 둘 다 등록된다", r["approve"]["summary"] == {"registered": 2}, r["approve"])
db = {t: (u, d) for t, u, d in r["db"]}
mine = [x for x in r["db"] if x[1] == IMG]
check("문제 테이블 image_url 에 주소가 저장된다", len(mine) == 1, r["db"])
if mine:
    desc = json.loads(mine[0][2])
    check("설명 JSON 에 사람이 고친 부제목·문제의도·본문이 들어간다", desc == {"intent": "프론트 의도", "subtitle": "프론트 부제목", "content": "두 수의 합을 출력하시오."}, desc)
    check("제목은 영문·숫자 코드", __import__("re").fullmatch(r"[A-Z]+\d+_\d{4}", mine[0][0]) is not None, mine[0][0])
other = [x for x in r["db"] if x[1] != IMG]
check("엑셀 부제목 문제는 엑셀 값이 설명 JSON 에 들어간다", other and json.loads(other[0][2])["subtitle"] == "엑셀 부제목", other)

print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
