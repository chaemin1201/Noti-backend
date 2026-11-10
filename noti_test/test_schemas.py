"""schemas.py 검증 테스트. 실행: python test_schemas.py (pydantic v2 필요)
같은 폴더의 schemas.py 를 직접 import 하므로 app 패키지나 DB 없이 돌아갑니다."""
from pydantic import ValidationError
import _bootstrap
_bootstrap.setup()
from app.inputdata.schemas import problem_adapter, format_validation_errors     # 프로젝트의 실제 스키마

_F = _bootstrap.features()
PATCHED = _F["그래픽 문제 허용"] and _F["입력 null 처리"] and _F["정규화"]
passed = failed = skipped = 0
skipping = False            # True 이면 수정본이 필요한 항목이라 건너뜀(실패가 아님)


def _skip(name):
    global skipped
    skipped += 1; print(f"  ⏭ {name}  (수정본 미적용)")


def ok(name, data, check=None, patched_only=False):
    global passed, failed
    if skipping or (patched_only and not PATCHED): return _skip(name)
    try:
        p = problem_adapter.validate_python(data)
        dumped = p.model_dump(mode="json")      # 라우터/crud 와 같은 직렬화까지 확인
        if check:
            assert check(dumped), f"결과 불일치: {dumped}"
        passed += 1
        print(f"  ✅ {name}")
    except Exception as e:
        failed += 1
        print(f"  ❌ {name}: {type(e).__name__}: {str(e)[:150]}")


def bad(name, data, field=None, patched_only=False):
    global passed, failed
    if skipping or (patched_only and not PATCHED): return _skip(name)
    try:
        problem_adapter.validate_python(data)
        failed += 1
        print(f"  ❌ {name}: 통과해서는 안 되는 데이터가 통과함")
    except ValidationError as e:
        errs = format_validation_errors(e)
        if field is None or any(x["field"] == field for x in errs):
            passed += 1
            print(f"  ✅ {name} → {errs[0]['field']}: {errs[0]['message']}")
        else:
            failed += 1
            print(f"  ❌ {name}: 예상 field={field}, 실제={errs}")


coding = dict(problemType="코딩", title="t", description="d",
              test_cases=[{"input": "1", "expected_output": "1"}],
              reference_codes=[{"language": "python", "code": "print(1)"}])
debug = dict(problemType="디버깅", title="t", description="d",
             test_cases=[{"input": "", "expected_output": "1"}],
             reference_codes=[{"language": "python", "code": "print(1)"}],
             base_code=[{"language": "python", "code": "print()"}])
mc = dict(problemType="객관식", title="t", description="d", options=["a", "b", "c", "d"], correct_answers=[2])

print("1. 기존 test.py 샘플")
ok("코딩", coding)
ok("객관식", mc)
ok("단답형 리스트", dict(problemType="단답형", title="t", description="d", answer_text=["print", "print()"]))
ok("단답형 dict", dict(problemType="단답형", title="t", description="d", answer_text={"1": ["a"], "2": ["b"]}))
ok("주관식", dict(problemType="주관식", title="t", description="d", answer_text="x"))

print("2. 제목·설명 검증 (수정 전에는 모두 통과하던 케이스)")
bad("제목 없음", {k: v for k, v in coding.items() if k != "title"}, "title")
bad("제목 공백", {**coding, "title": "   "}, "title")
bad("설명 없음", {k: v for k, v in coding.items() if k != "description"}, "description")
bad("설명 빈 문자열", {**coding, "description": ""}, "description")
ok("제목 앞뒤 공백 제거", {**coding, "title": "  제목  "}, lambda d: d["title"] == "제목")

print("3. 그래픽 출력 문제 (테스트 케이스 없음)")
skipping = not PATCHED
bad("테스트 케이스도 조건도 없음", {**coding, "test_cases": []}, "문제 전체")
ok("테스트 케이스 없음 + 조건 있음", {**coding, "test_cases": [], "problem_condition": ["[필수] 반복문 사용"]})
ok("디버깅도 동일", {**debug, "test_cases": [], "problem_condition": ["[필수] 반복문 사용"]})
bad("test_cases 키 자체가 없음", {k: v for k, v in coding.items() if k != "test_cases"}, "test_cases")

print("4. 테스트 케이스 입력·키")
skipping = not PATCHED
ok("입력 null → 빈 문자열", {**coding, "test_cases": [{"input": None, "expected_output": "x"}]},
   lambda d: d["test_cases"][0]["input"] == "")
ok("입력 키 생략", {**coding, "test_cases": [{"expected_output": "x"}]},
   lambda d: d["test_cases"][0]["input"] == "")
ok("output 키도 허용, 저장은 expected_output", {**coding, "test_cases": [{"input": "1", "output": "1"}]},
   lambda d: d["test_cases"][0]["expected_output"] == "1" and "output" not in d["test_cases"][0])
bad("출력 키 둘 다 없음", {**coding, "test_cases": [{"input": "1"}]}, "test_cases.0.expected_output")

print("5. 정규화")
skipping = not PATCHED
ok("rating_mode Regex → regex", {**coding, "rating_mode": "Regex"}, lambda d: d["rating_mode"] == "regex")
bad("rating_mode 잘못된 값", {**coding, "rating_mode": "fuzzy"}, "rating_mode")
ok("난이도 Easy → easy", {**coding, "difficulty": "Easy"}, lambda d: d["difficulty"] == "easy")
ok("난이도 생략 → easy", coding, lambda d: d["difficulty"] == "easy")
bad("난이도 잘못된 값", {**coding, "difficulty": "쉬움"}, "difficulty")
ok("언어 Python → python", {**coding, "reference_codes": [{"language": "Python", "code": "x"}]},
   lambda d: d["reference_codes"][0]["language"] == "python")
bad("정답 코드 공백", {**coding, "reference_codes": [{"language": "python", "code": "  "}]}, "reference_codes.0.code")

skipping = False
print("6. 디버깅")
ok("정상", debug)
ok("reference_codes 단일 객체", {**debug, "reference_codes": {"language": "python", "code": "x"}}, patched_only=True)
bad("base_code 없음", {k: v for k, v in debug.items() if k != "base_code"}, "base_code")

print("7. 기타")
ok("정의되지 않은 필드는 무시됨(부제목 등)", {**coding, "subtitle": "s", "points": 10}, lambda d: "subtitle" not in d)
bad("조건이 객체 목록", {**coding, "problem_condition": [{"태그": "필수", "내용": "x"}]}, "problem_condition.0")
bad("객관식 정답 범위 초과", {**mc, "correct_answers": [4]}, "문제 전체", patched_only=True)

print(f"\n결과: 통과 {passed} / 실패 {failed}" + (f" / 수정본 미적용으로 건너뜀 {skipped}" if skipped else ""))
raise SystemExit(1 if failed else 0)
