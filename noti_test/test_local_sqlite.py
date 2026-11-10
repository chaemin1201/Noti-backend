"""로컬 통합 테스트: 실제 모델·crud·라우터를 실제 DB(기본: SQLite 메모리)에 연결해 문제 등록을 시험한다.
noti_test 폴더에서 실행:
  pip install aiosqlite            # SQLite 로 시험할 때만
  python test_local_sqlite.py                                     # SQLite (Postgres 전용 타입은 JSON 으로 대체)
  python test_local_sqlite.py --db postgresql+asyncpg://user:pw@localhost/testdb   # 실제 Postgres (테스트 전용 DB 사용!)
적용하지 않은 기능은 ⏭ 로 표시하고(실패가 아님), 마지막에 적용 안 된 기능 목록을 보여 준다."""
import argparse, asyncio, importlib.util, json, os, sys, types
try:                                   # Windows 콘솔(cp949)에서도 ✅ ❌ 가 깨지거나 오류 나지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_HERE = os.path.dirname(os.path.abspath(__file__))
def package_dirs(c):
    """중첩(inputdata/inputdata, models/models)과 평면(inputdata, models) 구조를 모두 받는다. _bootstrap.package_dirs 와 같다."""
    pick = lambda *cands, marker: next((d for d in cands if os.path.isfile(os.path.join(d, marker))), None)
    return (pick(os.path.join(c, "inputdata", "inputdata"), os.path.join(c, "inputdata"), marker="schemas.py"),
            pick(os.path.join(c, "models", "models"), os.path.join(c, "models"), marker="problem.py"))
ROOT = next((c for c in (_HERE, os.path.dirname(_HERE)) if all(package_dirs(c))), _HERE)
ap = argparse.ArgumentParser(); ap.add_argument("--db", default="sqlite+aiosqlite:///:memory:")
ap.add_argument("--users", default="u1,u2", help="user 테이블에 이미 있는 사용자 ID 2개(쉼표). Postgres 에서는 실제 사용자 ID 를 넣으세요")
args = ap.parse_args()
U1, U2 = (args.users.split(",") + ["u2"])[:2]
USE_SQLITE = args.db.startswith("sqlite")
try:
    import pandas
except ImportError:
    sys.modules["pandas"] = types.ModuleType("pandas")      # 라우터가 import 만 하고 쓰지 않는 패키지
if USE_SQLITE:   # 모델을 import 하기 전에 Postgres 전용 타입(ARRAY, JSONB)을 JSON 으로 대체
    import sqlalchemy, sqlalchemy.dialects.postgresql as pg
    from sqlalchemy.types import JSON, TypeDecorator
    class JSONArray(TypeDecorator):
        impl = JSON; cache_ok = True
        def __init__(self, item_type=None, *a, **k): super().__init__()
    sqlalchemy.ARRAY = JSONArray; pg.JSONB = JSON

def _virtual_app():
    """보내주신 zip 의 폴더(models/models, inputdata/inputdata)만 있고 app 패키지가 없을 때,
    폴더를 코드가 기대하는 app.* 경로에 연결하고 app.database / app.security 는 임시로 대신 만든다."""
    def pkg(name, path=None):
        m = types.ModuleType(name); m.__path__ = [path] if path else []; sys.modules[name] = m; return m
    app = pkg("app"); pkg("app.problem"); pkg("app.security")
    _ind, _mod = package_dirs(ROOT)
    pkg("app.problem.models", _mod)
    pkg("app.inputdata", _ind)
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase):
        pass
    async def get_db():
        yield None
    db = types.ModuleType("app.database"); db.Base, db.get_db = Base, get_db; sys.modules["app.database"] = db; app.database = db
    sec = types.ModuleType("app.security.security"); sec.get_current_user = lambda: {"sub": "stub"}; sys.modules["app.security.security"] = sec
    print("[독립 실행 모드] app 패키지가 없어 폴더를 app.* 로 연결했습니다:", package_dirs(ROOT)[1], "·", package_dirs(ROOT)[0])

sys.path.insert(0, ROOT)
if importlib.util.find_spec("app") is None:
    if not all(package_dirs(ROOT)):
        raise SystemExit("app 패키지도 없고 models/models, inputdata/inputdata 폴더도 이 파일 옆에 없습니다. 테스트 파일을 'Noti backend' 폴더에 두고 실행하세요.")
    _virtual_app()
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
if "user" not in Base.metadata.tables:                      # 프로젝트에 User 모델이 없을 때만 임시로 만든다
    class _User(Base):
        __tablename__ = "user"
        user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem
