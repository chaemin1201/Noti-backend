"""엑셀 값 변경 감지(fidelity)와 AI 출력 JSON 복구(ai_output) 시험. AI 호출 없음.
실제 사례: AI 가 엑셀의 기대 출력에서 줄바꿈·입력값 줄을 지워 정상 데이터를 망가뜨렸다 (cpp03_01).
noti_test 폴더에서:  python test_fidelity.py"""
import json, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import service
from app.inputdata.intake.readers import xlsx_intake
from app.inputdata.intake.checks import fix as fidelity
from app.inputdata.intake.llm import parse_lines

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

NL = chr(10)
FIELDS = {"이름": "문제 F-1", "설명": "**반드시** 합을 출력하시오", "입력": "4" + NL + "10 20", "출력": "크기: 4" + NL + "합: 30", "정답코드": "print(1)", "제공코드": "x = 1"}
def payload(**kw):
    p = {"problemType": "디버깅", "title": "F-1", "description": "반드시 합을 출력하시오",
         "test_cases": [{"input": "4" + NL + "10 20", "expected_output": "크기: 4" + NL + "합: 30"}],
         "reference_codes": [{"language": "python", "code": "print(1)"}], "base_code": [{"language": "python", "code": "x = 1"}]}
    p.update(kw); return p
REC = {"입력종류": "엑셀", "fields": FIELDS}

print("1. 엑셀 값을 그대로 옮긴 경우는 통과")
check("그대로(마크다운 기호만 제거, 줄 끝 공백 차이)", fidelity.changed_fields(FIELDS, payload()) == [], fidelity.changed_fields(FIELDS, payload()))
check("줄 끝 공백·끝 줄바꿈 차이는 같은 값으로 본다", fidelity.changed_fields(FIELDS, payload(test_cases=[{"input": "4" + NL + "10 20 ", "expected_output": "크기: 4 " + NL + "합: 30" + NL}])) == [])

print("2. AI 가 바꾼 항목을 찾는다")
bad_out = payload(test_cases=[{"input": "4" + NL + "10 20", "expected_output": "크기: 합: 30"}])          # 입력값 줄 '4' 와 줄바꿈을 지운 실제 사례
check("기대 출력이 달라짐", fidelity.changed_fields(FIELDS, bad_out) == ["기대 출력"], fidelity.changed_fields(FIELDS, bad_out))
check("줄바꿈만 지워도 잡는다 (정확 일치로 채점하므로)", fidelity.changed_fields(FIELDS, payload(test_cases=[{"input": "4" + NL + "10 20", "expected_output": "크기: 4 합: 30"}])) == ["기대 출력"])
check("정답코드·제공코드·입력·설명이 달라진 것도 잡는다",
      fidelity.changed_fields(FIELDS, payload(reference_codes=[{"code": "print(2)"}], base_code=[{"code": "y = 2"}], description="다른 설명",
                                              test_cases=[{"input": "9", "expected_output": "크기: 4" + NL + "합: 30"}])) == ["입력", "정답코드", "제공코드", "설명"])
check("엑셀에 없는 칸은 비교하지 않는다", fidelity.changed_fields({"이름": "x", "설명": "합"}, payload(description="합")) == [])

print("3. 승인 이유")
r = fidelity.fidelity_reason(REC, bad_out)
check("엑셀 단독에서 바뀌면 승인 이유 한 줄", r is not None and "기대 출력" in r and "확인하세요" in r, r)
check("그대로면 None", fidelity.fidelity_reason(REC, payload()) is None)
check("둘 다·원본 입력에는 적용하지 않는다 (원본으로 복구하는 것이 정상)", fidelity.fidelity_reason({"입력종류": "둘 다", "fields": FIELDS}, bad_out) is None and fidelity.fidelity_reason({"입력종류": "원본"}, bad_out) is None)
case = {"id": "F-1", "payload": bad_out, "review": {"확인필요": []}, "record": REC}
st, fails, warns, reasons = service.classify(case, {}, False)
check("classify 가 승인 대기 + 엑셀 값 변경 이유를 단다", st == "needs_review" and any("엑셀 값과 달라진" in x for x in reasons), (st, reasons))
st2, _, _, reasons2 = service.classify({**case, "payload": payload()}, {}, False)
check("그대로면 이 이유가 붙지 않는다", not any("엑셀 값과 달라진" in x for x in reasons2), reasons2)

print("3b. 제목 되돌리기")
TREC = {"id": "C07_02", "fields": {"이름": "문제 C07_02 이중포인터"}}
p1 = {"title": "C07_02"}
check("줄인 제목은 입력의 이름('문제 ' 제거)으로 되돌리고 원래 AI 제목을 돌려준다", fidelity.fix_title(TREC, p1) == "C07_02" and p1["title"] == "C07_02 이중포인터", p1)
p2 = {"title": "PY10_02-확인학습"}
check("공백이 하이픈으로 바뀐 제목도 되돌린다", fidelity.fix_title({"id": "x", "fields": {"이름": "PY10_02 확인학습"}}, p2) is not None and p2["title"] == "PY10_02 확인학습", p2)
p3 = {"title": "C07_02 이중포인터"}
check("이미 같으면 손대지 않는다", fidelity.fix_title(TREC, p3) is None and p3["title"] == "C07_02 이중포인터")
p4 = {"title": "C07_02 이중포인터-2"}
check("방식 분할 제목('-N')은 그대로 둔다", fidelity.fix_title(TREC, p4) is None and p4["title"] == "C07_02 이중포인터-2")
check("기록이 없거나 payload 가 없으면 아무것도 안 한다", fidelity.fix_title(None, {"title": "a"}) is None and fidelity.fix_title(TREC, None) is None)

print("4. AI 출력 JSON 한 줄 복구 (닫는 괄호 누락)")
good = json.dumps({"id": "a", "payload": {"title": "a"}, "review": {"상태": "등록가능"}}, ensure_ascii=False)
check("정상 줄은 그대로", parse_lines(good)[0][0]["id"] == "a")
check("마지막 } 하나가 빠진 줄을 읽는다", parse_lines(good[:-1])[0][0]["id"] == "a")
check("} 두 개가 빠진 줄도 읽는다", parse_lines(good[:-2])[0][0]["id"] == "a")
rows, bad = parse_lines(good[:-12])
check("많이 잘린 줄은 복구하지 않고 형식 오류로 둔다", rows == [] and len(bad) == 1, (rows, bad))
check("코드 펜스·빈 줄·산문은 무시/오류 처리 (기존 동작)", parse_lines("```" + NL + good + NL + "```" + NL + "죄송합니다")[1] == ["죄송합니다"])

rec_o = {"입력종류": "원본", "id": "C_08_복사와이동생성자_01", "key": "C_08_복사와이동생성자_01"}
p_o = {"title": "C_08_복사와이동생자_01"}
orig = fidelity.fix_title(rec_o, p_o)
check("원본 문제의 제목을 AI 가 베끼다 틀리면 서버가 정한 ID 로 되돌린다", orig == "C_08_복사와이동생자_01" and p_o["title"] == "C_08_복사와이동생성자_01", p_o)
p_o2 = {"title": "C_08_복사와이동생성자_01-2"}
check("방식 분할 제목(ID-2)은 그대로 둔다", fidelity.fix_title(rec_o, p_o2) is None and p_o2["title"].endswith("-2"))
NL = chr(10)
def _rec(kind="엑셀", out="배열의 크기: 4" + NL + "4개를 입력: 10 20"):
    return {"입력종류": kind, "fields": {"입력": "4" + NL + "10 20", "출력": out}}
