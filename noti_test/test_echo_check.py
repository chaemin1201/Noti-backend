"""입력값 섞임 검사(echo_check) 시험. 실제 AI 가 만든 결과(3단계)에서 나온 모양을 그대로 쓴다.
noti_test 폴더에서:  python test_echo_check.py"""
import sys
from types import SimpleNamespace as NS
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.checks import fix as ec

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

print("1. 섞인 경우를 찾는다 (실제 AI 결과의 모양)")
check("여러 줄 입력이 메뉴 프롬프트 뒤에 그대로 붙음", ec.echoes_input("1\n4 5\n3", "1:(+) 2:(*) 3:exit >> 1\noperand >> 4 5\nAdd : 9\n1:(+) 2:(*) 3:exit >> 3\n"))
check("한 줄 입력이 '>>' 뒤에 붙음", ec.echoes_input("pass", "pw 입력 >> pass\nid >> null\n"))
check("CRLF 줄바꿈도 같음", ec.echoes_input("pass", "pw 입력 >> pass" + chr(13) + chr(10) + "id >> null"))
print("2. 정상은 건드리지 않는다")
check("입력이 출력에 없음", not ec.echoes_input("4 5", "Add : 9" + chr(10) + "Mul : 20" + chr(10)))
check("입력이 없는 프로그램", not ec.echoes_input("", "hello") and not ec.echoes_input(None, "hello"))
check("한 줄 입력이 ':' 뒤에 우연히 같아도 경고하지 않음 (오탐 방지)", not ec.echoes_input("5", "Total : 5" + chr(10)))
check("계산 결과일 뿐인 숫자", not ec.echoes_input("3" + chr(10) + "4", "합: 7" + chr(10)))
check("프롬프트 뒤 입력이 이어서 쓰이는 정상 출력은 한 곳만이면 경고하지 않음", not ec.echoes_input("1" + chr(10) + "2", "a >> " + chr(10) + "결과 : 1" + chr(10)))

print("3. 경고 문구와 승인 이유")
tcs = [NS(input="", expected_output="x"), NS(input="pass", expected_output="pw >> pass" + chr(10)), NS(input="7", expected_output="menu >> 7" + chr(10))]
w = ec.echo_warnings(tcs)
check("섞인 케이스 번호(2, 3)만 경고", [x.split()[2] for x in w] == ["2", "3"], w)
r = ec.approval_reason(w + ["exec: 무시되는 경고"])
check("승인 이유 한 줄로 합쳐짐(외 1건)", r is not None and r.startswith("테스트 케이스를 확인하세요: 케이스 2") and "외 1건" in r, r)
check("경고가 없으면 None", ec.approval_reason(["exec: x"]) is None)

print("4. 서버 검사에 연결돼 있다 (checker → service.classify)")
from app.inputdata.intake import service
from app.inputdata.intake.checks import checker
def case(input_text, expected):
    return {"id": "x", "review": {"확인필요": []}, "payload": {
        "problemType": "코딩", "title": "E-1", "description": "메뉴에서 고르는 프로그램을 작성하세요.",
        "test_cases": [{"input": input_text, "expected_output": expected}],
        "reference_codes": [{"language": "python", "code": "print(1)"}]}}
bad = case("1" + chr(10) + "4 5", "menu >> 1" + chr(10) + "operand >> 4 5" + chr(10) + "9")
good = case("4 5", "9")
f, w = checker.check_case(bad, {}, skip_exec=True)
check("check_case 가 echo 경고를 낸다 (실패가 아니라 경고)", f == [] and any(x.startswith("echo:") for x in w), (f, w))
st, fails, warns, reasons = service.classify(bad, {}, False)
check("classify 가 승인 대기 + 테스트 케이스 확인 이유를 단다", st == "needs_review" and any("테스트 케이스를 확인하세요" in r for r in reasons), (st, reasons))
st2, _, warns2, reasons2 = service.classify(good, {}, False)
check("정상 케이스에는 echo 이유가 붙지 않는다", not any("테스트 케이스를 확인하세요" in r for r in reasons2) and not any(str(x).startswith("echo:") for x in warns2), reasons2)
print("5. 유형 불확실·같은 보기는 승인 대기로 보낸다")
def mc(opts, notes):
    return {"id": "m", "review": {"상태": "등록가능", "확인필요": notes}, "payload": {"problemType": "객관식", "title": "M-1", "description": "알맞은 것을 고르시오.", "rating_mode": "none", "options": opts, "correct_answers": [0]}}
st, _, _, rs = service.classify(mc(["가", "나"], ["문제 유형이 애매함: 연결하기 문제라 객관식으로 넣음"]), {}, False)
check("AI 가 유형이 애매하다고 적으면 승인 대기 + 유형 확인 이유", st == "needs_review" and any("5가지" in r for r in rs), (st, rs))
st, _, _, rs = service.classify(mc(["가", "나"], []), {}, False)
check("정상 객관식은 바로 ready", st == "ready" and not rs, (st, rs))
st, _, _, rs = service.classify(mc(["가", " 가 "], []), {}, False)
check("같은 보기가 있으면 승인 대기 + 보기 확인 이유", st == "needs_review" and any("같은 내용" in r for r in rs), (st, rs))
check("유형과 무관한 확인필요 문구는 유형 이유를 달지 않는다", not ec.UNSURE_TYPE_RE.search("출력 형식 확인 필요") and not ec.UNSURE_TYPE_RE.search("영상 링크 첨부"))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
