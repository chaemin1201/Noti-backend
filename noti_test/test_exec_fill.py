"""정답 코드의 실제 실행 출력으로 AI 가 만든 기대 출력을 채우는 동작 시험 (python 코드를 실제로 실행한다).
noti_test 폴더에서:  python test_exec_fill.py"""
import os, sys
import _bootstrap
_bootstrap.setup()
os.environ["INTAKE_EXEC_NO_NET"] = "off"
from app.inputdata.intake import service, models
from app.inputdata.intake.checks import checker
from app.inputdata.intake.checks import fix as exec_fill
from app.inputdata.intake.checks import fix as audit

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def pl(code, tcs, ptype="코딩"):
    return {"problemType": ptype, "title": "F-1", "description": "d", "rating_mode": "none", "problem_condition": ["[필수] 출력"],
            "test_cases": tcs, "reference_codes": [{"language": "python", "code": code, "is_main": True}]}
AI = {"확인필요": [], "채움": [{"항목": "test_cases", "내용": "..", "근거": "손 추적", "검증": "손 추적"}]}
DOC = {"확인필요": [], "채움": [{"항목": "test_cases", "내용": "..", "근거": "원본", "검증": "자료 일치"}]}
fill = lambda p, rv: exec_fill.fill(p, rv, checker.run_code, checker.norm_out)

