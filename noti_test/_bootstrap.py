"""테스트 공통 준비. 'app' 패키지가 없는 폴더(보내주신 Noti backend 폴더만 있는 경우)에서도 실행되게 한다.

- models/models, inputdata/inputdata (또는 models, inputdata 에 코드가 바로 있는 평면 구조) 폴더를 코드가 기대하는 app.* 경로에 연결한다.
- app.database(Base, get_db), app.security.security(get_current_user)는 임시로 대신 만든다.
- 'app' 패키지가 이미 있는 실제 프로젝트에서는 아무것도 바꾸지 않는다.
"""
import importlib.util, os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))


def package_dirs(c):
    """(inputdata 패키지 폴더, models 패키지 폴더). 중첩 구조(inputdata/inputdata, models/models)와
    평면 구조(inputdata, models 바로 아래에 코드)를 모두 받는다. 없으면 None."""
    def pick(*cands, marker):
        return next((d for d in cands if os.path.isfile(os.path.join(d, marker))), None)
    return (pick(os.path.join(c, "inputdata", "inputdata"), os.path.join(c, "inputdata"), marker="schemas.py"),
            pick(os.path.join(c, "models", "models"), os.path.join(c, "models"), marker="problem.py"))


def find_root():
    for c in (os.path.dirname(HERE), HERE, os.getcwd()):
        if all(package_dirs(c)): return c
    return None


ROOT = find_root()


def _virtual_app(root):
    def pkg(name, path=None):
        m = types.ModuleType(name); m.__path__ = [path] if path else []; sys.modules[name] = m; return m
    app = pkg("app"); pkg("app.problem"); pkg("app.security")
    ind, mod = package_dirs(root)
    pkg("app.problem.models", mod)
    pkg("app.inputdata", ind)
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase):
        pass
    async def get_db():
        yield None
    db = types.ModuleType("app.database"); db.Base, db.get_db = Base, get_db; sys.modules["app.database"] = db; app.database = db
    sec = types.ModuleType("app.security.security"); sec.get_current_user = lambda: {"sub": "stub"}; sys.modules["app.security.security"] = sec


def sqlite_shims():
    """모델을 import 하기 전에 Postgres 전용 타입(ARRAY, JSONB)을 JSON 으로 대체한다 (SQLite 시험용)."""
    import sqlalchemy, sqlalchemy.dialects.postgresql as pg
    from sqlalchemy.types import JSON, TypeDecorator
    class JSONArray(TypeDecorator):
        impl = JSON; cache_ok = True
        def __init__(self, item_type=None, *a, **k): super().__init__()
    sqlalchemy.ARRAY = JSONArray; pg.JSONB = JSON


_done = False
def setup(sqlite=False):
    global _done
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # Windows 콘솔(cp949)에서도 이모지 출력
    except Exception:
        pass
    if _done: return ROOT
    try:
        import pandas
    except ImportError:
        sys.modules["pandas"] = types.ModuleType("pandas")             # 라우터가 import 만 하고 쓰지 않는 패키지
    if HERE not in sys.path: sys.path.insert(0, HERE)
    if ROOT and ROOT not in sys.path: sys.path.insert(0, ROOT)
    if sqlite: sqlite_shims()
    if "app" not in sys.modules and importlib.util.find_spec("app") is None:
        if not ROOT:
            raise SystemExit("app 패키지도 없고 models/models, inputdata/inputdata 폴더도 찾지 못했습니다. noti_test 폴더를 'Noti backend' 폴더 안에 두세요.")
        _virtual_app(ROOT)
    _done = True
    return ROOT


def features():
    """수정본이 적용됐는지 (기능별)."""
    setup()
    from pydantic import ValidationError
    from app.inputdata.schemas import problem_adapter
    base = dict(problemType="코딩", title="t", description="d", test_cases=[{"input": "1", "expected_output": "1"}], reference_codes=[{"language": "python", "code": "print(1)"}])
    def accepts(d):
        try: problem_adapter.validate_python(d); return True
        except ValidationError: return False
    return {
        "중복 방지": importlib.util.find_spec("app.inputdata.dedupe") is not None,
        "문제지 업로드 기능": importlib.util.find_spec("app.inputdata.intake") is not None,
        "그래픽 문제 허용": accepts({**base, "test_cases": [], "problem_condition": ["[필수] 반복문 사용"]}),
        "입력 null 처리": accepts({**base, "test_cases": [{"input": None, "expected_output": "x"}]}),
        "정규화": accepts({**base, "rating_mode": "Regex", "difficulty": "Easy"}),
    }


def require(*names):
    """필요한 수정본 기능이 적용되지 않았으면 안내하고 종료 코드 2(건너뜀)로 끝낸다."""
    f = features(); missing = [n for n in names if not f[n]]
    if missing:
        print(f"⏭ 건너뜀: 수정본이 아직 적용되지 않았습니다 → {', '.join(missing)}\n   apply 폴더의 파일을 프로젝트에 복사하면 실행됩니다 (README.md 참고).")
        sys.exit(2)
