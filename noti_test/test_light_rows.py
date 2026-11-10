"""완성된 엑셀·DB 행을 서버가 직접 구성하고 AI 에는 메타 정보(난이도·태그·부제목·문제의도)만 짧게 묻는 경로 시험 (가짜 AI).
noti_test 폴더에서:  python test_light_rows.py        (httpx, aiosqlite 필요)"""
import asyncio, csv, io, json, os, sys
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
from app.inputdata.intake import router as intake_router, service, config
os.environ["INTAKE_FILL_META"] = "off"          # 이 시험은 호출 횟수를 세므로 부제목·문제의도를 채우는 추가 호출은 끈다 (test_meta_fill.py 가 따로 확인)
from app.inputdata.intake.checks import fix

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
def rec(**f):
    base = {"이름": "L_01", "유형": "코딩", "설명": "1부터 10까지 합을 출력하시오", "정답코드": "print(55)", "출력": "55", "언어": "Python"}
    base.update(f)
    return {"입력종류": "엑셀", "key": base["이름"], "fields": base, "intake": {"유형": base["유형"], "유형추정": False, "필수누락": [], "메모": []}}

print("1. 완성된 행 판정과 payload 구성")
r = fix.light_payload(rec(), "none")
check("이름·설명·정답 코드·출력이 있으면 서버가 payload 를 만든다 (메타 4개가 비어 있음)", r is not None and r[0]["problemType"] == "코딩" and r[0]["title"] == "L_01"
      and r[0]["test_cases"] == [{"input": "", "expected_output": "55", "is_hidden": False}] and r[0]["reference_codes"][0]["language"] == "python" and r[1] == ["difficulty", "tags", "subtitle", "intent"], r)
full = fix.light_payload(rec(난이도="하", 태그="반복문, 합", 부제목="합", 문제의도="반복"), "none")
check("난이도·태그·부제목·문제의도가 엑셀에 있으면 AI 에게 물을 것이 없다", full is not None and full[1] == [] and full[0]["difficulty"] == "easy" and full[0]["tags"] == ["반복문", "합"], full)
check("태그 없는 조건 글이 있으면 AI 가 판단해야 하므로 해당하지 않는다", fix.light_payload(rec(조건="정수만 입력"), "none") is None)
check("태그가 붙은 조건은 그대로 쓴다", fix.light_payload(rec(조건="[필수] for 사용" + NL + "[금지] while 사용"), "none")[0]["problem_condition"] == ["[필수] for 사용", "[금지] while 사용"])
check("정답 코드나 출력이 없으면 해당하지 않는다", fix.light_payload(rec(정답코드=""), "none") is None and fix.light_payload(rec(출력=""), "none") is None)
bad = rec(); bad["intake"]["메모"] = ["풀이 방식이 여러 개 → 문제 분할 후보"]
check("서버 메모(분할 후보 등)가 있으면 해당하지 않는다", fix.light_payload(bad, "none") is None)
check("엑셀+원본(둘 다)과 그림이 붙은 행은 해당하지 않는다", fix.light_payload({**rec(), "입력종류": "둘 다"}, "none") is None and fix.light_payload({**rec(), "이미지": [{"n": 1}]}, "none") is None)
check("디버깅은 제공 코드가 있어야 하고, 있으면 base_code 로 옮긴다", fix.light_payload(rec(유형="디버깅"), "none") is None and fix.light_payload(rec(유형="디버깅", 제공코드="print(0)"), "none")[0]["base_code"][0]["code"] == "print(0)")
mc = fix.light_payload(rec(유형="객관식", 보기="① 가" + NL + "② 나" + NL + "③ 다", 정답="2", 정답코드="", 출력=""), "none")
check("객관식은 보기 기호를 지우고 정답 번호(1부터)를 인덱스로 바꾼다", mc is not None and mc[0]["options"] == ["가", "나", "다"] and mc[0]["correct_answers"] == [1], mc)
check("주관식·단답형은 AI 가 판단하므로 해당하지 않는다", fix.light_payload(rec(유형="주관식", 정답="답"), "none") is None)

print("2. 메타 응답 읽기")
check("JSON 이 코드 펜스에 싸여 와도 읽고, 허용되지 않는 난이도는 버린다", fix.parse_meta(chr(96) * 3 + 'json' + NL + '{"difficulty":"Easy","tags":["반복문","합","a","b","c"],"subtitle":" 합 ","intent":"반복"}' + NL + chr(96) * 3)
      == {"difficulty": "easy", "tags": ["반복문", "합", "a", "b"], "subtitle": "합", "intent": "반복"})