def _pl(exp): return {"problemType": "코딩", "test_cases": [{"input": "4", "expected_output": exp, "is_hidden": False}]}
rv_t = {"확인필요": [], "정리": []}
pl_t = _pl("배열의 크기: 4" + NL + "4" + NL + "4개를 입력: 10 20")
n_t = fidelity.restore_excel_outputs(_rec(), pl_t, rv_t)
check("엑셀 출력 열을 AI 가 바꿔(입력값 줄을 끼워 넣음) 쓰면 엑셀 값으로 되돌리고 정리에 적는다", n_t == 1 and pl_t["test_cases"][0]["expected_output"] == "배열의 크기: 4" + NL + "4개를 입력: 10 20" and "되돌림" in rv_t["정리"][0]["변경"], (n_t, pl_t))
pl_w = _pl("배열의 크기: 4  " + NL + "4개를 입력: 10 20" + NL)
check("줄 끝 공백이나 끝 줄바꿈만 다르면 건드리지 않는다", fidelity.restore_excel_outputs(_rec(), pl_w, {}) == 0 and pl_w["test_cases"][0]["expected_output"].endswith(NL))
pl_nl = _pl("합:55" + NL + "평균:5.5")
check("글자는 같고 줄바꿈 복원을 확인필요에 적었으면 AI 값을 인정한다", fidelity.restore_excel_outputs(_rec(out="합:55 평균:5.5"), pl_nl, {"확인필요": ["줄바꿈 복원, 원본 확인 권장"]}) == 0 and NL in pl_nl["test_cases"][0]["expected_output"])
pl_nl2 = _pl("합:55" + NL + "평균:5.5")
check("줄바꿈 복원을 확인필요에 적지 않았으면 엑셀 값으로 되돌린다", fidelity.restore_excel_outputs(_rec(out="합:55 평균:5.5"), pl_nl2, {"확인필요": []}) == 1 and pl_nl2["test_cases"][0]["expected_output"] == "합:55 평균:5.5")
pl_b = _pl("다른 값")
check("엑셀+원본(둘 다) 입력은 원본이 정본이므로 건드리지 않는다", fidelity.restore_excel_outputs(_rec(kind="둘 다"), pl_b, {}) == 0 and pl_b["test_cases"][0]["expected_output"] == "다른 값")
pl_c = {"problemType": "코딩", "test_cases": [{"input": "", "expected_output": "a"}, {"input": "", "expected_output": "b"}]}
check("테스트 케이스 개수가 엑셀과 다르면 건드리지 않는다", fidelity.restore_excel_outputs(_rec(out="x"), pl_c, {}) == 0)
check("엑셀에 출력 열이 없으면 건드리지 않는다", fidelity.restore_excel_outputs({"입력종류": "엑셀", "fields": {"설명": "d"}}, _pl("z"), {}) == 0)
print("서버로 옮긴 규칙: 객관식 정답 번호, 이름 없음·중복 보류")
def _mc(ans, cur, n=4): return {"입력종류": "엑셀", "fields": {"정답": ans}}, {"problemType": "객관식", "options": ["가", "나", "다", "라"][:n], "correct_answers": cur}
rec_a, pl_a = _mc("1,3", [1, 3])
rv_a = {}
check("객관식: 엑셀 정답 '1,3'(1부터)을 인덱스 [0, 2] 로 맞추고 정리에 적는다", fidelity.restore_choice_answers(rec_a, pl_a, rv_a) == 1 and pl_a["correct_answers"] == [0, 2] and "correct_answers" in rv_a["정리"][0]["항목"], (pl_a, rv_a))
rec_b, pl_b = _mc("2", [1])
check("이미 맞는 인덱스는 건드리지 않는다", fidelity.restore_choice_answers(rec_b, pl_b, {}) == 0 and pl_b["correct_answers"] == [1])
rec_c, pl_c = _mc("9", [0])
check("보기 개수를 벗어난 번호는 건드리지 않는다", fidelity.restore_choice_answers(rec_c, pl_c, {}) == 0 and pl_c["correct_answers"] == [0])
rec_d, pl_d = _mc("가", [0])
check("번호가 아닌 정답(글)은 건드리지 않는다", fidelity.restore_choice_answers(rec_d, pl_d, {}) == 0)
rec_e = {"입력종류": "원본", "fields": {"정답": "1"}}
check("원본 입력은 건드리지 않는다", fidelity.restore_choice_answers(rec_e, {"problemType": "객관식", "options": ["a", "b"], "correct_answers": [1]}, {}) == 0)
h1 = service._forced_hold({"입력종류": "엑셀", "key": "X", "fields": {"이름": "", "설명": "d"}, "intake": {"메모": []}})
check("이름이 없으면 AI 를 부르지 않고 보류한다", h1 and h1["payload"] is None and h1["review"]["상태"] == "보류" and "이름이 없" in h1["review"]["보류사유"], h1)
h2 = service._forced_hold({"입력종류": "엑셀", "key": "A_01", "fields": {"이름": "A_01", "설명": "d"}, "intake": {"메모": ["같은 이름이 여러 번 나옴 (2번, 행 3, 5)"]}})
check("같은 이름이 여러 번 나오면 겹친 위치를 알리고 보류한다", h2 and h2["review"]["상태"] == "보류" and "2번" in h2["review"]["보류사유"] and "서로 다르게" in h2["review"]["보류사유"], h2)
check("정상 행과 원본 입력(fields 없음)은 보류하지 않는다", service._forced_hold({"입력종류": "엑셀", "fields": {"이름": "A", "설명": "d"}, "intake": {"메모": []}}) is None and service._forced_hold({"입력종류": "원본", "key": "P", "원본조각": "x", "intake": {}}) is None)
print("엑셀 설명 되돌리기")
def _d(kind="엑셀", desc="두 수의 합을 출력하시오.", title="A_01", img=None):
    r = {"입력종류": kind, "fields": {"이름": title, "설명": desc}}
    if img: r["이미지"] = [{"n": 1}]
    return r
pl1 = {"title": "A_01", "description": "두 수를 더한 값을 출력하는 프로그램을 작성하세요."}
rv1 = {}
check("엑셀 단독: AI 가 설명 문장을 바꾸면 엑셀 값으로 되돌리고 정리에 적는다", fidelity.restore_excel_description(_d(), pl1, rv1) == 1 and pl1["description"] == "두 수의 합을 출력하시오." and "description" in rv1["정리"][0]["항목"], (pl1, rv1))
pl2 = {"title": "A_01", "description": "두 수의 합을  출력하시오.\n"}
check("공백·줄바꿈만 다르면 건드리지 않는다", fidelity.restore_excel_description(_d(), pl2, {}) == 0 and pl2["description"].startswith("두 수의 합을  출력"))
pl3 = {"title": "A_01", "description": "반드시 **정수**만 입력받으시오"}
check("엑셀 설명의 마크다운 기호(**)는 지운 값으로 되돌린다", fidelity.restore_excel_description(_d(desc="반드시 **정수**만 입력받으시오"), pl3, {}) == 0 and True)
pl3b = {"title": "A_01", "description": "전혀 다른 글"}
check("엑셀 설명에 ** 가 있으면 되돌릴 때 기호를 지운다", fidelity.restore_excel_description(_d(desc="반드시 **정수**만 입력받으시오"), pl3b, {}) == 1 and pl3b["description"] == "반드시 정수만 입력받으시오", pl3b)
pl4 = {"title": "A_01", "description": "다른 글"}
check("엑셀+원본(둘 다)은 원본이 정본이므로 건드리지 않는다", fidelity.restore_excel_description(_d(kind="둘 다"), pl4, {}) == 0 and pl4["description"] == "다른 글")
pl5 = {"title": "A_01-1", "description": "방법 안내 문장을 뺀 글"}
check("방식 분할 제목(A_01-1)은 건드리지 않는다", fidelity.restore_excel_description(_d(), pl5, {}) == 0)
pl6 = {"title": "A_01", "description": "그림에서 옮긴 설명 글"}
check("그림이 붙은 문제는 건드리지 않는다", fidelity.restore_excel_description(_d(img=True), pl6, {}) == 0 and pl6["description"] == "그림에서 옮긴 설명 글")

pm = {"description": "반드시 **정수**만 입력받으시오. 코드: int **p = &q;"}
rm = {}
check("설명에 남은 **굵게** 기호는 서버가 지우고 코드의 int **p 는 그대로 둔다", fidelity.strip_description_markdown(pm, rm) == 1 and pm["description"] == "반드시 정수만 입력받으시오. 코드: int **p = &q;" and rm["정리"][0]["항목"] == "description", (pm, rm))
check("마크다운이 없으면 건드리지 않는다", fidelity.strip_description_markdown({"description": "평범한 설명"}, {}) == 0)
print("엑셀·DB 코드 되돌리기")
_NL = chr(10)
def _c(kind="엑셀", ans="int main() {" + _NL + "  return 0;" + _NL + "}", base="int x = 1;"):
    return {"입력종류": kind, "fields": {"정답코드": ans, "제공코드": base}}