from app.inputdata.schemas import InputDataRequest, problem_adapter
from app.inputdata.routers.inputdata import input_data_endpoint
from pydantic import ValidationError

# ---- 적용 여부 감지 ----
HAS_DEDUPE = importlib.util.find_spec("app.inputdata.dedupe") is not None
def accepts(d):
    try: problem_adapter.validate_python(d); return True
    except ValidationError: return False
BASE = dict(problemType="코딩", title="t", description="d", test_cases=[{"input": "1", "expected_output": "1"}], reference_codes=[{"language": "python", "code": "print(1)"}])
HAS_GRAPHIC = accepts({**BASE, "test_cases": [], "problem_condition": ["[필수] 반복문 사용"]})
HAS_INPUT_NULL = accepts({**BASE, "test_cases": [{"input": None, "expected_output": "x"}]})
HAS_NORMALIZE = accepts({**BASE, "rating_mode": "Regex", "difficulty": "Easy"})

passed = failed = skipped = 0; unapplied = {}
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")
def skip(name, feature):
    global skipped; skipped += 1; unapplied[feature] = unapplied.get(feature, 0) + 1; print(f"  ⏭ {name}  (미적용: {feature})")

async def send(S, problems, user=None):
    async with S() as db:
        return await input_data_endpoint(InputDataRequest(problems=problems), {"sub": user or U1}, db)
async def rows(S, **where):
    async with S() as db:
        return (await db.execute(select(Problem))).scalars().all()

