"""서술형(주관식) 모범 답안은 사람이 직접 입력한다: 입력에 답이 없으면 AI 가 쓴 답을 지우고 needs_input 으로 두는지.
noti_test 폴더에서:  python test_subjective.py"""
import sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import service, models
from app.inputdata.intake.checks import fix as subjective
from app.inputdata.intake.checks import checker

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def pl(ans="모범 답안", **kw): return {"problemType": "주관식", "title": "S-1", "description": "상속을 설명하시오.", "answer_text": ans, **kw}
RV = {"확인필요": [], "채움": [{"항목": "answer_text", "내용": "..", "근거": "직접", "검증": "손 추적"}]}

print("1. AI 가 쓴 답 지우기")
p = pl(); check("입력에 답이 없으면 AI 의 답을 비운다", subjective.strip_ai_answer({"fields": {}}, p, RV) and p["answer_text"] == "")
p = pl(); check("엑셀 정답 열이 있으면 그대로 둔다", not subjective.strip_ai_answer({"fields": {"정답": "엑셀 답"}}, p, RV) and p["answer_text"] == "모범 답안")
p = pl(); check("풀이 자료가 있으면 그대로 둔다", not subjective.strip_ai_answer({"정답자료": "풀이"}, p, RV) and p["answer_text"] == "모범 답안")
p = pl(); rv = {"채움": [{"항목": "answer_text", "검증": "자료 일치"}]}
check("문서 값을 옮겼다고(자료 일치) 기록했으면 그대로 둔다", not subjective.strip_ai_answer(None, p, rv))
p = {"problemType": "단답형", "answer_text": ["40"], "title": "x", "description": "x"}
check("단답형·객관식은 건드리지 않는다", not subjective.strip_ai_answer({"fields": {}}, p, RV) and p["answer_text"] == ["40"])
check("이미 비어 있으면 아무것도 하지 않는다", not subjective.strip_ai_answer({"fields": {}}, pl(""), RV))

print("2. 입력 필요 상태")
check("주관식이고 답이 비면 입력 필요", subjective.needs_input(pl("")) and subjective.needs_input(pl("   ")))
check("답이 있거나 다른 유형이면 아니다", not subjective.needs_input(pl()) and not subjective.needs_input({"problemType": "단답형", "answer_text": ""}))
case = {"id": "S-1", "payload": pl(""), "review": {"확인필요": []}}
st, fails, warns, reasons = service.classify(case, {}, False)
check("classify 가 needs_input 으로 두고 이유를 단다 (막힘이 아님)", st == models.NEEDS_INPUT and not fails and reasons == [subjective.REASON], (st, fails, reasons))
check("승인 대상이 아니다", models.NEEDS_INPUT not in models.APPROVABLE and models.NEEDS_INPUT in models.EDITABLE and models.NEEDS_INPUT in models.ALL_STATUS)
bad = pl("", description="")
st, fails, _, _ = service.classify({"id": "S-1", "payload": bad, "review": {"확인필요": []}}, {}, False)
check("다른 오류(설명 비어 있음)가 있으면 입력 필요가 아니라 막힘으로 보인다", st == models.BLOCKED and fails, (st, fails))
st, fails, warns, reasons = service.classify({"id": "S-2", "payload": pl("직접 쓴 답"), "review": {"확인필요": []}}, {}, False)
check("답이 있으면 평소처럼 자동 등록 대상", st == models.READY, (st, reasons))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
