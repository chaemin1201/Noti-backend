"""등록 제목 코드(언어+주제 번호_순번)와 부제목 이동 시험 (SQLite).
noti_test 폴더에서:  python test_title_code.py"""
import asyncio, json, os, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401
from app.inputdata.intake import service, models
from app.inputdata.intake.checks import fix

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

print("1. 제목 코드 계산 (DB 없이)")
def ti(orig, lang="python", rec_extra=None):
    rec = {"입력종류": "원본", "id": orig, "key": orig, **(rec_extra or {})}
    return fix.title_info(rec, {"title": orig, "reference_codes": [{"language": lang}]})
check("PY41-0001 → PY41, 이름 없음(AI 키워드가 부제목)", ti("PY41-0001")["코드접두"] == "PY41" and ti("PY41-0001")["읽을이름"] == "")
check("방식 분할 PY41-0001-2 도 같은 접두", ti("PY41-0001-2")["코드접두"] == "PY41")
check("NP11-0003 은 파이썬 코드이므로 언어는 PY, 주제 번호 11", ti("NP11-0003")["코드접두"] == "PY11")
check("JAVA01_01 변수 → JAVA1, 부제목 '변수'", ti("JAVA01_01 변수", "java")["코드접두"] == "JAVA1" and ti("JAVA01_01 변수", "java")["읽을이름"] == "변수")
check("C++_08_01 → CPP8", ti("C++_08_01", "cpp")["코드접두"] == "CPP8")
check("C_06_클래스와객체_02 → C6, 부제목 '클래스와객체'", ti("C_06_클래스와객체_02", "c")["코드접두"] == "C6" and ti("C_06_클래스와객체_02", "c")["읽을이름"] == "클래스와객체")
check("ID 가 없으면 제목 속 첫 숫자(5주차 → 5)", ti("5주차실습과제_01", "java")["코드접두"] == "JAVA5" and ti("5주차실습과제_01", "java")["주제번호확실"])
check("파일 이름 뒤에 서버가 붙인 문제 번호(_02)는 주제 번호가 아니다 → 0, 확실하지 않음", ti("혼합_문제지_02")["코드접두"] == "PY0" and ti("혼합_문제지_02")["주제번호확실"] is False)
check("언어를 알 수 없는 유형(코드 없음)은 ETC, 확실하지 않음", fix.title_info({"입력종류": "원본", "id": "혼합_문제지_02"}, {"title": "혼합_문제지_02"})["코드접두"] == "ETC0" and fix.title_info({"입력종류": "원본", "id": "PY41-0001"}, {"title": "PY41-0001"})["코드접두"] == "PY41")
check("언어를 몰라도 ID 머리글자가 언어면 쓴다 (JAVA01_01)", fix.title_info({"입력종류": "원본", "id": "JAVA01_01 변수"}, {"title": "JAVA01_01 변수"})["코드접두"] == "JAVA1")
check("숫자가 전혀 없으면 0 이고 '확실하지 않음'", ti("합계 구하기")["코드접두"] == "PY0" and ti("합계 구하기")["주제번호확실"] is False)

print("2. 부제목")
w = models.wrap({"description": "본문"}, {"fields": {}}, {"채움": [{"항목": "부제목", "내용": "for문, 합계"}]}, name="")
check("이름이 없으면 AI 키워드가 부제목", json.loads(w["description"])["subtitle"] == "for문, 합계")
w = models.wrap({"description": "본문"}, {"fields": {}}, {"채움": [{"항목": "부제목", "내용": "for문, 합계"}]}, name="변수")
check("원래 이름이 있으면 그것이 부제목", json.loads(w["description"])["subtitle"] == "변수")
w = models.wrap({"description": "본문"}, {"fields": {"부제목": "입력 부제목"}}, {}, name="변수")
check("입력(엑셀)에 부제목이 있으면 그것이 우선", json.loads(w["description"])["subtitle"] == "입력 부제목")

print("3. 번호 예약 (카운터 표) · 중복 방지")
import re
P = lambda t, d="두 수의 합을 출력하시오": {"problemType": "코딩", "title": t, "description": d, "rating_mode": "none", "problem_condition": ["[필수] 정수만 출력"], "difficulty": "easy", "tags": ["합"],
     "test_cases": [{"input": "", "expected_output": "3", "is_hidden": False}], "reference_codes": [{"language": "python", "code": "print(3)", "is_main": True}]}
