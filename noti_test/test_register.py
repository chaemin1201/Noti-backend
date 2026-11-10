"""등록 흐름 테스트: register.py → 실제 라우터(FastAPI) → 가짜 DB 세션.
noti_test 폴더에서 실행: python test_register.py   (httpx 필요)"""
import json, os, sys, types
import _bootstrap; _bootstrap.setup(); _bootstrap.require("중복 방지", "그래픽 문제 허용")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.inputdata.routers.inputdata import router
from app.database import get_db
from app.security.security import get_current_user
from register import load_cases, split_cases, register

class _Nested:
    def __init__(self, s): self.s = s
    async def __aenter__(self): self.mark = len(self.s.rows); return self
    async def __aexit__(self, et, ev, tb):
        self.s._pending = []
        if et: del self.s.rows[self.mark:]
        return False
class FakeSession:
    def __init__(self): self.rows, self._pending = [], []
    def add(self, o): self._pending.append(o)
    async def flush(self):
        for o in self._pending:
            o.problem_id = len(self.rows) + 1
            if getattr(o, "is_deleted", None) is None: o.is_deleted = False
            self.rows.append(o)
        self._pending = []
    async def scalar(self, stmt):
        p = stmt.compile().params
        h = [v for k, v in p.items() if "temporary_field_str_2" in k][0]; m = [v for k, v in p.items() if k.startswith("maker_id")][0]
        for o in self.rows:
            if o.temporary_field_str_2 == h and o.maker_id == m and not o.is_deleted: return o.problem_id
    def begin_nested(self): return _Nested(self)
    async def commit(self): pass

db = FakeSession()
app = FastAPI(); app.include_router(router)
app.dependency_overrides[get_db] = lambda: db
app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
client = TestClient(app)
post = lambda body: client.post("/inputdata", json=body).json()

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")
by = lambda res: {r["id"]: r for r in res}

print("1. 정상 사례(golden) 등록")
send, blocked, hold = split_cases(load_cases("golden_cases.jsonl"))
check("등록 대상 9 · 막힘 0 · 보류 1", (len(send), len(blocked), len(hold)) == (9, 0, 1), (len(send), len(blocked), len(hold)))
res = register(send, post)
check("9개 모두 created", all(r["result"] == "created" for r in res), [(r["id"], r["result"], r.get("error")) for r in res])
check("그래픽 문제(test_cases 없음)도 등록됨", by(res)["TT11-0001"]["result"] == "created")
check("단답형 dict 도 등록됨", by(res)["PY43-0002"]["result"] == "created")
check("DB 에 9건", len(db.rows) == 9)
check("조건이 문자열로 저장됨", db.rows[0].problem_condition[0].startswith("[필수]"))

print("2. 같은 파일 다시 실행")
res = register(send, post)
check("9개 모두 duplicate", all(r["result"] == "duplicate" for r in res), [(r["id"], r["result"]) for r in res])
check("DB 건수 그대로", len(db.rows) == 9)

print("3. 틀린 사례(bad) — 검사기가 등록 전에 막음")
send, blocked, hold = split_cases(load_cases("bad_cases.jsonl"))
check("정상 1건만 통과 · 11건 막힘 · 1건 보류(BAD-8 은 보류라 payload 가 있어도 보내지 않음)", (len(send), len(blocked), len(hold)) == (1, 11, 1), (len(send), len(blocked), len(hold)))
check("정상 1건은 이미 등록돼 duplicate", register(send, post)[0]["result"] == "duplicate")

print("4. 검사를 건너뛰면 (--skip-check) 무슨 일이 생기나")
cases = {c["id"]: c for c in load_cases("bad_cases.jsonl")}
bad1, bad3 = cases["BAD-1 정답코드가 틀림(0부터 센 경우)"], cases["BAD-3 객관식 정답 인덱스 범위 초과(1부터 센 경우)"]
r = register([bad1, bad3], post)
check("API 는 틀린 정답코드를 그대로 등록함 (검사기가 필요한 이유)", r[0]["result"] == "created", r[0])
check("API 는 객관식 범위 초과를 오류로 돌려줌", r[1]["result"] == "error", r[1])
check("오류에 필드 경로(문제 전체)와 사유가 있음", "정답 번호" in json.dumps(r[1]["error"], ensure_ascii=False), r[1]["error"])

print("5. 배치 분할")
db2_before = len(db.rows)
many = []
for i in range(5):
    c = json.loads(json.dumps(load_cases("golden_cases.jsonl")[0], ensure_ascii=False))
    c["id"] = f"N{i}"; c["payload"]["title"] = f"배치-{i}"; many.append(c)
r = register(many, post, batch_size=2)       # 2+2+1 로 나눠 전송
check("5개를 2개씩 나눠 보내도 모두 created", [x["result"] for x in r] == ["created"] * 5, [x["result"] for x in r])
check("순서와 결과가 짝지어짐", [x["id"] for x in r] == [f"N{i}" for i in range(5)])
check("DB 에 5건 추가", len(db.rows) - db2_before == 5)

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