check("읽을 수 없는 응답은 빈 값", fix.parse_meta("모르겠습니다") == {} and fix.parse_meta('{"difficulty":"어려움"}') == {})
row = fix.light_row(rec(), r[0], {"difficulty": "medium", "tags": ["반복문"], "subtitle": "합", "intent": "반복"}, r[1])
check("메타는 payload(난이도·태그)와 채움(부제목·문제의도 포함)에 들어간다", row["payload"]["difficulty"] == "medium" and row["payload"]["tags"] == ["반복문"]
      and {e["항목"] for e in row["review"]["채움"]} == {"difficulty", "tags", "부제목", "문제의도"} and row["review"]["상태"] == "등록가능", row)

print("3. 업로드 흐름: 가벼운 호출만 하는 행, AI 를 안 부르는 행, 일반 호출로 가는 행")
HEAD = ["이름", "유형", "설명", "정답코드", "입력", "출력", "조건", "난이도", "태그", "부제목", "문제의도", "언어"]
ROWS = [["L_01", "코딩", "1부터 10까지 합을 출력하시오", "print(55)", "", "55", "", "", "", "", "", "Python"],
        ["L_02", "코딩", "1부터 5까지 합을 출력하시오", "print(15)", "", "15", "", "하", "반복문", "합", "반복", "Python"],
        ["L_03", "코딩", "정수 n 을 입력받아 출력하시오", "print(int(input()))", "3", "3", "정수만 입력", "", "", "", "", "Python"]]
buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD); [w.writerow(x) for x in ROWS]
CSV = buf.getvalue().encode("utf-8-sig")
CALLS = {"meta": 0, "full": 0}
def fake_ai(user, images=None, info=None, system=None):
    if system:
        CALLS["meta"] += 1
        return json.dumps({"difficulty": "medium", "tags": ["반복문", "합"], "subtitle": "합 구하기", "intent": "반복문으로 누적하기"}, ensure_ascii=False)
    CALLS["full"] += 1
    r0 = json.loads(user.split("입력: ", 1)[1]); f = r0["fields"]
    p = {"problemType": "코딩", "title": f["이름"], "description": f["설명"], "rating_mode": "none", "problem_condition": ["[필수] 정수만 입력받기"],
         "test_cases": [{"input": f.get("입력", ""), "expected_output": f["출력"], "is_hidden": False}], "reference_codes": [{"language": "python", "code": f["정답코드"], "is_main": True}]}
    return json.dumps({"id": f["이름"], "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)

async def run(ai, label="문제.csv"):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    service._default_ai = lambda: (ai, "fake")
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    r = await c.post("/intake/jobs", files=[("files", (label, CSV, "text/csv"))])
    job = r.json()["job_id"]
    for _ in range(200):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    items = (await c.get(f"/intake/jobs/{job}/items")).json()
    await engine.dispose()
    return j, {i["result_id"]: i for i in items}

CALLS.update(meta=0, full=0)
j, it = asyncio.run(run(fake_ai))
check("3행이 모두 처리된다", j["status"] == "done" and len(it) == 3, (j["status"], list(it)))
check("가벼운 호출 1번(L_01) + 일반 호출 1번(L_03, 조건이 태그 없는 글). L_02 는 AI 를 부르지 않는다", CALLS == {"meta": 1, "full": 1}, CALLS)
p1 = it["L_01"]["payload"]
check("L_01: 엑셀 값 그대로에 메타만 AI 값", p1["test_cases"][0]["expected_output"] == "55" and p1["difficulty"] == "medium" and p1["tags"] == ["반복문", "합"], p1)
p2 = it["L_02"]["payload"]
check("L_02: 엑셀의 난이도(하)·태그를 그대로 쓴다", p2["difficulty"] == "easy" and p2["tags"] == ["반복문"], p2)
check("L_01 의 부제목·문제의도는 채움에 기록된다", {e["항목"] for e in it["L_01"]["review"]["채움"]} >= {"부제목", "문제의도"}, it["L_01"]["review"]["채움"])
check("세 문제 모두 승인 대기(코드 실행 검증이 꺼져 있음)", {i["status"] for i in it.values()} == {"needs_review"}, {k: v["status"] for k, v in it.items()})

def old_style_ai(user, images=None):                      # system 인자를 받지 못하는 AI 함수(옛 방식)는 가벼운 경로를 쓰지 않는다
    return fake_ai(user)
CALLS.update(meta=0, full=0)
j2, it2 = asyncio.run(run(old_style_ai))
check("system 인자를 받지 못하는 AI 함수면 일반 호출로만 처리한다 (3번)", CALLS == {"meta": 0, "full": 3} and len(it2) == 3, CALLS)

os.environ["INTAKE_LIGHT_ROWS"] = "off"
CALLS.update(meta=0, full=0)
j3, it3 = asyncio.run(run(fake_ai))
os.environ.pop("INTAKE_LIGHT_ROWS")
check("INTAKE_LIGHT_ROWS=off 이면 모두 일반 호출 (3번)", CALLS == {"meta": 0, "full": 3} and len(it3) == 3, CALLS)

def failing_meta_ai(user, images=None, info=None, system=None):
    if system: raise RuntimeError("메타 호출 실패")
    return fake_ai(user)
CALLS.update(meta=0, full=0)
j4, it4 = asyncio.run(run(failing_meta_ai))
check("가벼운 호출이 실패하면 일반 호출로 이어서 처리한다 (L_01 도 일반 호출)", CALLS["full"] == 2 and len(it4) == 3 and j4["status"] == "done", (CALLS, j4["status"]))
print("4. 유형 열이 없는 행(DB 등): 서버가 유형을 정한다")
def _db(**f):
    base = {"이름": "D_01", "설명": "d", "정답코드": "print(1)", "출력": "1", "언어": "Python"}
    base.update(f)
    return {"입력종류": "엑셀", "key": "D_01", "fields": base, "intake": {"유형": "코딩", "유형추정": True, "필수누락": ["유형"], "메모": []}}
check("유형 열이 없고 제공 코드도 없으면 코딩", fix.light_payload(_db(), "none")[0]["problemType"] == "코딩")
check("유형 열이 없고 제공 코드가 있으면 디버깅(프롬프트의 규칙)", fix.light_payload(_db(제공코드="print(0)"), "none")[0]["problemType"] == "디버깅")
_bad = _db(); _bad["intake"]["필수누락"] = ["유형", "정답코드"]
check("유형 말고 다른 필수 항목이 빠졌으면 해당하지 않는다", fix.light_payload(_bad, "none") is None)
_unk = _db(유형="이상한값");
check("알 수 없는 유형 값이 적혀 있으면 AI 가 판단한다", fix.light_payload(_unk, "none") is None)
print("5. 방식 분할이라면서 나머지 줄을 내지 않으면 다시 쓰게 한다")
check("'-1' 로 끝나는 혼자뿐인 결과는 다시 쓸 이유가 된다", service._split_fail({"payload": {"title": "A_01-1"}}, {"key": "A_01"}) != [] and service._split_fail({"payload": {"title": "A_01"}}, {"key": "A_01"}) == [] and service._split_fail({"payload": {"title": "A_01-1"}}, {"key": "A_01-1"}) == [])
_hold = {"id": "A_01-1", "payload": None, "review": {"상태": "보류", "보류사유": "풀이 방식이 둘 이상인데 문제 분할 필요"}}
check("분할이 필요하다는 이유로 보류한 결과는 다시 쓸 이유가 된다 (모델이 분할 대신 보류한 경우)", service._split_fail(_hold, {"key": "A_01"}) != [] and "보류 사유가 아닙니다" in service._split_fail(_hold, {"key": "A_01"})[0])
check("분할과 무관한 이유의 보류는 건드리지 않는다", service._split_fail({"payload": None, "review": {"상태": "보류", "보류사유": "본문이 그림뿐이라 읽을 수 없음"}}, {"key": "A_01"}) == [])
SPLIT_CALLS = {"n": 0}
def split_ai(user, images=None, info=None, system=None):
    if system: return json.dumps({"difficulty": "easy", "tags": ["반복문"], "subtitle": "합", "intent": "반복"}, ensure_ascii=False)
    SPLIT_CALLS["n"] += 1
    r0, _end = json.JSONDecoder().raw_decode(user.split("입력: ", 1)[1]); f = r0["fields"]
    def one(name):
        p = {"problemType": "코딩", "title": name, "description": f["설명"], "rating_mode": "none", "problem_condition": ["[필수] 정수만 입력받기"],
             "test_cases": [{"input": f.get("입력", ""), "expected_output": f["출력"], "is_hidden": False}], "reference_codes": [{"language": "python", "code": f["정답코드"], "is_main": True}]}
        return json.dumps({"id": name, "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)
    if "[서버 검사 결과]" in user: return one(f["이름"] + "-1") + NL + one(f["이름"] + "-2")
    return one(f["이름"] + "-1")
SPLIT_CALLS["n"] = 0
j5, it5 = asyncio.run(run(split_ai))
check("첫 결과가 혼자뿐인 '-1' 이면 다시 쓰게 하고, 두 줄(-1, -2)이 모두 저장된다", j5["status"] == "done" and "L_03-1" in it5 and "L_03-2" in it5, (j5["status"], list(it5)))

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
