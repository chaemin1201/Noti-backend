"""한글(.hwp/.hwpx) 읽기 시험: 합성 데이터로 자동 번호 되살리기, 글머리표, 수준 초기화, 문제 나누기, 바이너리 번호 서식 해석을 확인한다.
실제 한글 파일은 필요 없다. 실제 파일 시험은 한컴오피스에서 변환한 파일로 따로 했다 (CHANGES.md 참고).
noti_test 폴더에서:  python test_hwp_text.py"""
import os, struct, sys, tempfile, zipfile
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.readers import hwp_text
from app.inputdata.intake.readers import pdf_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

NS = 'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
HEADER = f"""<?xml version="1.0" encoding="UTF-8"?><hh:head {NS}><hh:refList>
<hh:numberings itemCnt="2">
 <hh:numbering id="3" start="1"><hh:paraHead start="1" level="1" numFormat="DIGIT">(^1)</hh:paraHead><hh:paraHead start="1" level="2" numFormat="HANGUL_SYLLABLE">^2.</hh:paraHead></hh:numbering>
 <hh:numbering id="2" start="1"><hh:paraHead start="1" level="1" numFormat="DIGIT"></hh:paraHead></hh:numbering>
</hh:numberings>
<hh:paraProperties itemCnt="5">
 <hh:paraPr id="0"><hh:heading type="NONE" idRef="0" level="0"/></hh:paraPr>
 <hh:paraPr id="20"><hh:heading type="NUMBER" idRef="3" level="0"/></hh:paraPr>
 <hh:paraPr id="21"><hh:heading type="NUMBER" idRef="3" level="1"/></hh:paraPr>
 <hh:paraPr id="22"><hh:heading type="BULLET" idRef="1" level="0"/></hh:paraPr>
 <hh:paraPr id="23"><hh:heading type="NUMBER" idRef="2" level="0"/></hh:paraPr>
</hh:paraProperties></hh:refList></hh:head>"""

def p(ppid, text): return f'<hp:p paraPrIDRef="{ppid}"><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
SECTION = f"""<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>
{p(0, 'C++_09_번호테스트 학번 :')}
{p(20, '첫 문제를 푸세요')}
{p(21, '세부 항목')}
{p(22, '글머리 항목')}
{p(23, '글리프 글머리')}
{p(20, '둘째 문제를 푸세요')}
{p(21, '다시 세부')}
{p(0, '번호 없는 문장')}
</hs:sec>"""

tmp = tempfile.mkdtemp()
f = os.path.join(tmp, "n.hwpx")
with zipfile.ZipFile(f, "w") as z:
    z.writestr("mimetype", "application/hwp+zip"); z.writestr("Contents/header.xml", HEADER); z.writestr("Contents/section0.xml", SECTION)
lines = hwp_text.hwpx_text(f).splitlines()

print("1. hwpx 자동 번호")
check("번호 문단에 (1) (2) 가 붙음", "(1) 첫 문제를 푸세요" in lines and "(2) 둘째 문제를 푸세요" in lines, lines)
check("하위 수준은 가. 로, 상위 번호가 올라가면 다시 가. 부터", "가. 세부 항목" in lines and "가. 다시 세부" in lines, lines)
check("글머리표(BULLET)와 글리프 번호 서식은 '-'", "- 글머리 항목" in lines and "- 글리프 글머리" in lines, lines)
check("번호 없는 문단은 그대로", "번호 없는 문장" in lines and "C++_09_번호테스트 학번 :" in lines, lines)
ids = [m[0] for m in pdf_intake.marks_of("\n".join(lines))]
check("문서 제목 + (n) 으로 문제가 나뉨 (C++_09_01, 02)", ids == ["C++_09_01", "C++_09_02"], ids)

print("2. 번호 서식이 없는 hwpx 는 예전처럼 글자만")
f2 = os.path.join(tmp, "plain.hwpx")
with zipfile.ZipFile(f2, "w") as z: z.writestr("Contents/section0.xml", SECTION)
check("header.xml 이 없어도 오류 없이 글자를 읽음", "첫 문제를 푸세요" in hwp_text.hwpx_text(f2).splitlines())

print("3. 번호 세기 도구 (hwp 와 공통)")
an = hwp_text._AutoNumber({1: {1: ("DIGIT", "(^1)", 1), 2: ("HANGUL_SYLLABLE", "^2.", 1), 3: ("ROMAN_SMALL", "^3)", 1)}, 2: {1: ("LATIN_CAPITAL", "^1.", 1)}, 3: {1: ("DIGIT", "^N", 1)}})
seq = [an.label(1, 1), an.label(1, 2), an.label(1, 2), an.label(1, 3), an.label(1, 1), an.label(1, 2)]
check("수준별로 센다 / 상위가 올라가면 하위 초기화", seq == ["(1)", "가.", "나.", "i)", "(2)", "가."], seq)
check("영문 대문자 형식", [an.label(2, 1), an.label(2, 1)] == ["A.", "B."])
check("^N 문구(개요·쪽 번호)와 없는 서식은 번호를 붙이지 않음", an.label(3, 1) == "" and an.label(99, 1) == "")
check("단위: 로마 소문자·한글 가나다·동그라미", [hwp_text._fmt_num(4, "ROMAN_SMALL"), hwp_text._fmt_num(3, "HANGUL_SYLLABLE"), hwp_text._fmt_num(2, "CIRCLED_DIGIT")] == ["iv", "다", "②"])

print("4. hwp 바이너리 번호 서식 해석 (합성 레코드)")
def level(fmt_code, pat):
    s = pat.encode("utf-16-le")
    return struct.pack("<IHHI", fmt_code << 5, 0, 0, 0) + struct.pack("<H", len(pat)) + s
rec = level(0, "(^1)") + level(8, "^2.") + b"".join(level(0, "") for _ in range(5)) + struct.pack("<H", 1) + struct.pack("<7I", *([1] * 7))
heads = hwp_text._hwp_numbering_record(rec)
check("수준 1: 숫자 / (^1)", heads.get(1) == ("DIGIT", "(^1)", 1), heads.get(1))
check("수준 2: 한글 가나다 / ^2.", heads.get(2) == ("HANGUL_SYLLABLE", "^2.", 1), heads.get(2))
check("7개 수준을 모두 읽음", len(heads) == 7, len(heads))
rec0 = level(0, "^1.") + b"".join(level(0, "") for _ in range(6)) + struct.pack("<H", 0) + struct.pack("<7I", *([0] * 7))
check("시작 번호 0 도 그대로 (첫 문단이 0.)", hwp_text._hwp_numbering_record(rec0)[1][2] == 0)
def record(tag, body): return struct.pack("<I", tag | (len(body) << 20)) + body
doc = record(hwp_text.TAG_NUMBERING, rec) + record(hwp_text.TAG_PARA_SHAPE, struct.pack("<I", 2 << 23) + b"\0" * 26 + struct.pack("<H", 1) + b"\0" * 8)
shapes = [(( struct.unpack_from("<I", b, 0)[0] >> 23) & 3, struct.unpack_from("<H", b, 30)[0]) for t, _l, b in hwp_text._records(doc) if t == hwp_text.TAG_PARA_SHAPE]
check("문단 모양에서 번호 종류(2)와 번호 서식 번호(1)를 읽음", shapes == [(2, 1)], shapes)

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
