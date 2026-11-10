"""이전/이후 비교 도구 점검 (AI 호출 없음).
noti_test 폴더에서:  python test_compare_runs.py"""
import json, os, sys, tempfile
import _bootstrap
_bootstrap.setup()
import compare_runs as cr

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def rv(status="등록가능", confirm=(), fill=()):
    return {"상태": status, "보류사유": None if status == "등록가능" else "이유", "입력종류": "원본", "정리": [], "복구": [], "채움": list(fill), "조언": [], "확인필요": list(confirm), "참고": []}
def pl(**kw):
    d = {"problemType": "코딩", "title": "T", "description": "설명", "rating_mode": "none", "test_cases": [{"input": "", "expected_output": "1", "is_hidden": False}],
         "reference_codes": [{"language": "python", "code": "print(1)", "is_main": True}]}
    d.update(kw); return d
def line(i, payload, review): return {"id": i, "payload": payload, "review": review}
def text_line(t, row): return {"test": t, "run": 1, "model": "m", "text": json.dumps(row, ensure_ascii=False)}

def write(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in rows: f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
    f.close(); return f.name

A = write([line("P1", pl(title="P1"), rv()), line("P2", pl(title="P2", difficulty="easy"), rv()), line("P3", pl(title="P3"), rv()), line("P4", pl(title="P4"), rv()), line("P5", pl(title="P5"), rv(confirm=["a"]))])
B = write([line("P1", pl(title="P1"), rv()),                                                   # 같음
           line("P2", pl(title="P2"), rv()),                                                   # difficulty 가 사라짐 → 후퇴
           line("P3", None, rv("보류")),                                                      # 등록가능 → 보류 → 후퇴
           line("P4", pl(title="P4", description="다른 설명"), rv(confirm=["x", "y"])),          # description 변경 + 확인필요 증가 → 후퇴
           line("P5", pl(title="P5", tags=["루프"]), rv())])                                    # 개선: 확인필요 감소, tags 채워짐

print("1. 불러오기")
a, b = cr.load(A), cr.load(B)
check("id 줄 형식을 키별로 읽는다", set(a) == {"P1", "P2", "P3", "P4", "P5"} and len(a["P1"]) == 1)
t = cr.load(write([text_line("T1", line("T1", pl(title="T1"), rv())), {"test": "T2", "text": "JSON 이 아닌 글"}]))
check("run_ai_tests --save 형식(text)을 파싱한다", len(t["T1"]) == 1 and t["T1"][0]["id"] == "T1")
check("읽을 수 없는 출력은 형식실패로 센다", t["T2"] == [] and cr.summarize(t)["형식실패"] == 1)
items = write([]); open(items, "w", encoding="utf-8").write(json.dumps([{"result_id": "S1", "status": "ready", "payload": pl(title="S1"), "review": rv()}]))
check("서버 items 목록(JSON 배열)도 읽는다", list(cr.load(items)) == ["S1"])

print("2. 비교")
check("같은 문제는 후퇴도 변화도 없다", cr.diff_one(a["P1"], b["P1"]) == ([], []))
bad, _ = cr.diff_one(a["P2"], b["P2"]); check("항목이 사라지면 후퇴", any("difficulty" in x for x in bad), bad)
bad, _ = cr.diff_one(a["P3"], b["P3"]); check("등록가능 → 보류는 후퇴", any("상태" in x for x in bad), bad)
bad, _ = cr.diff_one(a["P4"], b["P4"]); check("description 변경과 확인필요 증가는 후퇴", any("description" in x for x in bad) and any("확인필요" in x for x in bad), bad)
bad, note = cr.diff_one(a["P5"], b["P5"]); check("확인필요 감소·항목 추가는 후퇴가 아니라 변화", not bad and any("확인필요" in x for x in note) and any("tags" in x for x in note), (bad, note))
bad, _ = cr.diff_one(a["P1"], []); check("이후가 형식실패면 후퇴", any("형식실패" in x for x in bad), bad)

print("3. 요약과 종료 코드")
sa, sb = cr.summarize(a), cr.summarize(b)
check("요약: 이전 5문제 등록가능 5, 이후 등록가능 4·보류 1", (sa["등록가능"], sb["등록가능"], sb["보류"]) == (5, 4, 1), (sa, sb))
check("후퇴가 있으면 종료 코드 1", cr.main([A, B]) == 1)
check("같은 파일끼리면 종료 코드 0", cr.main([A, A]) == 0)
check("인자가 모자라면 2", cr.main([A]) == 2)

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
