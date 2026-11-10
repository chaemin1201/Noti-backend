"""문제 설명 저장 형식 시험: 등록할 때 description 을 {"intent","subtitle","content"} JSON 문자열로 감싸는지, 중복 확인은 본문만 보는지.
noti_test 폴더에서:  python test_desc_pack.py"""
import json, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import models as desc_pack
from app.inputdata.dedupe import compute_content_hash

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

P = {"title": "T", "problemType": "코딩", "description": "본문 설명"}
print("1. 감싸기")
w = desc_pack.wrap(P)
d = json.loads(w["description"])
check("입력에 없으면 빈 문자열, 본문은 content", d == {"intent": "", "subtitle": "", "content": "본문 설명"}, d)
check("원래 payload 는 바뀌지 않는다", P["description"] == "본문 설명")
rec = {"fields": {"부제목": "엑셀 부제목", "문제의도": "엑셀 의도"}}
rv = {"채움": [{"항목": "부제목", "내용": "AI 부제목"}, {"항목": "문제의도", "내용": "AI 의도"}]}
d = json.loads(desc_pack.wrap(P, rec, rv)["description"])
check("입력의 값이 AI 가 채운 값보다 우선", d["subtitle"] == "엑셀 부제목" and d["intent"] == "엑셀 의도", d)
d = json.loads(desc_pack.wrap(P, {"fields": {}}, rv)["description"])
check("입력에 없으면 AI 가 채운 값", d["subtitle"] == "AI 부제목" and d["intent"] == "AI 의도", d)
d = json.loads(desc_pack.wrap(P, None, {"채움": [{"항목": "부제목", "내용": "  "}]})["description"])
check("빈 내용은 무시", d["subtitle"] == "", d)
w2 = desc_pack.wrap(w)
check("이미 감싸져 있으면 다시 감싸지 않는다", w2["description"] == w["description"])
check("한글·줄바꿈이 보존된다", json.loads(desc_pack.wrap({"description": "가\n나"})["description"])["content"] == "가\n나")
check("{ 로 시작하는 일반 설명은 감싸진 것으로 보지 않는다", desc_pack.unwrap("{a, b} 집합 문제") is None and desc_pack.unwrap('{"x": 1}') is None)

print("2. 중복 확인은 본문만")
h1 = compute_content_hash("코딩", "T", "본문 설명")
h2 = compute_content_hash("코딩", "T", w["description"])
h3 = compute_content_hash("코딩", "T", desc_pack.wrap(P, rec, rv)["description"])
check("감싼 설명과 일반 설명의 해시가 같다", h1 == h2 == h3)
check("본문이 다르면 해시도 다르다", h1 != compute_content_hash("코딩", "T", desc_pack.wrap({"description": "다른 설명"})["description"]))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