async def mkdb(seq_table=True):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if not seq_table: await conn.execute(text("DROP TABLE problem_title_seq"))
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    return engine, S
async def scenario():
    engine, S = await mkdb()
    r = {}
    async with S() as db:
        a = await service.allocate_title(db, "PY41"); b = await service.allocate_title(db, "PY41"); c = await service.allocate_title(db, "PY4")
        r["seq"] = (a, b, c)
        st, _ = await service.register_payload(db, P(a), "u1", dedupe_title="PY41-0001"); await db.commit(); r["st1"] = st
        r["gap"] = await service.allocate_title(db, "PY41")                        # b 를 쓰지 않아도 다음은 0003 (빈 번호는 다시 쓰지 않는다)
        st2, _ = await service.register_payload(db, P(a, "다른 설명"), "u1", dedupe_title="PY41-0002"); r["taken"] = st2   # 같은 번호를 다른 문제가 쓰려 함
        await db.rollback()
        st3, _ = await service.register_payload(db, P(b), "u1", dedupe_title="PY41-0001"); r["dup"] = st3                    # 같은 문제를 새 번호로 다시 올림
        await db.rollback()
        r["same_hash_other_title"] = None
    await engine.dispose()
    return r
r = asyncio.run(scenario())
check("접두별로 1씩 늘어난다 (PY41_0001, PY41_0002) 접두가 다르면 따로 (PY4_0001)", r["seq"] == ("PY41_0001", "PY41_0002", "PY4_0001"), r)
check("쓰지 않고 버린 번호는 빈 번호로 남고 다시 쓰지 않는다", r["gap"] == "PY41_0003", r)
check("다른 문제가 이미 쓴 번호를 쓰려 하면 중복 문제가 아니라 '번호 겹침'으로 알려 준다", r["taken"] == service.TITLE_TAKEN, r)
check("같은 문제를 새 번호로 다시 올려도 원래 제목으로 비교해 중복으로 막는다", r["dup"] == service.DUPLICATE, r)

async def seed_scenario():
    engine, S = await mkdb()
    async with S() as db:
        for t in ("PY41_0007", "PY41_0003", "옛 한글 제목", "PY41-0001"):
            st, _ = await service.register_payload(db, P(t, "설명 " + t), "u1"); await db.commit()
        r = {"first": await service.allocate_title(db, "PY41")}                    # 이미 등록된 가장 큰 번호(0007)에서 이어 간다
    await engine.dispose()
    return r
r = asyncio.run(seed_scenario())
check("카운터가 비어 있어도 이미 등록된 가장 큰 번호 다음부터 (0008)", r["first"] == "PY41_0008", r)

async def many():
    engine, S = await mkdb()
    async def one():
        async with S() as db:
            t = await service.allocate_title(db, "PY9"); await db.commit(); return t
    out = await asyncio.gather(*[one() for _ in range(20)])
    await engine.dispose()
    return out
out = asyncio.run(many())
check("세션 20개가 동시에 받아도 번호가 겹치지 않는다", len(set(out)) == 20, sorted(out))

async def no_table():
    engine, S = await mkdb(seq_table=False)
    async with S() as db:
        a = await service.allocate_title(db, "PY41")
        st, _ = await service.register_payload(db, P(a), "u1"); await db.commit()
        b = await service.allocate_title(db, "PY41")
    await engine.dispose()
    return a, b, st
a, b, st = asyncio.run(no_table())
check("카운터 표가 아직 없는 DB(마이그레이션 전)에서도 가장 큰 번호 + 1 로 동작한다", (a, b, st) == ("PY41_0001", "PY41_0002", service.REGISTERED), (a, b, st))

print("4. 처리 결과의 제목이 바로 코드로 바뀐다 (승인 화면에서도 영문·숫자)")
async def scenario2():
    engine, S = await mkdb()
    out = {}
    async with S() as db:
        rv = lambda: {"제목정보": fix.title_info({"입력종류": "원본", "id": "JAVA01_01 변수"}, {"title": "JAVA01_01 변수", "reference_codes": [{"language": "java"}]})}
        a, b = {"title": "JAVA01_01 변수"}, {"title": "JAVA01_02 반복문"}
        ra, rb = rv(), rv()
        await service._give_code_title(db, a, ra); await service._give_code_title(db, b, rb)
        out["a"], out["b"], out["ti"] = a["title"], b["title"], ra["제목정보"]
    await engine.dispose()
    return out
o = asyncio.run(scenario2())
check("같은 접두의 문제는 등록 전이라도 서로 다른 번호 (JAVA1_0001, JAVA1_0002)", (o["a"], o["b"]) == ("JAVA1_0001", "JAVA1_0002"), o)
check("제목에 한글·공백·기호가 없다 (영문 대문자+숫자+_)", all(re.fullmatch(r"[A-Z]+\d+_\d{4}", x) for x in (o["a"], o["b"])), o)
check("원래 이름은 제목정보에 남는다 (부제목·중복 검사용)", o["ti"]["원래이름"] == "JAVA01_01 변수" and o["ti"]["읽을이름"] == "변수" and o["ti"]["등록제목"] == o["a"], o["ti"])
print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