_pc = {"reference_codes": [{"language": "cpp", "code": "int main() { return 1; }", "is_main": True}], "base_code": [{"language": "cpp", "code": "int x = 1;", "is_main": False}]}
_rv = {}
check("AI 가 정답코드를 고쳐 쓰면 엑셀·DB 의 원래 코드로 되돌리고 조언에 제안을 남긴다", fidelity.restore_excel_codes(_c(), _pc, _rv) == 1 and _pc["reference_codes"][0]["code"].startswith("int main() {" + _NL) and any("int main() { return 1; }" in a["제안"] for a in _rv["조언"]) and any("되돌림" in x["변경"] for x in _rv["정리"]), (_pc, _rv))
_pc2 = {"reference_codes": [{"language": "cpp", "code": "int main() {  " + _NL + "  return 0;" + _NL + "}" + _NL, "is_main": True}]}
check("줄 끝 공백·끝 줄바꿈만 다르면 건드리지 않는다", fidelity.restore_excel_codes(_c(), _pc2, {}) == 0)
_pc3 = {"reference_codes": [{"language": "cpp", "code": "x", "is_main": True}], "base_code": [{"language": "cpp", "code": "y", "is_main": False}]}
check("엑셀 단독은 제공코드도 되돌린다", fidelity.restore_excel_codes(_c(), _pc3, {}) == 2 and _pc3["base_code"][0]["code"] == "int x = 1;")
_pc4 = {"reference_codes": [{"language": "cpp", "code": "x", "is_main": True}], "base_code": [{"language": "cpp", "code": "y", "is_main": False}]}
check("엑셀+원본(둘 다)은 정답코드만 되돌린다 (제공코드는 원본이 정본)", fidelity.restore_excel_codes(_c(kind="둘 다"), _pc4, {}) == 1 and _pc4["base_code"][0]["code"] == "y")
check("원본 입력과 코드 칸이 없는 입력은 건드리지 않는다", fidelity.restore_excel_codes({"입력종류": "원본", "fields": {"정답코드": "z"}}, {"reference_codes": [{"code": "x"}]}, {}) == 0 and fidelity.restore_excel_codes({"입력종류": "엑셀", "fields": {"설명": "d"}}, {"reference_codes": [{"code": "x"}]}, {}) == 0)
print("실행환경 링크 확인필요 지우기")
_rv = {"확인필요": ["설명에 Trinket 링크가 있어 첨부 필요", "영상 링크가 있어 첨부 필요", "출력 형식 확인", "실행 환경 링크 확인 필요"], "참고": []}
check("Trinket·실행환경 링크 때문에 단 확인필요만 지우고 영상 링크·다른 항목은 둔다", fidelity.drop_env_link_flags(_rv) == 2 and _rv["확인필요"] == ["영상 링크가 있어 첨부 필요", "출력 형식 확인"] and len(_rv["참고"]) == 1, _rv)
check("지울 것이 없으면 건드리지 않는다", fidelity.drop_env_link_flags({"확인필요": ["출력 확인"], "참고": []}) == 0)
import asyncio as _aio
_hold = {"id": "X", "payload": {"problemType": "코딩", "title": "X", "description": "d"}, "review": {"상태": "보류", "보류사유": "본문 없음"}}
try: _r = _aio.run(service._precheck(_hold, {"입력종류": "원본", "key": "X", "원본조각": "본문"}, False))
except Exception as _e: _r = repr(_e)
check("보류 결과(payload 가 지워짐)를 미리 검사해도 죽지 않는다 (실제 NoneType 오류의 원인)", _r == [], _r)
print("올릴 그림 / 올리지 않을 그림")
_rec = {"원본형식": "워드", "이미지": [{"n": 1}, {"n": 2}, {"n": 3}]}
_rv = {"그림": [{"n": 1, "용도": "출력예시", "올림": True}, {"n": 2, "용도": "정답", "올림": True}, {"n": 3, "용도": "문제글", "올림": True}, {"n": 9, "용도": "개념", "올림": True}]}
_up = fidelity.image_plan(_rec, _rv)
check("출력 예시 그림만 올린다 (정답·문제글 그림은 AI 가 올림이라 해도 막는다)", _up == [1] and [g["올림"] for g in _rv["그림"]] == [True, False, False], _rv)
check("붙지 않은 그림 번호(9)는 지운다", all(g["n"] != 9 for g in _rv["그림"]))
_rv2 = {"그림": [{"n": 1, "용도": "개념", "올림": True}]}
check("개념 그림은 올릴 수 있다", fidelity.image_plan(_rec, _rv2) == [1])
_rv3 = {"그림": [{"n": 1, "용도": "이상한값", "올림": True}]}
check("모르는 용도는 기타로 보고 올리지 않는다", fidelity.image_plan(_rec, _rv3) == [] and _rv3["그림"][0]["용도"] == "기타")
_rv4 = {"그림": [{"n": 1, "용도": "출력예시", "올림": True}]}
check("PDF 쪽 전체 화면은 출력 예시라 해도 올리지 않는다 (다른 문제·정답이 섞일 수 있음)", fidelity.image_plan({"원본형식": "PDF", "이미지": [{"n": 1}]}, _rv4) == [] and _rv4["그림"][0]["올림"] is False)
check("그림 항목이 없으면 건드리지 않는다", fidelity.image_plan(_rec, {"확인필요": []}) == [] and fidelity.image_plan(_rec, None) == [])
print("유형 추정 · 번호 붙은 단답 · 정답을 이유로 한 보류")
check("유형이 비고 보기가 있으면 객관식으로 추정한다", xlsx_intake.infer_type({"설명": "고르시오", "보기": "a" + chr(10) + "b"}) == "객관식")
check("유형이 비고 코드 단서(정답코드·입력·출력)가 있으면 코딩이다", xlsx_intake.infer_type({"설명": "출력하시오", "정답코드": "print(1)"}) == "코딩" and xlsx_intake.infer_type({"설명": "합", "출력": "7"}) == "코딩")
check("코드 단서가 하나도 없으면 코딩으로 단정하지 않는다 (O/X·연결하기 문제를 코딩으로 오해하지 않게)", xlsx_intake.infer_type({"설명": "다음이 맞으면 O, 틀리면 X"}) is None)
_ir = xlsx_intake.intake_row({"이름": "EX", "설명": "O 또는 X 로 답하시오"}, "t")
check("유형 미정이면 필수누락 없이 AI 가 판단하라는 메모를 남긴다", _ir["유형"] is None and _ir["필수누락"] == [] and any("유형을 판단" in m for m in _ir["메모"]), _ir)
_p = {"problemType": "단답형", "answer_text": ["(1) float", "2) int"], "rating_mode": "none"}
fidelity.normalize(_p, {})
check("'(n) 값' 모양의 단답형 정답을 번호별 정답으로 고친다", _p["answer_text"] == {"1": ["float"], "2": ["int"]}, _p)
_p2 = {"problemType": "단답형", "answer_text": ["len", "length"], "rating_mode": "none"}
fidelity.normalize(_p2, {})
check("번호가 없는 허용 답 목록은 그대로 둔다", _p2["answer_text"] == ["len", "length"])
_h = {"payload": None, "review": {"상태": "보류", "보류사유": "단답형 문제인데 정답이 누락되어 있어 등록할 수 없습니다"}}
check("단답형·객관식 정답이 없다는 이유의 보류는 다시 쓰게 한다", service._hold_fail(_h, {"key": "S"}) != [] and "보류 사유가 아닙니다" in service._hold_fail(_h, {"key": "S"})[0])
check("그림이 붙은 문제나 서술형 이유의 보류는 건드리지 않는다", service._hold_fail(_h, {"key": "S", "이미지": [{"n": 1}]}) == [] and service._hold_fail({"payload": None, "review": {"상태": "보류", "보류사유": "서술형 정답이 없음"}}, {"key": "S"}) == [])
check("정답과 무관한 보류 이유는 건드리지 않는다", service._hold_fail({"payload": None, "review": {"상태": "보류", "보류사유": "문제 본문을 읽을 수 없음"}}, {"key": "S"}) == [])
print("디버깅의 제공 코드는 설명에서 뺀다")
_code = "class Book {" + chr(10) + "  int price; // 가격" + chr(10) + "public:" + chr(10) + "  Book(int p);" + chr(10) + "};"
_desc = "Book 클래스를 구현하세요." + chr(10) + _code.replace("// 가격", "// 가격 ") + chr(10) + chr(10) + "1) 생성자를 작성하세요."
_p = {"problemType": "디버깅", "description": _desc, "base_code": [{"language": "cpp", "code": _code, "is_main": False}]}
_rv = {}
_n = fidelity.move_base_code_out({"입력종류": "원본"}, _p, _rv)
check("원본 문서의 디버깅: 설명에 있던 제공 코드 5줄을 빼고 문장은 그대로 둔다 (공백 차이는 무시)", _n == 5 and _p["description"] == "Book 클래스를 구현하세요." + chr(10) + chr(10) + "1) 생성자를 작성하세요." and "class Book" not in _p["description"], _p["description"])
check("정리에 기록한다", _rv["정리"] and "제공 코드 5줄" in _rv["정리"][0]["변경"], _rv)
_p2 = {"problemType": "디버깅", "description": _desc, "base_code": [{"language": "cpp", "code": _code}]}
check("엑셀 단독 입력은 엑셀의 설명을 지키므로 그대로 둔다", fidelity.move_base_code_out({"입력종류": "엑셀"}, _p2, {}) == 0 and _p2["description"] == _desc)
_p3 = {"problemType": "코딩", "description": _desc, "base_code": [{"language": "cpp", "code": _code}]}
check("코딩 문제는 건드리지 않는다", fidelity.move_base_code_out({"입력종류": "원본"}, _p3, {}) == 0)
_p4 = {"problemType": "디버깅", "description": "x = 1" + chr(10) + "print(x)", "base_code": [{"language": "python", "code": "x = 1" + chr(10) + "print(x)"}]}
check("설명에 코드밖에 없으면(글이 남지 않으면) 지우지 않는다", fidelity.move_base_code_out({"입력종류": "원본"}, _p4, {}) == 0 and "print(x)" in _p4["description"])
_p5 = {"problemType": "디버깅", "description": "다음을 고치세요." + chr(10) + "print(1)", "base_code": [{"language": "python", "code": "print(1)"}]}
check("코드가 한 줄뿐이면 우연히 같을 수 있어 지우지 않는다", fidelity.move_base_code_out({"입력종류": "원본"}, _p5, {}) == 0)
_c2 = "class Book {" + chr(10) + "char *title; // 제목" + chr(10) + "public:" + chr(10) + "  void show() { cout << title; }" + chr(10) + "};"
_d2 = "Book 을 완성하세요." + chr(10) + "class Book {" + chr(10) + "char *title; // 제목 [이미지]" + chr(10) + "public:" + chr(10) + "  void show() { std::cout << title; }" + chr(10) + "};" + chr(10) + chr(10) + "1) 생성자를 작성하세요."
_q = {"problemType": "디버깅", "description": _d2, "base_code": [{"language": "cpp", "code": _c2}]}
check("AI 가 코드를 다듬어(std::, 그림 표시 등) 줄이 조금 달라도 같은 코드 블록으로 보고 뺀다", fidelity.move_base_code_out({"입력종류": "원본"}, _q, {}) == 5 and "class Book" not in _q["description"] and "1) 생성자를 작성하세요." in _q["description"], _q["description"])
_d3 = "설명 문장 하나." + chr(10) + "다른 문장 둘." + chr(10) + "또 다른 문장 셋." + chr(10) + "x = 1" + chr(10) + "y = 2"
_q3 = {"problemType": "디버깅", "description": _d3, "base_code": [{"language": "python", "code": "x = 1" + chr(10) + "y = 2" + chr(10) + "z = 3" + chr(10) + "print(z)" + chr(10) + "w = 4"}]}
check("제공 코드의 일부만(80% 미만) 설명에 있으면 지우지 않는다", fidelity.move_base_code_out({"입력종류": "원본"}, _q3, {}) == 0 and "x = 1" in _q3["description"])
print("엑셀의 번호별 단답 정답 되돌리기")
_nl = chr(10)
_rec = {"입력종류": "엑셀", "fields": {"정답": "(1) float" + _nl + "(2) int"}}
_pp = {"problemType": "단답형", "answer_text": ["float", "int"]}
_rv = {}
check("AI 가 번호를 떼고 목록으로 바꾼 단답 정답을 엑셀의 번호별 정답으로 되돌린다", fidelity.restore_short_answers(_rec, _pp, _rv) is True and _pp["answer_text"] == {"1": ["float"], "2": ["int"]} and _rv["복구"], _pp)
_pp2 = {"problemType": "단답형", "answer_text": {"1": ["float"], "2": ["int"]}}
check("이미 같으면 건드리지 않는다", fidelity.restore_short_answers(_rec, _pp2, {}) is False)
_pp3 = {"problemType": "단답형", "answer_text": ["len"]}
check("번호가 없는 엑셀 정답은 건드리지 않는다", fidelity.restore_short_answers({"입력종류": "엑셀", "fields": {"정답": "len"}}, _pp3, {}) is False and _pp3["answer_text"] == ["len"])
_pp4 = {"problemType": "단답형", "answer_text": ["a"]}
check("같은 번호가 여러 줄이면 그 번호의 허용 답에 모은다", fidelity.restore_short_answers({"입력종류": "엑셀", "fields": {"정답": "(1) a" + _nl + "(1) b"}}, _pp4, {}) is True and _pp4["answer_text"] == {"1": ["a", "b"]}, _pp4)
check("엑셀 입력이 아니면(fields 없음) 건드리지 않는다", fidelity.restore_short_answers({"입력종류": "원본"}, {"problemType": "단답형", "answer_text": ["x"]}, {}) is False)
print("설명에서 그림 링크 줄 지우기")
_nl = chr(10)
_pp = {"problemType": "코딩", "description": "합을 구하시오." + _nl + _nl + "![](Untitled%201.png)" + _nl + _nl + "입력은 두 정수입니다."}
_rv = {}
check("원본 설명의 ![](..) 그림 링크 줄을 지우고 문장은 그대로 둔다", fidelity.strip_description_images({"입력종류": "원본"}, _pp, _rv) == 1 and "![" not in _pp["description"] and "합을 구하시오." in _pp["description"] and "입력은 두 정수입니다." in _pp["description"] and _rv["정리"], _pp)
_pe = {"problemType": "코딩", "description": "합" + _nl + "![](a.png)" + _nl + "을 구하시오 충분히 긴 글"}
check("엑셀 단독 입력은 엑셀의 설명을 지키므로 건드리지 않는다", fidelity.strip_description_images({"입력종류": "엑셀"}, _pe, {}) == 0 and "![" in _pe["description"])
check("코드 속 느낌표·대괄호는 그림 링크가 아니므로 지우지 않는다", fidelity.strip_description_images({"입력종류": "원본"}, {"description": "if (!a[0]) 처리하시오 이 문장은 충분히 깁니다"}, {}) == 0)
print("옮겨진 예시를 가리키는 말 고치기")
_pp = {"problemType": "코딩", "description": "np1 배열과 같이 체스보드 판을 그리는 프로그램을 작성하시오.", "test_cases": [{"input": "", "expected_output": "1 0 1"}]}
_rv = {}
check("'np1 배열과 같이' 처럼 이름으로 예시를 가리키면 '출력 결과와 같이'로 고친다", fidelity.fix_example_ref({"입력종류": "원본"}, _pp, _rv) == 1 and _pp["description"] == "출력 결과와 같이 체스보드 판을 그리는 프로그램을 작성하시오." and _rv["정리"], _pp)
_p2 = {"problemType": "코딩", "description": "np1 배열을 만든 뒤 np1 배열과 같이 출력하시오.", "test_cases": [{"input": "", "expected_output": "1"}]}
check("그 이름이 설명 안에서 다른 곳에도 쓰이면(정의·사용) 그대로 둔다", fidelity.fix_example_ref({"입력종류": "원본"}, _p2, {}) == 0 and "np1 배열과 같이" in _p2["description"])
_p3 = {"problemType": "코딩", "description": "np1 배열과 같이 그리시오.", "test_cases": []}
check("출력 예(test_cases)가 없으면 고치지 않는다", fidelity.fix_example_ref({"입력종류": "원본"}, _p3, {}) == 0)
_p4 = {"problemType": "코딩", "description": "np1 배열과 같이 그리시오.", "test_cases": [{"input": "", "expected_output": "1"}]}
check("엑셀 단독 입력은 엑셀의 설명을 지킨다", fidelity.fix_example_ref({"입력종류": "엑셀"}, _p4, {}) == 0 and "np1" in _p4["description"])
_p5 = {"problemType": "코딩", "description": "아래와 같이 출력하시오.", "test_cases": [{"input": "", "expected_output": "1"}]}
check("이름 없는 '아래와 같이' 는 건드리지 않는다 (아래의 대상이 설명에 남아 있을 수 있음)", fidelity.fix_example_ref({"입력종류": "원본"}, _p5, {}) == 0)
print("디버깅의 정답 코드는 제공 코드를 포함한 전체 코드")
from app.inputdata.intake.checks import checker as _ck
_nl = chr(10)
_base = "class Person {" + _nl + "  int id;" + _nl + "public:" + _nl + "  Person(const Person& p);" + _nl + "};"
_full = _base + _nl + "Person::Person(const Person& p) { id = p.id; }" + _nl + "int main() { return 0; }"
def _dbg(ref):
    return {"id": "D", "review": {"확인필요": []}, "payload": {"problemType": "디버깅", "title": "D-1", "description": "구현하세요", "rating_mode": "none",
            "base_code": [{"language": "cpp", "code": _base, "is_main": False}], "reference_codes": [{"language": "cpp", "code": ref, "is_main": True}],
            "test_cases": [{"input": "", "expected_output": "", "is_hidden": False}]}}
