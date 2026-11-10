"""마크다운 강조 검사 시험: 글자를 감싼 **굵게** 는 잡고, 코드·식의 ** (int **p, **kwargs, 2**3) 는 잡지 않는다.
실제 사례: 이중 포인터 문제 설명 '(int **)'와 조건 '키워드 가변 인자(**kwargs)'가 마크다운으로 오인되어 정상 문제가 막혔다.
noti_test 폴더에서:  python test_md_check.py"""
import sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.checks import checker
from app.inputdata.intake.checks.fix import has_markdown_bold

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

NL = chr(10)
print("1. 마크다운 강조는 잡는다")
for s in ["**방법1) for문을 사용하시오.**", "다음을 **반드시** 사용하세요", "(**강조**)", "**a** 와 **b**", "첫째 **굵게**" + NL + "둘째 줄", "**굵은 설명**입니다.", "이것은 **중요**합니다"]:
    check(f"잡음: {s[:30]!r}", has_markdown_bold(s))

print("2. 코드·식의 ** 는 잡지 않는다 (오탐 방지)")
CODE = ["이중 포인터(int **)를 매개변수로 받는 함수를 작성하세요.", "추가 전달되는 정보는 키워드 가변 인자(**kwargs)로 받습니다.", "def create_profile(name, age, **kwargs):",
        "void f(int **pp, int *target)", "x = 2**3 + 4**5", "2 ** 3 ** 2 를 계산", "f(**a, **b) 로 호출", "(int **) 와 (char **) 를 비교", "포인터 **p 와 **q 를 출력", "int main(int argc, char **argv, char **envp)",
        "__init__ 메서드를 정의하세요", "a**b 연산", "인라인 코드 `**굵게**` 는 코드", "펜스 코드:" + NL + "```" + NL + "**p = 5;" + " **q" + NL + "```"]
for s in CODE:
    check(f"안 잡음: {s[:34]!r}", not has_markdown_bold(s))

print("3. 서버 검사(checker)에 연결돼 있다")
def case(desc, cond):
    return {"id": "x", "review": {"확인필요": []}, "payload": {
        "problemType": "코딩", "title": "M-1", "description": desc, "problem_condition": cond,
        "test_cases": [{"input": "", "expected_output": "1"}], "reference_codes": [{"language": "python", "code": "print(1)"}]}}
f, _ = checker.check_case(case("이중 포인터(int **)를 사용하세요.", ["[필수] 키워드 가변 인자(**kwargs) 사용"]), {}, skip_exec=True)
check("이중 포인터·**kwargs 문제는 md 실패가 없다", not any(x.startswith("md:") for x in f), f)
f, _ = checker.check_case(case("**굵은 설명**입니다.", []), {}, skip_exec=True)
check("진짜 마크다운 강조는 description 에서 실패", any(x.startswith("md: description") for x in f), f)
f, _ = checker.check_case(case("설명", ["[필수] **반드시** for 사용"]), {}, skip_exec=True)
check("진짜 마크다운 강조는 problem_condition 에서도 실패", any(x.startswith("md: problem_condition") for x in f), f)

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
