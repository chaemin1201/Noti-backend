import sys, types, asyncio
"""중복 방지 흐름 테스트. noti_test 폴더에서 실행: python test_inputdata_flow.py
DB 대신 가짜 세션을 쓰므로 실제 DB 연동은 검증하지 않습니다."""
import _bootstrap; _bootstrap.setup(); _bootstrap.require("중복 방지", "그래픽 문제 허용")

from app.inputdata.schemas import InputDataRequest
from app.inputdata.routers.inputdata import input_data_endpoint
from app.inputdata.dedupe import compute_content_hash

class _Nested:
    def __init__(self, s): self.s = s
    async def __aenter__(self): self.mark = len(self.s.rows); return self
    async def __aexit__(self, et, ev, tb):
        self.s._pending = []
        if et: del self.s.rows[self.mark:]
        return False

class FakeSession:
    """DB 대신 쓰는 가짜 세션: add/flush/scalar/commit/begin_nested 만 흉내냄"""
    def __init__(self): self.rows, self._pending, self.commits = [], [], 0
    def add(self, o): self._pending.append(o)
    async def flush(self):
        for o in self._pending:
            o.problem_id = len(self.rows) + 1
            if getattr(o, "is_deleted", None) is None: o.is_deleted = False
            self.rows.append(o)
        self._pending = []
    async def scalar(self, stmt):
        params = stmt.compile().params
        h = [v for k, v in params.items() if "temporary_field_str_2" in k][0]
        m = [v for k, v in params.items() if k.startswith("maker_id")][0]
        for o in self.rows:
            if o.temporary_field_str_2 == h and o.maker_id == m and not o.is_deleted:
                return o.problem_id
        return None
    def begin_nested(self): return _Nested(self)
    async def commit(self): self.commits += 1

def coding(title="두 수의 합", desc="a와 b를 입력받아 합을 출력하세요.", **kw):
    return dict(problemType="코딩", title=title, description=desc,
                test_cases=[{"input": "1 2", "expected_output": "3"}],
                reference_codes=[{"language": "python", "code": "print(sum(map(int,input().split())))"}], **kw)

async def call(db, problems, user="u1"):
    return await input_data_endpoint(InputDataRequest(problems=problems), {"sub": user}, db)

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

async def main():
    print("1. 해시 함수")
    h = compute_content_hash("코딩", "PY11-0001", "Hello World 출력")
    check("64자 sha256 (컬럼 길이 100 이내)", len(h) == 64)
    check("영문/한글 유형 이름은 같은 해시", h == compute_content_hash("coding", "PY11-0001", "Hello World 출력"))
    check("제목 대소문자 무시", h == compute_content_hash("코딩", "py11-0001", "Hello World 출력"))
    check("설명 공백·줄바꿈 차이 무시", h == compute_content_hash("코딩", "PY11-0001", "  Hello   World\r\n출력 "))
    check("설명 대소문자는 구분", h != compute_content_hash("코딩", "PY11-0001", "hello world 출력"))
    check("유형이 다르면 다른 해시", h != compute_content_hash("디버깅", "PY11-0001", "Hello World 출력"))

    print("2. 등록과 재전송")
    db = FakeSession()
    r = await call(db, [coding()])
    check("첫 등록 성공", r["status"] == "success" and r["created"] == 1 and r["skipped_duplicates"] == 0, r)
    check("해시가 저장됨", len(db.rows[0].temporary_field_str_2) == 64)
    r = await call(db, [coding()])
    check("같은 요청 재전송 → 중복으로 건너뜀", r["created"] == 0 and r["skipped_duplicates"] == 1 and r["status"] == "success", r)
    check("기존 문제 ID를 알려줌", r["duplicates"][0]["existing_problem_id"] == 1, r)
    check("DB에 한 건만 존재", len(db.rows) == 1)

    print("3. 중복 판정 범위")
    r = await call(db, [coding(desc="a와   b를 입력받아\n합을 출력하세요. ")])
    check("공백만 다른 설명도 중복", r["skipped_duplicates"] == 1, r)
    r = await call(db, [dict(problemType="디버깅", title="두 수의 합", description="a와 b를 입력받아 합을 출력하세요.",
                              test_cases=[{"input": "1 2", "expected_output": "3"}],
                              reference_codes=[{"language": "python", "code": "x"}],
                              base_code=[{"language": "python", "code": "y"}])])
    check("같은 제목·설명이어도 유형이 다르면 별개로 등록", r["created"] == 1, r)
    r = await call(db, [coding()], user="u2")
    check("다른 사용자는 별개로 등록", r["created"] == 1, r)
    db.rows[0].is_deleted = True
    r = await call(db, [coding()])
    check("삭제된 문제는 다시 등록할 수 있음", r["created"] == 1 and r["skipped_duplicates"] == 0, r)

    print("4. 한 요청 안의 혼합")
    db = FakeSession()
    await call(db, [coding(title="A")])
    r = await call(db, [coding(title="A"),            # 이미 있음
                        coding(title="B"),            # 신규
                        coding(title="B"),            # 같은 요청 안에서 중복
                        dict(problemType="코딩", title="", description="d", test_cases=[], reference_codes=[])])  # 검증 실패
    check("신규 1 · 중복 2 · 오류 1 → partial", r["status"] == "partial" and r["created"] == 1 and r["skipped_duplicates"] == 2 and r["failed"] == 1, r)
    check("오류에는 index 와 field 경로가 있음", r["errors"][0]["index"] == 4 and any(e["field"] == "title" for e in r["errors"][0]["error"]), r["errors"])
    check("중복 index 가 맞음", [d["index"] for d in r["duplicates"]] == [1, 3], r["duplicates"])
    check("commit 이 호출됨", db.commits >= 1)

    print("5. 전부 실패 / 전부 중복")
    r = await call(db, [dict(problemType="코딩", title="", description="d", test_cases=[], reference_codes=[])])
    check("전부 오류 → failure", r["status"] == "failure" and r["skipped_duplicates"] == 0, r)
    r = await call(db, [coding(title="A"), coding(title="B")])
    check("전부 중복 → success, created 0", r["status"] == "success" and r["created"] == 0 and r["skipped_duplicates"] == 2, r)

    print("6. 유형별 등록·재전송 (객관식·단답형·주관식)")
    db = FakeSession()
    batch = [
        dict(problemType="객관식", title="자료형", description="기본 자료형이 아닌 것은?", options=["int", "str", "varchar", "list"], correct_answers=[2]),
        dict(problemType="단답형", title="출력 함수", description="출력 함수는?", answer_text=["print", "print()"]),
        dict(problemType="주관식", title="캡슐화", description="캡슐화를 설명하시오.", answer_text="데이터와 메서드를 묶는 개념"),
    ]
    r = await call(db, batch)
    check("3개 유형 등록", r["created"] == 3, r)
    check("단답형 여러 답안이 그대로 저장됨", db.rows[1].answer_text == ["print", "print()"], db.rows[1].answer_text)
    r = await call(db, batch)
    check("재전송하면 3개 모두 중복", r["skipped_duplicates"] == 3 and r["created"] == 0, r)

    print(f"\n결과: 통과 {passed} / 실패 {failed}")
    return failed

sys.exit(1 if asyncio.run(main()) else 0)