_f, _w = _ck.check_case(_dbg(_full), {}, skip_exec=True)
check("정답 코드가 제공 코드를 포함하면 통과", not any(x.startswith("ref:") for x in _f), _f)
_f, _w = _ck.check_case(_dbg("Person::Person(const Person& p) { id = p.id; }"), {}, skip_exec=True)
check("정답 코드가 구현부만 있고 제공 코드(클래스 선언 등)를 빼먹으면 막지 않고 경고 + 승인 이유", not _f and any(x.startswith("ref:") and "제공 코드까지 포함" in x for x in _w) and any("제공 코드가 거의" in r for r in service.classify(_dbg("Person::Person(const Person& p) { id = p.id; }"), {}, False)[3]), (_f, _w))
print("조건 정리: 설명의 조건·입출력 예 구역, 객관식·단답형·주관식의 조건")
_nl = chr(10)
_d1 = "입력 문자열의 단어 순서를 뒤집으시오." + _nl + "- 조건" + _nl + "    - [Trinket](https://trinket.io/x)" + _nl + "    - 아래방법 모두 작성하시오." + _nl + "        - 방법1) for 반복문 이용하시오" + _nl + "- 입출력 예" + _nl + "    - 입력 안내 메시지는 생략해주세요" + _nl + "        | 입력 | 출력 |" + _nl + "        | --- | --- |" + _nl + "        | a b | b a |"
_p1 = {"problemType": "코딩", "description": _d1, "problem_condition": ["[필수] 아래방법 모두 작성하시오", "[필수] 방법1) for 반복문 이용하시오"], "test_cases": [{"input": "a b", "expected_output": "b a"}]}
_r1 = {}
_n1 = fidelity.trim_description({"입력종류": "원본"}, _p1, _r1)
check("조건·입출력 예 구역을 설명에서 빼고 링크 줄은 남긴다 (조건이 모두 problem_condition 에 있을 때)", _n1 > 0 and "- 조건" not in _p1["description"] and "입출력 예" not in _p1["description"] and "| --- |" not in _p1["description"] and "trinket.io" in _p1["description"] and _p1["description"].startswith("입력 문자열의 단어 순서를 뒤집으시오."), _p1["description"])
check("입출력 예 구역의 '~해주세요' 문장은 [출력형식] 조건으로 옮긴다", "[출력형식] 입력 안내 메시지는 생략해주세요" in _p1["problem_condition"], _p1["problem_condition"])
_p2 = {"problemType": "코딩", "description": "합을 구하시오." + _nl + "- 조건" + _nl + "- 변수 이름은 영어로 쓴다" + _nl + "- 반복문 사용", "problem_condition": ["[필수] 반복문 사용"], "test_cases": [{"input": "", "expected_output": "1"}]}
_n2 = fidelity.trim_description({"입력종류": "원본"}, _p2, {})
check("problem_condition 에 없던 조건 항목은 [필수]/[금지]/[허용] 을 붙여 조건 목록에 옮긴 뒤 설명에서 뺀다 (정보가 사라지지 않게)", _n2 > 0 and "- 조건" not in _p2["description"] and "[필수] 변수 이름은 영어로 쓴다" in _p2["problem_condition"] and "[필수] 반복문 사용" in _p2["problem_condition"] and len(_p2["problem_condition"]) == 2, _p2)
_p2b = {"problemType": "코딩", "description": "배열을 만드시오." + _nl + "- 조건" + _nl + "- 반복문 사용x" + _nl + "- 문자열 함수 사용 가능" + _nl + "- [필수] 방법2로 구현할 것", "problem_condition": [], "test_cases": [{"input": "", "expected_output": "1"}]}
fidelity.trim_description({"입력종류": "원본"}, _p2b, {})
check("사용x → [금지], 사용 가능 → [허용], 설명에 적힌 [필수] 태그 줄은 조건으로 옮기고 지운다", sorted(_p2b["problem_condition"]) == sorted(["[금지] 반복문 사용x", "[허용] 문자열 함수 사용 가능", "[필수] 방법2로 구현할 것"]) and _p2b["description"] == "배열을 만드시오.", _p2b)
_p2c = {"problemType": "코딩", "description": "채우시오." + _nl + "- 입력" + _nl + "    - 입출력 예 참고" + _nl + "- 출력" + _nl + "    - 입출력 예 참고", "problem_condition": [], "test_cases": [{"input": "", "expected_output": "1"}]}
fidelity.trim_description({"입력종류": "원본"}, _p2c, {})
check("'입력/출력: 입출력 예 참고' 뿐인 머리는 설명에서 지운다", _p2c["description"] == "채우시오.", _p2c)
_s1 = {"problemType": "단답형", "answer_text": ["97531", "876", "876"], "description": "결과를 작성하시오." + _nl + "| 코드 | 결과 |" + _nl + "| --- | --- |" + _nl + "| a |  |" + _nl + "| b |  |" + _nl + "| c |  |"}
check("단답형: 빈 결과 칸이 있는 표 행 수와 정답 수가 같으면 번호별 정답으로 나눈다", fidelity.number_short_answers(_s1, {}) is True and _s1["answer_text"] == {"1": ["97531"], "2": ["876"], "3": ["876"]}, _s1)
_s2 = {"problemType": "단답형", "answer_text": ["a", "b"], "description": "1) 첫째는?" + _nl + "2) 둘째는?"}
check("단답형: 설명에 1) 2) 번호 소문항이 있으면 번호별 정답으로 나눈다", fidelity.number_short_answers(_s2, {}) is True and _s2["answer_text"] == {"1": ["a"], "2": ["b"]}, _s2)
_s3 = {"problemType": "단답형", "answer_text": ["a", "b"], "description": "두 값을 쓰시오."}
check("번호 소문항이 없으면 허용 답 목록 그대로 둔다", fidelity.number_short_answers(_s3, {}) is False and _s3["answer_text"] == ["a", "b"])
_s4 = {"problemType": "단답형", "answer_text": ["a", "b", "c"], "description": "1) 첫째는?" + _nl + "2) 둘째는?"}
check("번호 소문항 수와 정답 수가 다르면 건드리지 않는다", fidelity.number_short_answers(_s4, {}) is False)
_p3 = {"problemType": "코딩", "description": "합" + _nl + "- 조건" + _nl + "- 반복문 사용", "problem_condition": ["[필수] 반복문 사용"], "test_cases": []}
check("엑셀 단독 입력은 건드리지 않는다", fidelity.trim_description({"입력종류": "엑셀"}, _p3, {}) == 0)
_p4 = {"problemType": "단답형", "description": "결과를 작성하시오. 충분히 긴 글" + _nl + "- 조건" + _nl + "- x 로 표시하시오", "problem_condition": ["[필수] x 로 표시하시오"], "answer_text": ["a"]}
check("단답형의 조건 문장은 설명에 남기고(조건 구역을 지우지 않음) 조건 목록은 비운다", fidelity.trim_description({"입력종류": "원본"}, _p4, {}) == 0 and fidelity.drop_noncode_conditions(_p4, {}) == 1 and _p4["problem_condition"] == [] and "x 로 표시하시오" in _p4["description"], _p4)
_p5 = {"problemType": "주관식", "description": "캡슐화의 장점을 서술하시오.", "problem_condition": ["[필수] 3줄 이내로 쓴다"], "answer_text": ""}
fidelity.drop_noncode_conditions(_p5, {})
check("주관식의 조건이 설명에 없으면 설명 끝으로 옮기고 조건 목록은 비운다", _p5["problem_condition"] == [] and _p5["description"].endswith("3줄 이내로 쓴다"), _p5)
_p6 = {"problemType": "객관식", "description": "알맞은 것은?", "problem_condition": [], "options": ["a", "b"], "correct_answers": [0]}
check("조건이 없으면 건드리지 않는다", fidelity.drop_noncode_conditions(_p6, {}) == 0 and _p6["problem_condition"] == [])
_p7 = {"problemType": "코딩", "description": "합", "problem_condition": ["[필수] x"]}
check("코딩·디버깅의 조건은 그대로 둔다", fidelity.drop_noncode_conditions(_p7, {}) == 0 and _p7["problem_condition"] == ["[필수] x"])
print("설명에 정답이 섞였는지 확인")
_nl = chr(10)
_c = "a = int(input())" + _nl + "b = int(input())" + _nl + "print(a + b)" + _nl + "print(a - b)"
_lk = {"problemType": "코딩", "description": "합을 구하시오." + _nl + _c, "base_code": [], "reference_codes": [{"language": "python", "code": _c}]}
check("정답 코드 줄 3개 이상이 설명에 있으면 정답 노출 의심", "정답 코드와 같은 줄" in (_ck.answer_leak_reason(_lk) or ""), _ck.answer_leak_reason(_lk))
_ok = {"problemType": "디버깅", "description": "고치시오." + _nl + _c, "base_code": [{"code": _c}], "reference_codes": [{"language": "python", "code": _c}]}
check("설명의 코드가 제공 코드(base_code)와 같을 뿐이면 정답 노출로 보지 않는다", _ck.answer_leak_reason(_ok) is None)
check("단답형 정답 글이 설명에 그대로 있으면 의심", "정답 글이" in (_ck.answer_leak_reason({"problemType": "단답형", "description": "결과는 numpy 입니다 라고 쓰시오", "answer_text": ["numpy"]}) or ""))
check("짧은 정답(3글자 이하)은 우연히 겹칠 수 있어 보지 않는다", _ck.answer_leak_reason({"problemType": "단답형", "description": "x 를 쓰시오 abc", "answer_text": ["abc"]}) is None)
check("정답 글이 설명에 없으면 통과", _ck.answer_leak_reason({"problemType": "주관식", "description": "캡슐화를 서술하시오", "answer_text": "정보 은닉과 접근 제어를 통해 안전하게 한다"}) is None)
print("소문항 밑에 적힌 답을 설명에서 떼어 정답 칸으로")
_nl = chr(10)
_d = "상속에 대한 물음에 답하시오." + _nl + " a) 상속의 주체는? " + _nl + "-상속의 주체는 자식입니다." + _nl + " b) 다중 상속이 가능한가?" + _nl + "-가능하지 않습니다." + _nl + "클래스만으로는 불가능합니다." + _nl + " e) 부모 메소드를 부르는 키워드는?" + _nl + "-super 키워드"
_pe = {"problemType": "주관식", "description": _d, "answer_text": ""}
_re = {}
check("주관식: 소문항 밑의 답을 설명에서 떼어 모범 답안으로 옮긴다 (문서가 준 답이라 '자료 일치')", fidelity.extract_inline_answers({"입력종류": "원본"}, _pe, _re) == 3 and "자식입니다" not in _pe["description"] and "a) 상속의 주체는? " in _pe["description"] and "b) 상속의 주체는 자식입니다." not in _pe["answer_text"] and _pe["answer_text"].startswith("a) 상속의 주체는 자식입니다.") and "b) 가능하지 않습니다." in _pe["answer_text"] and "클래스만으로는 불가능합니다." in _pe["answer_text"] and any(x.get("검증") == "자료 일치" for x in _re["채움"]), (_pe, _re))
_ps = {"problemType": "단답형", "description": _d, "answer_text": ""}
fidelity.extract_inline_answers({"입력종류": "원본"}, _ps, {})
check("단답형: 설명의 소문항 표기(a, b, e)를 그대로 키로 하는 정답으로 옮긴다", _ps["answer_text"]["a"] == ["상속의 주체는 자식입니다."] and list(_ps["answer_text"]) == ["a", "b", "e"], _ps["answer_text"])
_pk = {"problemType": "단답형", "description": _d, "answer_text": ["이미", "있음", "x"]}
fidelity.extract_inline_answers({"입력종류": "원본"}, _pk, {})
check("AI 가 이미 정답을 넣었으면 정답은 그대로 두고 설명에서만 뺀다", _pk["answer_text"] == ["이미", "있음", "x"] and "자식입니다" not in _pk["description"])
_pm = {"problemType": "단답형", "description": "- 목록 항목입니다 충분히 긴 글" + _nl + "a) 첫째는?" + _nl + "- 마크다운 목록", "answer_text": ["x"]}
check("마크다운 목록('- 글')과 숫자·기호로 시작하는 줄은 답으로 보지 않는다", fidelity.extract_inline_answers({"입력종류": "원본"}, _pm, {}) == 0 and fidelity.extract_inline_answers({"입력종류": "원본"}, {"problemType": "단답형", "description": "a) 값은?" + _nl + "-1", "answer_text": ["x"]}, {}) == 0)
check("엑셀 단독 입력과 코딩 문제는 건드리지 않는다", fidelity.extract_inline_answers({"입력종류": "엑셀"}, {"problemType": "단답형", "description": _d, "answer_text": ""}, {}) == 0 and fidelity.extract_inline_answers({"입력종류": "원본"}, {"problemType": "코딩", "description": _d}, {}) == 0)
_pl = {"problemType": "단답형", "answer_text": {"1": ["자식"], "2": ["불가능"], "3": ["첫 줄"]}, "description": "물음" + _nl + "a) 첫째는?" + _nl + "b) 둘째는?" + _nl + "c) 셋째는?"}
check("설명이 a) b) c) 이면 정답 키 1, 2, 3 을 a, b, c 로 바꾼다 (소문항 표기가 키)", fidelity.number_short_answers(_pl, {}) is True and _pl["answer_text"] == {"a": ["자식"], "b": ["불가능"], "c": ["첫 줄"]}, _pl)
_pl2 = {"problemType": "단답형", "answer_text": ["x", "y"], "description": "a) 첫째는?" + _nl + "b) 둘째는?"}
check("번호 없는 정답 목록도 설명의 소문항 표기(a, b)로 나눈다", fidelity.number_short_answers(_pl2, {}) is True and _pl2["answer_text"] == {"a": ["x"], "b": ["y"]}, _pl2)
_pq = {"problemType": "주관식", "description": "물음에 답하시오." + _nl + "a) 부모는?" + _nl + "b) 자식은?" + _nl + "c) 설명하시오", "answer_text": "a) People" + _nl + "b) Student" + _nl + "그리고 학생", "rating_mode": "deactive"}
_rq = {}
check("소문항이 둘 이상인 주관식은 소문항별 정답이 있는 단답형으로 바꾼다 (정답이 없는 소문항은 확인필요)", fidelity.subquestions_to_short({"입력종류": "원본"}, _pq, _rq) is True and _pq["problemType"] == "단답형" and _pq["answer_text"] == {"a": ["People"], "b": ["Student\n그리고 학생"]} and _pq["rating_mode"] == "none" and any("c" in m for m in _rq["확인필요"]), (_pq, _rq))
_pq2 = {"problemType": "주관식", "description": "설명하시오." , "answer_text": "글"}
check("소문항이 없는 주관식은 그대로 둔다", fidelity.subquestions_to_short({"입력종류": "원본"}, _pq2, {}) is False and _pq2["problemType"] == "주관식")
_pq3 = {"problemType": "주관식", "description": "a) 가?" + _nl + "b) 나?", "answer_text": ""}
check("정답이 비어 있는(사람이 입력할) 주관식은 바꾸지 않는다", fidelity.subquestions_to_short({"입력종류": "원본"}, _pq3, {}) is False)
_pa = {"problemType": "단답형", "description": "물음" + _nl + "a) 부모클래스 이름은?" + _nl + "부모클래스 이름: People" + _nl + "자식클래스 이름: Student" + _nl + "b) 키워드는?", "answer_text": {"a": ["부모클래스 이름: People", "자식클래스 이름: Student"], "b": ["super"]}}
check("정답 칸에 있는 줄과 같은 줄은 설명에서 빼고 소문항 줄은 남긴다", fidelity.strip_answer_lines(_pa, {}) == 2 and "People" not in _pa["description"] and "a) 부모클래스 이름은?" in _pa["description"] and "b) 키워드는?" in _pa["description"], _pa["description"])
print("분할 문제의 '모두 작성/택1' 안내")
_sp = {"problemType": "코딩", "title": "P-1", "description": "단어 순서를 뒤집으시오." + _nl + "아래방법 모두 작성하시오." + _nl + "방법1) for 반복문 이용하시오", "problem_condition": ["[필수] 아래방법 모두 작성하시오", "[필수] 방법1) for 반복문 이용하시오"]}
_rs = {}
check("분할한 문제에서 '아래방법 모두 작성하시오' 줄과 조건을 빼고 자기 방식 조건은 남긴다", fidelity.clean_split_phrases({"입력종류": "원본", "key": "P"}, _sp, _rs) == 2 and "모두" not in _sp["description"] and _sp["problem_condition"] == ["[필수] 방법1) for 반복문 이용하시오"] and "방법1) for 반복문 이용하시오" in _sp["description"], (_sp, _rs))
_sc = {"problemType": "코딩", "title": "PY42-0002-2", "description": "고치시오.", "problem_condition": ["[필수] 두가지 방법 모두 작성하시오 ((방법2) for 문을 사용할것)", "[필수] 방법 택1 (방법1 : 교집합으로 판단)", "[필수] 데이터를 모두 삭제할 것"]}
fidelity.clean_split_phrases({"입력종류": "원본", "key": "PY42-0002"}, _sc, {})
check("조건 글에 안내와 방식 내용이 섞여 있으면 안내만 걷어내고 방식 내용·다른 조건은 남긴다", _sc["problem_condition"] == ["[필수] (방법2) for 문을 사용할것", "[필수] 방법1 : 교집합으로 판단", "[필수] 데이터를 모두 삭제할 것"], _sc["problem_condition"])
_sid = {"problemType": "코딩", "title": "NP11-0003", "description": "아래방법 모두 작성하시오. 충분히 긴 글", "problem_condition": []}
check("ID 자체가 -0003 처럼 끝나는 문제는 분할이 아니므로 건드리지 않는다", fidelity.clean_split_phrases({"입력종류": "원본", "key": "NP11-0003"}, _sid, {}) == 0)
_ssp = {"problemType": "코딩", "title": "NP11-0009-1", "description": "배열을 만드시오." + _nl + "아래방법 모두 작성하시오.", "problem_condition": ["[필수] 방법1 사용"]}
check("ID 가 -0009 로 끝나도 NP11-0009-1 처럼 -1 이 더 붙은 것은 분할이다", fidelity.clean_split_phrases({"입력종류": "원본", "key": "NP11-0009"}, _ssp, {}) == 1 and "모두" not in _ssp["description"], _ssp)
_sn = {"problemType": "코딩", "title": "P", "description": "아래방법 모두 작성하시오.", "problem_condition": []}
check("분할하지 않은 문제(제목에 -N 없음)는 건드리지 않는다", fidelity.clean_split_phrases({"입력종류": "원본", "key": "P"}, _sn, {}) == 0)
print("'-' 표시 없는 답과 그림 결과 보류")
_nl = chr(10)
_d5 = ("다음 예제 코드에 대하여 물음에 답하시오." + _nl + "a) 빈 칸에 알맞은 것은?" + _nl + "-extends" + _nl + "b) 부모클래스 이름과 자식클래스 이름을 각각 쓰시오." + _nl + "부모클래스 이름: People" + _nl + "자식클래스 이름: Student" + _nl +
       "c) 멤버들을 각각 나열하시오." + _nl + "부모클래스 멤버들: 필드[name, ssn], 메소드[talk()]" + _nl + "자식클래스 멤버들: 필드[studentNo], 메소드[study()]" + _nl +
       "d) 기본 생성자를 다음과 같이 생성하시오. 실행 결과에 대하여 설명하시오." + _nl + "People() {" + _nl + "    System.out.println(1);" + _nl + "}" + _nl + "-부모 생성자가 먼저 호출됩니다.")