print("1. 채우기")
p, rv = pl("print(1 + 2)", None), {"확인필요": []}
n = fill(p, rv)
check("테스트 케이스가 없으면 입력 없이 실행한 출력으로 1개 만든다", p["test_cases"] == [{"input": "", "expected_output": "3", "is_hidden": False}] and n, p["test_cases"])
check("채움에 '서버 실행'으로 기록되고 사후 점검(ai_filled)에 잡힌다", rv["채움"][-1]["항목"] == "test_cases" and rv["채움"][-1]["검증"] == "서버 실행" and "test_cases" in audit.ai_filled(rv), rv)
p, rv = pl("print(1 + 2)", [{"input": "", "expected_output": "5", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
n = fill(p, rv)
check("AI 가 손으로 쓴 기대 출력이 틀리면 실행 출력으로 바꾼다", p["test_cases"][0]["expected_output"] == "3" and n, (p["test_cases"], n))
p, rv = pl("print(1 + 2)", [{"input": "", "expected_output": "3", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
check("이미 맞으면 바꾸지도 기록하지도 않는다", not fill(p, rv) and rv["채움"] == AI["채움"])
p, rv = pl("print(1 + 2)", [{"input": "", "expected_output": "5", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("문서·엑셀에서 옮긴 기대 출력('자료 일치')은 건드리지 않는다 (다르면 서버 검사가 막는다)", not fill(p, rv) and p["test_cases"][0]["expected_output"] == "5")
p, rv = pl("print(1 + 2)", [{"input": "", "expected_output": "5", "is_hidden": False}]), {"확인필요": []}
check("채움 기록이 없으면 문서에서 온 값으로 보고 건드리지 않는다", not fill(p, rv) and p["test_cases"][0]["expected_output"] == "5")
p, rv = pl("x = int(input())\nprint(x * 2)", None), {}
check("입력이 필요한 프로그램을 입력 없이 만들 수는 없으므로 채우지 않는다", not fill(p, rv) and not p.get("test_cases"), p.get("test_cases"))
p, rv = pl("x = int(input())\nprint(x * 2)", [{"input": "21", "expected_output": "0", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
fill(p, rv); check("입력이 있는 케이스는 그 입력으로 실행한 출력으로 바꾼다", p["test_cases"][0]["expected_output"] == "42", p["test_cases"])
p, rv = pl("import sys\nprint('x')\nsys.exit(3)", None), {}
check("비정상 종료한 코드의 출력은 믿지 않는다", not fill(p, rv) and not p.get("test_cases"))
p, rv = {"problemType": "객관식", "title": "t"}, {}
check("코딩·디버깅이 아니면 아무것도 하지 않는다", not fill(p, rv))

print("2. 자동 등록으로 이어지는가 (classify, 실행 검증 켬)")
p, rv = pl("print('안녕')", [{"input": "", "expected_output": "안 녕", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
st0, f0, _, _ = service.classify({"id": "F-1", "payload": {**p, "test_cases": [dict(t) for t in p["test_cases"]]}, "review": rv}, {}, True)
fill(p, rv)
st1, f1, _, r1 = service.classify({"id": "F-1", "payload": p, "review": rv}, {}, True)
check("채우기 전에는 출력 불일치로 막히고", st0 == models.BLOCKED and any("출력 불일치" in x for x in f0), (st0, f0))
check("채운 뒤에는 막히지 않고 확인할 것이 없으면 자동 등록 대상(ready)이 된다", st1 == models.READY and not f1, (st1, f1, r1))

print("3. 실행마다 달라지는 출력(난수·시각·객체 해시)은 테스트 케이스로 쓰지 않는다")
RAND = "import random" + chr(10) + "print(random.random())"
p, rv = pl(RAND, None), {"확인필요": []}
n = fill(p, rv)
check("케이스가 없는데 출력이 실행마다 달라지면 만들지 않는다", not p.get("test_cases") and any("달라" in x for x in n) and any("달라" in x for x in rv["참고"]), (p.get("test_cases"), rv))
p, rv = pl(RAND, [{"input": "", "expected_output": "0.123", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
n = fill(p, rv)
check("AI 가 쓴 케이스의 출력이 실행마다 달라지면 그 케이스를 뺀다 (채점이 항상 틀리게 되므로)", p["test_cases"] == [] and any("뺌" in x for x in n), (p["test_cases"], n))
p, rv = pl("print('안정')", [{"input": "", "expected_output": "안정", "is_hidden": False}]), {"확인필요": [], "채움": list(AI["채움"])}
check("매번 같은 출력이면 그대로 둔다", not fill(p, rv) and len(p["test_cases"]) == 1)

print("4. 문서의 출력 예에 입력 안내 문구만 빠진 경우")
PROMPTED = "x = input('키를 입력하세요: ')\nprint('비만도는 정상입니다.')"
p, rv = pl(PROMPTED, [{"input": "170", "expected_output": "비만도는 정상입니다.", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
n = fill(p, rv)
check("문서의 출력이 실행 출력의 끝부분이고 앞에 안내 문구만 더 있으면 실행 출력으로 맞춘다", p["test_cases"][0]["expected_output"] == "키를 입력하세요: 비만도는 정상입니다." and n, (p["test_cases"], n))
p, rv = pl("print(13)", [{"input": "", "expected_output": "3", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("숫자가 우연히 겹치는 경우(문서 3, 코드 13)는 값이 다른 것이므로 바꾸지 않는다", not fill(p, rv) and p["test_cases"][0]["expected_output"] == "3")
p, rv = pl("print('-0.0+1.0i')", [{"input": "", "expected_output": "0.0+1.0i", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("-0.0 과 0.0 처럼 값이 다른 것(코드 결함)은 바꾸지 않는다 (서버 검사가 막는다)", not fill(p, rv) and p["test_cases"][0]["expected_output"] == "0.0+1.0i")
p, rv = pl("print('결과 : 21')", [{"input": "", "expected_output": "결과 : 20", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("값이 다르면 바꾸지 않는다", not fill(p, rv))
p, rv = pl("print('a')\nprint('b')", [{"input": "", "expected_output": "b\na", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("줄 순서가 다르면 바꾸지 않는다", not fill(p, rv))

print("5. 기대 출력에 사용자가 친 입력값이 섞인 경우 (콘솔 기록을 그대로 옮긴 실수)")
MENU = "a = input('키를 입력하세요: ')\nb = input('몸무게를 입력하세요: ')\nprint('비만도는 정상입니다.')"
p, rv = pl(MENU, [{"input": "170\n65", "expected_output": "키를 입력하세요: 170\n몸무게를 입력하세요: 65\n비만도는 정상입니다.", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
n = fill(p, rv)
check("안내 문구 뒤에 적힌 입력값과 그 줄바꿈이 있는 기대 출력은 실행 출력(입력값 없음)으로 바꾼다", p["test_cases"][0]["expected_output"] == "키를 입력하세요: 몸무게를 입력하세요: 비만도는 정상입니다." and any("입력값" in x for x in n), (p["test_cases"], n))
p, rv = pl(MENU, [{"input": "170\n65", "expected_output": "키를 입력하세요: 170\n몸무게를 입력하세요: 65\n비만도는 비정상입니다.", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("입력값을 걷어내도 결과 문구가 다르면(정상/비정상) 바꾸지 않는다", not fill(p, rv) and "비정상" in p["test_cases"][0]["expected_output"])
p, rv = pl("n = int(input('수: '))\nprint(n + 5)", [{"input": "3", "expected_output": "수: 3\n9", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("입력값을 걷어내면 같아 보이지만 결과 값이 다르면(8 과 9) 바꾸지 않는다", not fill(p, rv))
p, rv = pl("n = int(input('수: '))\nprint(n + 5)", [{"input": "3", "expected_output": "수: 3\n8", "is_hidden": False}]), {"확인필요": [], "채움": list(DOC["채움"])}
check("결과 값이 맞으면 입력값만 걷어낸다", fill(p, rv) and p["test_cases"][0]["expected_output"] == "수: 8", p["test_cases"])

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
