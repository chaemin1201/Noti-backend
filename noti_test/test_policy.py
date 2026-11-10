"""자동 등록 정책("보통") 고정 시험: 어떤 경우에 자동 등록(ready)되고, 어떤 경우에 사람 승인(needs_review)·막힘(blocked)이 되는지.

  보통 정책 = 검사 실패 없음 + 확인필요 없음 + (코딩·디버깅이면) 정답 코드를 서버에서 실행해 맞았음  →  승인 없이 등록
  AI 가 직접 채운 정답코드라도 실행이 통과하고 확인필요가 없으면 자동 등록한다. 참고는 승인에 영향을 주지 않는다.
noti_test 폴더에서:  python test_policy.py"""
import os, sys
import _bootstrap
_bootstrap.setup()
os.environ["INTAKE_EXEC_NO_NET"] = "off"          # 개발 PC 에서도 도는 시험 (네트워크 차단 동작은 check_exec_isolation.py 가 따로 본다)
from app.inputdata.intake import service

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

CODE = "a, b = map(int, input().split())" + chr(10) + "print(a + b)"
def coding(expected="3", code=CODE, title="P-1"):
    return {"problemType": "코딩", "title": title, "description": "두 정수의 합을 출력하시오.",
            "test_cases": [{"input": "1 2", "expected_output": expected}],
            "reference_codes": [{"language": "python", "code": code, "is_main": True}]}
def case(payload, notes=(), refs=(), filled=False):
    rv = {"상태": "등록가능", "보류사유": None, "확인필요": list(notes), "참고": list(refs),
          "채움": [{"항목": "reference_codes", "내용": "합 계산", "근거": "설명", "검증": "손 추적"}] if filled else []}
    return {"id": payload["title"], "payload": payload, "review": rv}
def run(c, exec_on=True):
    st, fails, warns, reasons = service.classify(c, {}, exec_on)
    return st, fails, reasons

print("1. 자동 등록 (실행 검증 켜짐)")
st, f, r = run(case(coding()))
check("실행이 맞고 확인필요 없음 → 자동 등록", st == "ready" and not r, (st, r))
st, f, r = run(case(coding(title="P-2"), filled=True))
check("AI 가 채운 정답코드여도 실행이 맞으면 자동 등록 (보통 정책)", st == "ready", (st, r))
st, f, r = run(case(coding(title="P-3"), refs=["원 문제 X의 방법1로 분할", "긴 대화형 출력은 서버 실행 검증으로 확인됨"]))
check("참고는 승인에 영향을 주지 않는다", st == "ready", (st, r))

print("2. 사람 승인이 필요한 경우")
st, f, r = run(case(coding(title="P-4"), notes=["원본 대조 필요"]))
check("확인필요가 있으면 승인 대기", st == "needs_review" and any("확인할 것 1건" in x for x in r), (st, r))
st, f, r = run(case(coding(title="P-5")), exec_on=False)
check("실행 검증이 꺼져 있으면 코딩 문제는 승인 대기", st == "needs_review" and any("실행해 확인하지 않았" in x for x in r), (st, r))
mc = {"problemType": "객관식", "title": "M-1", "description": "정답은?", "options": ["a", "b"], "correct_answers": [0]}
st, f, r = run(case(mc), exec_on=False)
check("객관식은 실행 검증이 꺼져 있어도 확인필요 없으면 자동 등록", st == "ready", (st, r))
bad_echo = {"problemType": "코딩", "title": "P-6", "description": "메뉴 프로그램",
            "test_cases": [{"input": "1" + chr(10) + "4 5", "expected_output": "menu >> 1" + chr(10) + "op >> 4 5" + chr(10) + "9"}],
            "reference_codes": [{"language": "python", "code": "print(1)", "is_main": True}]}
st, f, r = run(case(bad_echo), exec_on=False)
check("기대 출력에 입력값이 섞인 것 같으면 승인 이유에 알림", st == "needs_review" and any("테스트 케이스를 확인하세요" in x for x in r), (st, r))

print("3. 막힘·보류")
st, f, r = run(case(coding(expected="999", title="P-7")))
check("정답코드 실행 결과가 기대 출력과 다르면 막힘(승인 불가)", st == "blocked" and any("exec:" in x for x in f), (st, f))
held = {"id": "H-1", "payload": None, "review": {"상태": "보류", "보류사유": "본문을 읽을 수 없음", "확인필요": []}}
st, f, r = run(held)
check("AI 가 보류한 문제는 held", st == "held", st)

print("4. AI 가 직접 푼 객관식·단답형 정답은 자동 등록하지 않는다 (실행으로 확인할 수 없음)")
def with_fill(payload, item, how):
    c = case(payload)
    c["review"]["채움"] = [{"항목": item, "내용": "풀이", "근거": "문제", "검증": how}]
    return c
sa = {"problemType": "단답형", "title": "S-1", "description": "결과는?", "answer_text": ["12", "9"]}
st, f, r = run(with_fill(sa, "answer_text", "손 추적"), exec_on=True)
check("AI 가 손으로 푼 단답형 정답은 승인 대기 + 정답 확인 이유", st == "needs_review" and any("AI 가 직접 푼 정답" in x for x in r), (st, r))
st, f, r = run(with_fill(mc, "correct_answers", "손 추적"), exec_on=True)
check("AI 가 손으로 푼 객관식 정답도 승인 대기", st == "needs_review" and any("AI 가 직접 푼 정답" in x for x in r), (st, r))
st, f, r = run(with_fill(sa, "answer_text", "자료 일치"), exec_on=True)
check("정답자료·실행 기록에서 그대로 옮긴 정답('자료 일치')은 자동 등록", st == "ready", (st, r))
st, f, r = run(with_fill(sa, "title", "미검증"), exec_on=True)
check("정답과 무관한 AI 채움(제목 등)은 승인 대기로 만들지 않는다", st == "ready", (st, r))

os.environ["INTAKE_AI_ANSWER_REVIEW"] = "off"
st, f, r = run(with_fill(sa, "answer_text", "손 추적"), exec_on=True)
check("INTAKE_AI_ANSWER_REVIEW=off 이면 AI 가 푼 단답형 정답도 자동 등록 (사후 점검 표시만 남김)", st == "ready", (st, r))
os.environ.pop("INTAKE_AI_ANSWER_REVIEW")

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