_p5 = {"problemType": "주관식", "description": _d5, "answer_text": ""}
check("값을 묻는 소문항 바로 밑의 '이름: 값' 줄(- 표시 없음)도 답으로 떼어 낸다 (b, c 포함)", fidelity.extract_inline_answers({"입력종류": "원본"}, _p5, {}) == 4 and "부모클래스 이름: People" not in _p5["description"] and "부모클래스 멤버들" not in _p5["description"] and _p5["answer_text"].count(_nl + "b) ") == 1 and "b) 부모클래스 이름: People" in _p5["answer_text"] and "c) 부모클래스 멤버들" in _p5["answer_text"], (_p5["description"], _p5["answer_text"]))
check("그 소문항들의 질문 줄과 d) 의 코드 블록은 설명에 남는다", "b) 부모클래스 이름과 자식클래스 이름을 각각 쓰시오." in _p5["description"] and "People() {" in _p5["description"] and "System.out.println(1);" in _p5["description"], _p5["description"])
_p6 = {"problemType": "단답형", "description": "a) 값은 무엇인가요" + _nl + "비고: 참고 사항입니다", "answer_text": ""}
check("값을 묻는 말로 끝나지 않는 소문항 밑의 '이름: 값' 줄은 답으로 보지 않는다", fidelity.extract_inline_answers({"입력종류": "원본"}, _p6, {}) == 0 and "비고: 참고" in _p6["description"])
_hh = {"payload": None, "review": {"상태": "보류", "보류사유": "실행 결과가 그림으로만 있어 출력 예를 알 수 없음"}}
check("실행 결과가 그림뿐이라는 이유의 보류는 다시 쓰게 한다 (보류 사유가 아님)", service._hold_fail(_hh, {"key": "K"}) != [] and "보류 사유가 아닙니다" in service._hold_fail(_hh, {"key": "K"})[0], service._hold_fail(_hh, {"key": "K"}))
check("문제 본문이 그림뿐이라는 보류는 그대로 둔다", service._hold_fail({"payload": None, "review": {"상태": "보류", "보류사유": "문제 본문이 그림뿐이고 실행 결과 그림도 읽을 수 없음"}}, {"key": "K"}) == [])
print("입력·출력 머리, 글자 맞춤, 긴 코드는 제공 코드로")
_nl = chr(10)
_pio = {"problemType": "코딩", "description": "값을 출력하시오." + _nl + _nl + "- 입력" + _nl + "    - 입력값은 공백으로 구분한다." + _nl + "- 출력" + _nl + "    - 일반 출력" + _nl + "    - 리스트 출력" + _nl + "    - 딕셔너리 형태로 값을 출력해야 합니다.", "problem_condition": ["[필수] 입력값은 공백으로 구분한다"], "test_cases": [{"input": "", "expected_output": "1"}]}
fidelity.trim_description({"입력종류": "원본"}, _pio, {})
check("'- 입력/- 출력' 구역: 조건에 있는 문장·'일반 출력' 같은 짧은 이름표는 지우고 새 문장은 [출력형식] 조건으로 옮긴다", _pio["description"] == "값을 출력하시오." and "[출력형식] 딕셔너리 형태로 값을 출력해야 합니다." in _pio["problem_condition"] and len(_pio["problem_condition"]) == 2, _pio)
_plk = {"problemType": "코딩", "description": "함수를 만드시오." + _nl + "- 조건" + _nl + "    - [Trinket](https://trinket.io/x)" + _nl + "    - 함수 이름은 f 로 한다", "problem_condition": [], "test_cases": [{"input": "", "expected_output": "1"}]}
fidelity.trim_description({"입력종류": "원본"}, _plk, {})
check("남기는 링크 줄은 글머리표를 벗겨 남긴다", _plk["description"] == "함수를 만드시오." + _nl + "[Trinket](https://trinket.io/x)", _plk["description"])
_rec = {"입력종류": "원본", "원본조각": "책의 정보를 저장하는 Book클래스에 대하여 질문에 답하세요" + _nl + "1) 생성자를 구현하세요." + _nl + "제출 방법: 이메일"}
_pal = {"description": "책의 정보를 저장하는 Book클래스에 대하여 질문에 답세요" + _nl + "1) 생성자를 구현하세요."}
check("AI 가 글자를 틀리게 옮긴 줄은 원문 줄로 되돌리고, AI 가 뺀 잡음 줄(제출 방법)은 되살리지 않는다", fidelity.align_description_to_source(_rec, _pal, {}) == 1 and _pal["description"] == "책의 정보를 저장하는 Book클래스에 대하여 질문에 답하세요" + _nl + "1) 생성자를 구현하세요.", _pal)
_pal2 = {"description": "전혀 다른 문장으로 요약했습니다." + _nl + "1) 생성자를 구현하세요."}
check("원문과 많이 다른 줄(요약·재서술)은 바꾸지 않는다", fidelity.align_description_to_source(_rec, _pal2, {}) == 0 and "요약" in _pal2["description"])
check("그림이 붙은 문제나 엑셀 단독 입력은 건드리지 않는다", fidelity.align_description_to_source({**_rec, "이미지": [{"n": 1}]}, {"description": "책의 정보를 저장하는 Book클래스에 대하여 질문에 답세요"}, {}) == 0 and fidelity.align_description_to_source({"입력종류": "엑셀"}, {"description": "답세요"}, {}) == 0)
_cb = "class Test {" + _nl + "  public static void main(String[] a) {" + _nl + "    Obesity o = new Obesity();" + _nl + "    o.print();" + _nl + "  }" + _nl + "}"
_pc = {"problemType": "코딩", "description": "다음 클래스를 테스트하시오." + _nl + _cb + _nl + "결과를 확인하시오.", "reference_codes": [{"language": "java", "code": "x"}]}
_rc = {}
check("코딩 문제의 설명에 코드가 4줄 이상이면 제공 코드로 옮기고 유형을 디버깅으로 바꾼다 (언어는 정답 코드의 언어)", fidelity.promote_code_block({"입력종류": "원본"}, _pc, _rc) == 6 and _pc["problemType"] == "디버깅" and _pc["base_code"][0]["language"] == "java" and "class Test" not in _pc["description"] and "결과를 확인하시오." in _pc["description"] and _rc["정리"], (_pc, _rc))
_ps = {"problemType": "코딩", "description": "다음 코드를 보시오." + _nl + "int a = 1;" + _nl + "int b = 2;" + _nl + "int c = 3;" + _nl + "마지막 문장입니다.", "reference_codes": [{"language": "c", "code": "x"}]}
_pb1 = {"problemType": "디버깅", "description": "main 을 완성하시오." + _nl + _cb + _nl + "끝.", "base_code": [{"language": "java", "code": "class Test {" + _nl + "  public static void main(String[] a) {" + _nl + "    Obesity o = new Obesity();" + _nl + "    o.print();" + _nl + "  }" + _nl + "}" + _nl + "class Obesity {}"}]}
fidelity.promote_code_block({"입력종류": "원본"}, _pb1, {})
check("제공 코드가 이미 있고 설명의 코드가 거기 들어 있으면(제공 코드가 더 길어도) 설명에서만 뺀다", "class Test" not in _pb1["description"] and _pb1["base_code"][0]["code"].count("class Test") == 1, _pb1)
_pb2 = {"problemType": "디버깅", "description": "main 을 완성하시오." + _nl + _cb + _nl + "끝.", "base_code": [{"language": "java", "code": "class Obesity {" + _nl + "  void print() {}" + _nl + "}"}]}
fidelity.promote_code_block({"입력종류": "원본"}, _pb2, {})
check("제공 코드에 없는 설명 속 코드는 제공 코드 끝에 덧붙이고 설명에서 뺀다", "class Test" not in _pb2["description"] and _pb2["base_code"][0]["code"].startswith("class Obesity {") and "main(String[] a)" in _pb2["base_code"][0]["code"], _pb2)
check("코드가 3줄이면 설명에 그대로 둔다 (짧은 코드·예시)", fidelity.promote_code_block({"입력종류": "원본"}, _ps, {}) == 0 and _ps["problemType"] == "코딩")
check("단답형·엑셀 단독은 건드리지 않는다 (단답형은 코드가 문제 자체)", fidelity.promote_code_block({"입력종류": "원본"}, {"problemType": "단답형", "description": "결과는?" + _nl + _cb}, {}) == 0 and fidelity.promote_code_block({"입력종류": "엑셀"}, {"problemType": "코딩", "description": "설명" + _nl + _cb}, {}) == 0)
print("설명만으로 풀 수 없는 문제는 보류")
_nl = chr(10)
_c2 = "4장 개념 확인 11번 문제를 해결한 소스코드와 결과를 제시하세요" + _nl + "■ 코드" + _nl + "#include <iostream>" + _nl + "class Rectangle {" + _nl + "public:" + _nl + "  double getWidth() const { return 1; }" + _nl + "};" + _nl + "int main() {" + _nl + "  return 0;" + _nl + "}"
_why = fidelity.unsolvable_reference({"입력종류": "원본", "원본조각": _c2})
check("교재 문제 번호만 있고 내용이 없는 문제(코드가 같이 있어도)는 보류 사유가 나온다", _why and "개념 확인 11번" in _why, _why)
check("외부 번호가 있어도 그 문제를 푸는 것이 과제가 아니라 '~와 같이' 로 요구사항을 말하면 보류하지 않는다", fidelity.unsolvable_reference({"입력종류": "원본", "원본조각": "교재 5번 문제와 같이 두 정수를 입력받아 합을 출력하시오."}) is None)
check("(긴 설명) 문제 요구사항이 충분히 적혀 있으면 외부 번호가 있어도 보류하지 않는다", fidelity.unsolvable_reference({"입력종류": "원본", "원본조각": "교재 5번 문제를 풀어서 두 정수를 입력받아 합과 차를 구해 각각 한 줄씩 출력하는 프로그램을 작성하시오. 입력은 공백으로 구분하고 출력은 합, 차 순서이며 음수도 처리해야 하고 예외 입력은 무시한다. 입력이 하나뿐이면 오류 문구를 출력하고 종료한다. 출력은 줄바꿈으로 구분하며 불필요한 공백을 넣지 않는다."}) is None)
check("외부 번호가 없는 짧은 문제는 보류하지 않는다", fidelity.unsolvable_reference({"입력종류": "원본", "원본조각": "두 수의 합을 출력하시오."}) is None and fidelity.unsolvable_reference({"입력종류": "엑셀", "원본조각": _c2}) is None)
_hd = service._forced_hold({"입력종류": "원본", "key": "X-02", "원본조각": _c2, "intake": {}})
check("서버가 AI 를 부르기 전에 보류 결과를 만든다", _hd and _hd["payload"] is None and _hd["review"]["상태"] == "보류" and "11번" in _hd["review"]["보류사유"], _hd)
print("원문에서 찾은 소문항 답으로 정답 칸 채우기")
_src = ("다음 예제 코드에 대하여 물음에 답하시오." + _nl + "a) 빈 칸에 알맞은 것은?" + _nl + "-extends" + _nl + "b) 부모클래스 이름과 자식클래스 이름을 각각 쓰시오." + _nl + "부모클래스 이름: People" + _nl + "자식클래스 이름: Student" + _nl +
        "d) 기본 생성자를 생성하시오. 실행 결과에 대하여 설명하시오." + _nl + "People() {" + _nl + "}" + _nl + "-부모 생성자가 먼저 호출됩니다." + _nl + "f) 오류를 수정하시오." + _nl + "-super() 를 호출한다")