async def main():
    engine = create_async_engine(args.db)
    async with engine.begin() as conn:
        if not USE_SQLITE:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine, expire_on_commit=False)
    if Base.metadata.tables["user"].c.keys() == ["user_id"]:       # 임시 user 테이블일 때만 사용자 행을 만든다
        async with S() as db:
            for u in (U1, U2): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
            await db.commit()

    print("1. 유형별 등록 (실제 DB 에 저장되고 다시 읽히는가)")
    batch = [
        dict(problemType="코딩", title="코딩-1", description="합을 출력", difficulty="easy", tags=["입출력"], rating_mode="none", problem_condition=["[필수] for 반복문 사용"],
             test_cases=[{"input": "1 2", "expected_output": "3", "is_hidden": False}], reference_codes=[{"language": "python", "code": "print(3)", "is_main": True}]),
        dict(problemType="디버깅", title="디버깅-1", description="오류 수정", rating_mode="none", test_cases=[{"input": "", "expected_output": "1"}],
             base_code=[{"language": "python", "code": "print(", "is_main": False}], reference_codes=[{"language": "python", "code": "print(1)"}]),
        dict(problemType="객관식", title="객관식-1", description="고르세요", options=["a", "b", "c"], correct_answers=[1]),
        dict(problemType="단답형", title="단답형-1", description="출력 함수", answer_text=["print", "print()"]),
        dict(problemType="단답형", title="단답형-2", description="번호별", answer_text={"1": ["97531"], "2": ["87"]}),
        dict(problemType="주관식", title="주관식-1", description="설명하시오", answer_text="모범답안", grading_criteria=["요소 1"]),
    ]
    r = await send(S, batch)
    check("6개 유형 모두 등록", r["status"] == "success" and r["created"] == 6, r)
    got = {p.title: p for p in await rows(S)}
    check("DB 에서 읽으면 유형별 클래스로 돌아옴 (polymorphic)", [type(got[t]).__name__ for t in ("코딩-1", "디버깅-1", "객관식-1", "단답형-1", "주관식-1")] == ["CodingProblem", "DebuggingProblem", "MultipleChoiceProblem", "ShortAnswerProblem", "SubjectiveProblem"], {t: type(p).__name__ for t, p in got.items()})
    c = got["코딩-1"]
    check("코딩: 테스트 케이스·정답코드·조건·태그 저장", c.test_cases[0]["expected_output"] == "3" and c.reference_codes[0]["code"] == "print(3)" and c.problem_condition == ["[필수] for 반복문 사용"] and c.tags == ["입출력"], (c.test_cases, c.tags))
    check("디버깅: base_code 저장", got["디버깅-1"].base_code[0]["code"] == "print(")
    check("객관식: 보기와 정답 인덱스 저장", got["객관식-1"].options == ["a", "b", "c"] and got["객관식-1"].correct_answers == [1])
    check("단답형: 허용 답안 리스트와 번호별 dict 저장", got["단답형-1"].answer_text == ["print", "print()"] and got["단답형-2"].answer_text == {"1": ["97531"], "2": ["87"]})
    check("주관식: 모범답안·채점기준 저장", got["주관식-1"].answer_text == "모범답안" and got["주관식-1"].grading_criteria == ["요소 1"])
    check("maker_id 가 요청한 사용자로 저장", all(p.maker_id == U1 for p in got.values()))

    print("2. 입력 검증")
    r = await send(S, [dict(BASE, title="")]); check("빈 제목은 오류(필드 title 로 안내)", r["status"] == "failure" and any(e["field"] == "title" for e in r["errors"][0]["error"]), r)
    r = await send(S, [{k: v for k, v in BASE.items() if k != "description"}]); check("설명 없음은 오류", r["status"] == "failure", r)
    r = await send(S, [dict(BASE, title="부가정보", subtitle="부제목", intent="의도", points=5)])
    p = next(x for x in await rows(S) if x.title == "부가정보"); check("부제목·출제의도·배점은 오류 없이 무시되고 저장되지 않음", r["status"] == "success" and not hasattr(p, "subtitle"))
    r = await send(S, [dict(problemType="객관식", title="범위초과", description="d", options=["a", "b"], correct_answers=[2])]); check("객관식 정답 인덱스 범위 초과는 오류", r["status"] == "failure", r)

    print("3. 수정이 필요한 항목 (적용 여부를 자동 감지)")
    if HAS_GRAPHIC:
        r = await send(S, [dict(BASE, title="그래픽-1", test_cases=[], problem_condition=["[필수] 반복문 사용"])]); g = next(x for x in await rows(S) if x.title == "그래픽-1")
        check("그래픽 문제(테스트 케이스 없음)가 등록됨", r["created"] == 1 and g.test_cases == [], r)
    else: skip("그래픽 문제(테스트 케이스 없음) 등록", "그래픽 문제 허용")
    if HAS_INPUT_NULL:
        r = await send(S, [dict(BASE, title="입력없음-1", test_cases=[{"input": None, "expected_output": "x"}])]); g = next(x for x in await rows(S) if x.title == "입력없음-1")
        check("입력 null 이 빈 문자열로 저장됨", r["created"] == 1 and g.test_cases[0]["input"] == "", r)
    else: skip("테스트 케이스 입력이 null 이어도 등록", "입력 null 처리")
    if HAS_NORMALIZE:
        r = await send(S, [dict(BASE, title="정규화-1", rating_mode="Regex", difficulty="Easy")]); g = next(x for x in await rows(S) if x.title == "정규화-1")
        check("rating_mode Regex → regex, 난이도 Easy → easy 로 저장", r["created"] == 1 and g.difficulty == "easy" and getattr(g.rating_mode, "value", g.rating_mode) == "regex", (g.difficulty, g.rating_mode))
    else: skip("채점 모드·난이도 대소문자 정규화", "정규화")
    if HAS_DEDUPE:
        r = await send(S, [dict(BASE, title="중복-1")]); r2 = await send(S, [dict(BASE, title="중복-1")])
        n = len([x for x in await rows(S) if x.title == "중복-1"])
        check("같은 문제를 다시 보내면 건너뜀(실제 DB 쿼리)", r["created"] == 1 and r2["skipped_duplicates"] == 1 and n == 1, (r2, n))
        r3 = await send(S, [dict(BASE, title="중복-1")], user=U2); check("다른 사용자는 같은 문제를 등록할 수 있음", r3["created"] == 1, r3)
        async with S() as db:
            await db.execute(text("UPDATE problem SET is_deleted = :t WHERE title = '중복-1' AND maker_id = :m"), {"t": True, "m": U1}); await db.commit()
        r4 = await send(S, [dict(BASE, title="중복-1")]); check("삭제한 문제는 다시 등록할 수 있음", r4["created"] == 1, r4)
        mixed = await send(S, [dict(BASE, title="혼합-신규"), dict(BASE, title="혼합-신규"), dict(BASE, title="")])
        check("신규 1 · 같은 요청 안 중복 1 · 오류 1 → partial", mixed["status"] == "partial" and mixed["created"] == 1 and mixed["skipped_duplicates"] == 1 and mixed["failed"] == 1, mixed)
    else: skip("중복 등록 방지 (재전송, 사용자별, 삭제 후 재등록)", "중복 방지")
    await engine.dispose()
    print(f"\n결과: 통과 {passed} · 실패 {failed} · 미적용 {skipped}")
    if unapplied: print("적용되지 않은 기능:", ", ".join(f"{k}({v}개 테스트)" for k, v in unapplied.items()))
    return failed
sys.exit(1 if asyncio.run(main()) else 0)
