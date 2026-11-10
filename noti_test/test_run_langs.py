"""서버의 정답 코드 실행 검증이 Java·JavaScript 도 다루는지 (이 PC 에 javac/java/node 가 있을 때). 실제 사례: 그림에서 옮긴 Java 코드에
`new Scanner(System. some)` 같은 깨진 글자가 있었는데 Java 는 실행하지 않아 그냥 통과했다.
noti_test 폴더에서:  python test_run_langs.py"""
import os, shutil, sys
import _bootstrap
_bootstrap.setup()
os.environ["INTAKE_EXEC_NO_NET"] = "off"
from app.inputdata.intake import service, models
from app.inputdata.intake.checks import checker

if not (shutil.which("javac") and shutil.which("java") and shutil.which("node")):
    print("⏭ 건너뜀: javac/java/node 가 필요합니다"); sys.exit(2)
passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

JAVA = 'import java.util.*;\npublic class Main { public static void main(String[] a){ Scanner s = new Scanner(System.in); int n = s.nextInt(); System.out.println("합: " + (n + 1)); } }'
print("1. Java")
check("실행하고 출력을 돌려준다", checker.run_code("java", JAVA, "4")[:2] == ("ok", "합: 5\n"))
r = checker.run_code("java", JAVA.replace("System.in", "System. some"), "4")
check("깨진 코드는 컴파일 실패로 잡는다 (서버 임시 경로는 메시지에 없음)", r[0] == "error" and "컴파일 실패" in r[1] and "tmp" not in r[1].lower(), r)
r = checker.run_code("java", "public class Shape<T>{}\nclass ShapeTest{ public static void main(String[] a){ System.out.println(\"x\"); } }", "")
check("public 클래스와 main 클래스가 다르면 main 클래스를 실행한다", r[:2] == ("ok", "x\n"), r)
check("파일·네트워크·프로세스 API 는 실행하지 않는다", checker.run_code("java", JAVA.replace("Scanner s", "java.io.FileReader f; Scanner s"), "4")[0] == "error" and
      "허용되지 않는" in checker.run_code("java", 'public class Main{ public static void main(String[] a) throws Exception { new ProcessBuilder("ls").start(); } }', "")[1])
check("무한 반복은 시간 초과로 끝난다", checker.run_code("java", "public class Main{ public static void main(String[] a){ while(true){} } }", "", timeout=3)[:2] == ("error", "시간 초과"))

print("2. JavaScript")
check("실행하고 출력을 돌려준다", checker.run_code("javascript", 'console.log("안녕", 1 + 2)', "")[:2] == ("ok", "안녕 3\n"))
check("fs·child_process 같은 모듈은 실행하지 않는다", checker.run_code("javascript", 'require("fs").readFileSync(0,"utf8")', "")[0] == "error" and checker.run_code("javascript", 'const c=require("child_process")', "")[0] == "error")
check("문법 오류는 실행 오류로 잡는다", checker.run_code("javascript", "console.log(", "")[0] == "error")

print("3. 자동 등록으로 이어지는가 (classify, 실행 검증을 켠 상태)")
def pl(code, out, lang="java"): return {"problemType": "코딩", "title": "J-1", "description": "n 을 입력받아 합을 출력", "rating_mode": "none", "problem_condition": ["[필수] 입력을 받는다"],
        "test_cases": [{"input": "4", "expected_output": out, "is_hidden": False}], "reference_codes": [{"language": lang, "code": code, "is_main": True}]}
st, fails, warns, reasons = service.classify({"id": "J-1", "payload": pl(JAVA, "합: 5"), "review": {"확인필요": []}}, {}, True)
check("기대 출력과 같으면 확인할 것이 없어 ready (자동 등록)", st == models.READY and not reasons, (st, fails, reasons))
st, fails, _, reasons = service.classify({"id": "J-2", "payload": pl(JAVA, "합: 9"), "review": {"확인필요": []}}, {}, True)
check("기대 출력과 다르면 막힌다", st == models.BLOCKED and any("출력 불일치" in f for f in fails), (st, fails))
st, fails, _, reasons = service.classify({"id": "J-3", "payload": pl(JAVA.replace("System.in", "System. some"), "합: 5"), "review": {"확인필요": []}}, {}, True)
check("깨진 정답 코드는 막힌다 (전에는 Java 를 실행하지 않아 통과했음)", st == models.BLOCKED and any("컴파일 실패" in f for f in fails), (st, fails))
st, _, _, reasons = service.classify({"id": "J-4", "payload": pl(JAVA, "합: 5"), "review": {"확인필요": ["글자 확인"]}}, {}, True)
check("AI 가 확인필요를 남기면 실행이 맞아도 승인 대기", st == models.NEEDS_REVIEW and any("확인할 것" in r for r in reasons), (st, reasons))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