_ai = {"problemType": "주관식", "description": "다음 예제 코드에 대하여 물음에 답하시오." + _nl + "a) 빈 칸에 알맞은 것은? -extends" + _nl + "b) 부모클래스 이름과 자식클래스 이름을 각각 쓰시오." + _nl + "d) 기본 생성자를 생성하시오. 실행 결과에 대하여 설명하시오." + _nl + "f) 오류를 수정하시오.", "answer_text": "", "rating_mode": "deactive"}
_ra = {}
check("AI 가 줄을 합치고 답을 못 옮겼어도 원문에서 a, b, d, f 의 답을 찾아 소문항별 정답(단답형)으로 채운다", fidelity.fill_answers_from_source({"입력종류": "원본", "원본조각": _src}, _ai, _ra) == 4 and _ai["problemType"] == "단답형" and list(_ai["answer_text"]) == ["a", "b", "d", "f"] and _ai["answer_text"]["a"] == ["extends"] and "People" in _ai["answer_text"]["b"][0] and _ai["answer_text"]["f"] == ["super() 를 호출한다"], _ai)
check("소문항 줄 끝에 합쳐진 답('… 알맞은 것은? -extends')은 설명에서 뗀다", fidelity.strip_answer_lines(_ai, {}) >= 1 and "-extends" not in _ai["description"] and "a) 빈 칸에 알맞은 것은?" in _ai["description"], _ai["description"])
_rm = {}
_ai2 = {"problemType": "단답형", "description": "물음" + _nl + "a) 첫째?" + _nl + "b) 둘째?" + _nl + "c) 셋째?", "answer_text": {"a": ["x"], "b": ["y"]}}
check("정답이 없는 소문항(c)은 확인필요에 한 번만 적는다", fidelity.check_missing_subanswers(_ai2, _rm) == 1 and fidelity.check_missing_subanswers(_ai2, _rm) == 1 and sum(1 for m in _rm["확인필요"] if "정답이 없는 소문항" in m) == 1 and "c" in _rm["확인필요"][0], _rm)
print("그림 제출 요구, 이름표 붙은 입력 자료, 방식별 문제")
_nl = chr(10)
_s1 = {"problemType": "주관식", "description": "프로그램을 작성하고 실행 결과를 캡처하여 제출하시오." + _nl + "원리를 설명하시오."}
_rs = {}
check("주관식: '실행 결과를 캡처하여 제출하시오' 는 '글로 쓰시오' 로 고쳐 글로 답하게 한다", fidelity.fix_screenshot_requests({"입력종류": "원본"}, _s1, _rs) == 1 and "캡처" not in _s1["description"] and "실행 결과를 글로 쓰시오" in _s1["description"] and "원리를 설명하시오." in _s1["description"] and _rs["정리"], _s1)
_s2 = {"problemType": "코딩", "description": "합을 구하시오." + _nl + "실행 화면을 스크린샷으로 제출하시오.", "test_cases": []}
check("코딩: 화면 제출 안내 줄은 뺀다 (서버가 채점)", fidelity.fix_screenshot_requests({"입력종류": "원본"}, _s2, {}) == 1 and _s2["description"] == "합을 구하시오.", _s2)
check("그림 제출 요구가 없거나 엑셀 단독 입력이면 건드리지 않는다", fidelity.fix_screenshot_requests({"입력종류": "원본"}, {"problemType": "단답형", "description": "결과를 쓰시오. 화면에 출력되는 값을 쓴다"}, {}) == 0 and fidelity.fix_screenshot_requests({"입력종류": "엑셀"}, {"problemType": "단답형", "description": "캡처하여 제출"}, {}) == 0)
_txt = "np1 배열에서 3의 배수의 위치를 모두 찾아 출력하시오." + _nl + "- 조건" + _nl + "- 방법1 : LC 이용" + _nl + _nl + "0   1   2   3   4   5" + _nl + "6   7   8   9   10   11" + _nl + "··· np1" + _nl + "- 출력 예" + _nl + "[(0, 0)]"
check("원문의 '··· np1' 이름표 위 줄들이 np1 의 값으로 읽힌다", fidelity.named_blocks(_txt) == {"np1": "0   1   2   3   4   5" + _nl + "6   7   8   9   10   11"}, fidelity.named_blocks(_txt))
_pn = {"description": "np1 배열에서 3의 배수의 위치를 모두 찾아 출력하시오."}
_rn = {}
check("설명이 np1 을 가리키는데 값이 없으면 원문에서 되살려 설명 끝에 'np1:' 과 함께 둔다 (설명만 보고 풀 수 있게)", fidelity.restore_named_blocks({"입력종류": "원본", "원본조각": _txt}, _pn, _rn) == 1 and _pn["description"].endswith("np1:" + _nl + "0   1   2   3   4   5" + _nl + "6   7   8   9   10   11"), _pn)
_pn2 = {"description": "체스보드 판을 그리는 프로그램을 작성하시오."}
check("설명이 그 이름을 가리키지 않으면 되살리지 않는다", fidelity.restore_named_blocks({"입력종류": "원본", "원본조각": _txt}, _pn2, {}) == 0)
_pn3 = {"description": "np1 배열에서 찾으시오." + _nl + "np1:" + _nl + "0   1   2   3   4   5"}
check("이미 값이 있으면 다시 넣지 않는다", fidelity.restore_named_blocks({"입력종류": "원본", "원본조각": _txt}, _pn3, {}) == 0)
_pm = {"problemType": "코딩", "description": "단어를 뒤집으시오." + _nl + "방법1) for 반복문 이용하시오" + _nl + "방법2) LC 사용", "problem_condition": ["[필수] 방법1) for 반복문 이용하시오", "[필수] 방법2) LC 사용"]}
_rm = {}
check("서버가 나눈 '방법2' 문제에서는 방법1 안내 줄과 조건을 뺀다", fidelity.drop_other_methods({"입력종류": "원본", "방식분할": "방법2"}, _pm, _rm) == 2 and "방법1" not in _pm["description"] and "방법2) LC 사용" in _pm["description"] and _pm["problem_condition"] == ["[필수] 방법2) LC 사용"], _pm)
check("나누지 않은 문제는 건드리지 않는다", fidelity.drop_other_methods({"입력종류": "원본"}, {"description": "방법1 방법2"}, {}) == 0)
print("테스트 케이스 빈칸 검사")
_g = lambda tcs, code: fidelity.test_case_gaps({"problemType": "코딩", "test_cases": tcs, "reference_codes": [{"code": code}]})
check("기대 출력이 빈 케이스는 입력 필요", any("기대 출력" in x for x in _g([{"input": "", "expected_output": ""}], "class A{};")))
check("입력을 읽는 코드인데 입력이 빈 케이스는 입력 필요", any("입력이 비어" in x for x in _g([{"input": "", "expected_output": "3"}], "n = int(input())")))
check("입력을 읽지 않는 코드의 빈 입력은 정상", _g([{"input": "", "expected_output": "3"}], "print(3)") == [])
check("테스트 케이스가 아예 없으면 입력 필요", any("없습니다" in x for x in _g([], "print(1)")))
check("객관식 등 코딩·디버깅이 아니면 검사하지 않는다", fidelity.test_case_gaps({"problemType": "객관식", "test_cases": []}) == [])
check("글로 읽은 표의 행 번호(3칸 공백)가 설명 앞에 붙으면 뺀다", (lambda p: (fidelity.strip_row_number({"입력종류": "원본"}, p, {}), p["description"]))({"description": "3   프로세스와 스레드의 차이를 설명하시오."}) == (1, "프로세스와 스레드의 차이를 설명하시오."))
check("일반 설명(1. 두 수 …)은 건드리지 않는다", fidelity.strip_row_number({"입력종류": "원본"}, {"description": "1. 두 수의 합을 구하시오."}, {}) == 0)

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
