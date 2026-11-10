"""입력에 맞춰 프롬프트를 줄여 보내는 기능(prompt_trim) 시험 (AI 호출 없음).
noti_test 폴더에서:  python test_prompt_trim.py"""
import json, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import config, llm

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

P = open(config.prompt_path(), encoding="utf-8").read()
NL = chr(10)
def user(memo=None, **rec):
    if memo: rec["intake"] = {"메모": memo}
    return "채점 모드: none" + NL + "입력: " + json.dumps(rec, ensure_ascii=False)
def trim(**kw): return llm.trim_prompt(P, user(**kw))
def has(t, head): return NL + head in t
xl = trim(입력종류="엑셀", 표형식="엑셀")
db = trim(입력종류="엑셀", 표형식="DB")
pdf = trim(입력종류="원본", 원본형식="PDF")
word_img = trim(입력종류="원본", 원본형식="워드", memo=["그림 3개를 함께 보냄"])
hangul = trim(입력종류="원본", 원본형식="한글")
both = trim(입력종류="둘 다", 원본형식="PDF", 표형식="엑셀")

print("1. 쓰는 형식 규칙만 남긴다")
check("엑셀 입력: 문서 형식 규칙을 모두 빼고 엑셀 규칙만 남긴다", not any(has(xl, h) for h in ("[PDF]", "[워드", "[파워포인트", "[한글", "[텍스트·마크다운", "[DB(SQLite)]")) and has(xl, "[엑셀·CSV]"))
check("DB 입력: DB 규칙만 남기고 엑셀 규칙은 뺀다", has(db, "[DB(SQLite)]") and not has(db, "[엑셀·CSV]"))
check("PDF 원본 입력: PDF 규칙만 남기고 워드·PPT·한글·표 형식 규칙은 뺀다", has(pdf, "[PDF]") and not any(has(pdf, h) for h in ("[워드", "[파워포인트", "[한글", "[엑셀·CSV]", "[DB(SQLite)]")))
check("한글 원본 입력: 한글 규칙에 더해 워드 규칙도 남긴다 (한글은 워드 기준을 따름)", has(hangul, "[한글") and has(hangul, "[워드") and not has(hangul, "[PDF]"))
check("둘 다 입력: 쓰는 원본 형식(PDF)과 표 형식(엑셀) 규칙을 남기고 나머지는 뺀다", has(both, "[PDF]") and has(both, "[엑셀·CSV]") and not any(has(both, h) for h in ("[워드", "[한글", "[DB(SQLite)]")) and len(both) < len(P))
check("형식을 알 수 없는 입력은 줄이지 않는다", llm.trim_prompt(P, "입력 없음") == P)
print("2. 그림 규칙은 그림이 붙을 때만")
check("그림이 없으면 그림 첨부 규칙을 뺀다", not has(pdf, "[그림 첨부]") and not has(xl, "[그림 첨부]"))
check("메모에 그림 안내가 있으면 그림 첨부 규칙을 남긴다", has(word_img, "[그림 첨부]") and "직접 읽고 글로 옮깁니다" in word_img)
check("DB 에 담긴 그림 안내가 있어도 남긴다", has(trim(입력종류="엑셀", 표형식="DB", memo=["DB 에 담긴 그림 2개를 함께 보냄"]), "[그림 첨부]"))
print("3. 공통 규칙과 예시")
for name, t in (("엑셀", xl), ("DB", db), ("PDF", pdf), ("워드+그림", word_img), ("한글", hangul), ("둘 다", both)):
    check(f"{name}: 출력 형식·누락 처리표·보류 조건·기록 규칙·요청·항목 매핑이 모두 있다", all(f"<{s}>" in t and f"</{s}>" in t for s in ("출력 형식", "누락 처리표", "보류 조건", "기록 규칙", "요청", "항목 매핑")))
    check(f"{name}: 형식별 필터링의 여닫는 태그가 맞고 공통 잡음 규칙이 남는다", t.count(NL + "<형식별 필터링>" + NL) == t.count(NL + "</형식별 필터링>" + NL) == 1 and "[공통 잡음]" in t)
check("프롬프트에는 예시가 없다 (규칙과 출력 형식 틀로만 가르친다)", all("<예시" not in x for x in (xl, pdf, both, P)))
print("4. 크기")
check("입력 종류별로 줄인 프롬프트는 14,500자 이하 (그림이 붙은 워드 원본 포함)", all(len(t) <= 14500 for t in (xl, db, pdf, word_img, hangul)), [len(t) for t in (xl, db, pdf, word_img, hangul)])
print("5. 그림 여부를 서버가 직접 알려 줄 때")
u = user(입력종류="원본", 원본형식="PDF")
check("그림을 실제로 보내면 입력 글에 안내가 없어도 그림 규칙을 남긴다", has(llm.trim_prompt(P, u, has_images=True), "[그림 첨부]"))
check("그림이 없다고 알리면 입력 글에 안내가 있어도 그림 규칙을 뺀다", not has(llm.trim_prompt(P, user(입력종류="원본", 원본형식="워드", memo=["그림 3개를 함께 보냄"]), has_images=False), "[그림 첨부]"))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
