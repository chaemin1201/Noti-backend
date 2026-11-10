"""PDF 읽기·나누기 시험 (실제 사례): ① pdftotext 를 -enc UTF-8 로 부르지 않아 한글이 모두 사라졌다. ② Java 실습 PDF 는 'ID 정규식'도 '(n) 항목'도 없고 '실습 1.' 제목뿐이라 문제를 하나도 찾지 못했다.
noti_test 폴더에서:  python test_pdf_reading.py"""
import os, sys, tempfile
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.readers import pdf_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

print("1. pdftotext 인코딩")
calls = []
class _R: stdout = "한글"
real = pdf_intake.subprocess.run
pdf_intake.subprocess.run = lambda cmd, **kw: (calls.append(cmd), _R())[1]
try: out = pdf_intake.read_text("a.pdf")
finally: pdf_intake.subprocess.run = real
check("PDF 는 -enc UTF-8 로 읽는다 (없으면 Latin1 로 나와 한글이 사라짐)", calls and "-enc" in calls[0] and calls[0][calls[0].index("-enc") + 1] == "UTF-8", calls)

print("2. 파일 이름 → 묶음 이름")
fs = pdf_intake.file_stem
check("문제 파일과 풀이 파일이 같은 이름이 된다", fs("D:/x/2025_자바프로그래밍1_실습_5주차_조건문_문제.pdf") == fs("D:" + chr(92) + "x" + chr(92) + "2025_자바프로그래밍1_실습_5주차_조건문_풀이.pdf") == "자바프로그래밍1_실습_5주차_조건문", fs("2025_자바프로그래밍1_실습_5주차_조건문_문제.pdf"))
check("꼬리가 없으면 그대로, 공백은 없앤다", fs("자바프로그래밍1_실습_6주차 반복.pdf") == "자바프로그래밍1_실습_6주차반복" and fs("자바프로그래밍1_실습_6주차 반복_풀이.pdf") == "자바프로그래밍1_실습_6주차반복")
check("폴더 이름은 섞이지 않는다", "/" not in fs("C:/문제 생성 목록/a_풀이.pdf") and chr(92) not in fs("C:" + chr(92) + "문제 생성 목록" + chr(92) + "a_풀이.pdf"))

print("3. '실습 N.' 제목으로 나누기")
TXT = "자바 실습\n\n실습 1. 두 수를 비교하시오.\n출력결과\n23\n\n실습 2. 홀짝을 판단하시오.\n  짝수\n\n실습 3. 함수값을 구하시오.\n16.0\n"
ms = pdf_intake.heading_marks(TXT, "S")
check("번호 제목마다 구간이 생긴다", [m[0] for m in ms] == ["S_01", "S_02", "S_03"], ms)
two = pdf_intake.heading_marks("실습 1. a\n내용\n실습 2. b\n내용\n실습 1. c\n내용\n실습 2. d\n내용\n", "S")
check("번호가 1로 되돌아가면 새 묶음이라 서로 덮어쓰지 않는다", [m[0] for m in two] == ["S_01", "S_02", "S_01b", "S_02b"], two)
check("번호 제목이 하나뿐이면 문제지로 보지 않는다", pdf_intake.heading_marks("실습 1. 소개\n", "S") == [])
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "2025_자바_실습_5주차_문제.txt"); open(p, "w", encoding="utf-8").write(TXT)
    got = list(pdf_intake.sections(p))
    check("sections 가 파일 이름 + 번호를 ID 로 쓴다", [g[0] for g in got] == ["자바_실습_5주차_01", "자바_실습_5주차_02", "자바_실습_5주차_03"], [g[0] for g in got])
    check("각 구간 본문에 해당 문제 내용이 있다", "홀짝" in got[1][2] and "16.0" in got[2][2], got[1])
    p2 = os.path.join(d, "x.txt"); open(p2, "w", encoding="utf-8").write("문제 PY11-0001 첫째\n내용\n문제 PY11-0002 둘째\n내용\n")
    check("기존 'ID 정규식' 문서는 그대로 ID 로 나눈다", [g[0] for g in pdf_intake.sections(p2)] == ["PY11-0001", "PY11-0002"])
    check("pattern 을 지정했는데 맞는 것이 없으면 번호 제목으로 넘어가지 않는다", list(pdf_intake.sections(p, __import__("re").compile(r"(ZZZ\d+)"))) == [])

NUM = "자바 실습_상속\n 0. 퀴즈를 푸시오. (안내)\n 1. 상속이란?\na) 주체는?\nb) 다중 상속은?\n 2. 다음 코드를 보시오.\nint x = 3.\n  1. 코드 속 번호\n 3. 결과는?\n"
nm = pdf_intake.heading_marks(NUM, "S")
check("번호만 있는 제목은 1, 2, 3 … 순서로 이어지는 것만 문제로 본다 (0번 안내와 코드 속 번호 제외)", [m[0] for m in nm] == ["S_01", "S_02", "S_03"], nm)
check("a) b) 소문항과 번호가 하나뿐인 문서는 문제로 나누지 않는다", pdf_intake.heading_marks("제목\n 1. 하나뿐\na) x\n", "S") == [])
check("낱말 제목('실습 1.')이 있으면 번호만 있는 제목은 쓰지 않는다", [m[0] for m in pdf_intake.heading_marks("실습 1. a\n 1. 가\n실습 2. b\n 2. 나\n", "S")] == ["S_01", "S_02"])

print("4. 업로드 경로: 임시 이름(f0, f1)으로 저장돼도 원래 이름으로 문제·풀이를 짝짓는다")
from app.inputdata.intake import parsing
with tempfile.TemporaryDirectory() as d:
    a, b = os.path.join(d, "f0.txt"), os.path.join(d, "f1.txt")
    open(a, "w", encoding="utf-8").write(TXT); open(b, "w", encoding="utf-8").write(TXT.replace("출력결과", "정답코드"))
    kind, recs = parsing.build_records(None, [a, b], labels=["2025_자바_실습_5주차_문제.txt", "2025_자바_실습_5주차_풀이.txt"])
    check("문제 3개로 합쳐지고 ID 에 임시 이름이 섞이지 않는다", [r["id"] for r in recs] == ["자바_실습_5주차_01", "자바_실습_5주차_02", "자바_실습_5주차_03"], [r["id"] for r in recs])
    check("풀이 파일은 정답자료로 붙는다", all(r.get("정답자료") for r in recs) and "정답코드" in recs[0]["정답자료"])
print("poppler(pdftotext) 위치 찾기")
import shutil as _sh, tempfile as _tf
_which = _sh.which
_old_env = os.environ.get("POPPLER_PATH")
try:
    _sh.which = lambda name, *a, **k: None                         # PATH 에 없는 상태
    os.environ.pop("POPPLER_PATH", None)
    check("PATH 에도 알려진 위치에도 없으면 None (안내 문구가 나가게 한다)", pdf_intake.poppler_exe("no_such_tool_xyz") is None)
    with _tf.TemporaryDirectory() as _d:
        _exe = os.path.join(_d, "pdftotext" + (".exe" if os.name == "nt" else ""))
        open(_exe, "w").close()
        os.environ["POPPLER_PATH"] = _d
        check("환경변수 POPPLER_PATH 의 폴더에 있으면 그것을 쓴다", pdf_intake.poppler_exe("pdftotext") == _exe, pdf_intake.poppler_exe("pdftotext"))
    os.environ.pop("POPPLER_PATH", None)
    try: pdf_intake.read_text(os.path.join(tempfile.gettempdir(), "x.pdf")) if False else None
    except Exception: pass
    check("안내 문구에 설치 방법이 들어 있다", "poppler" in pdf_intake.POPPLER_HELP and "POPPLER_PATH" in pdf_intake.POPPLER_HELP)
finally:
    _sh.which = _which
    if _old_env is not None: os.environ["POPPLER_PATH"] = _old_env
print("실행환경 링크는 첨부 확인 대상이 아니다")
_b1 = pdf_intake.intake("문제입니다. 실행은 [Trinket](https://trinket.io/embed/python3/6e396e6a97) 에서 하세요. 충분히 긴 문제 본문입니다.")
check("Trinket 링크만 있으면 링크 표시도 첨부 메모도 없다", _b1["링크"] is False and not any("링크" in m for m in _b1["메모"]), _b1)
_b2 = pdf_intake.intake("문제입니다. 영상은 https://youtu.be/abc 와 영상.mp4 를 보세요. 충분히 긴 문제 본문입니다.")
check("영상·자료 링크는 그대로 첨부 확인 대상", _b2["링크"] is True and any("링크" in m for m in _b2["메모"]), _b2)
print("문제 조각의 잡음 걷어내기 (번호 잔재·구역 표시·정답 구역)")
_nl = chr(10)
_raw = "-4" + _nl + "다음 프로그램의 결과를 작성해보자." + _nl + "import numpy as np" + _nl + "print(np.arange(3))" + _nl + "- 정답" + _nl + "import numpy as np" + _nl + "print(np.arange(3)[1])" + _nl + _nl + "<추가문제>"
_t, _a = pdf_intake.clean_section(_raw)
check("앞의 번호 잔재(-4)와 끝의 구역 표시(<추가문제>)를 지운다", _t.splitlines()[0] == "다음 프로그램의 결과를 작성해보자." and "<추가문제>" not in _t and not _t.startswith("-4"), _t)
check("'- 정답' 구역은 설명에서 떼어 정답 자료로 돌려준다", "print(np.arange(3)[1])" not in _t and _a and "print(np.arange(3)[1])" in _a and "<추가문제>" not in _a, (_t, _a))
_t2, _a2 = pdf_intake.clean_section("두 수의 합을 출력하시오." + _nl + "정답을 쓰시오.")
check("문장 속의 '정답'은 정답 구역 머리가 아니므로 그대로 둔다", _a2 is None and "정답을 쓰시오." in _t2, (_t2, _a2))
_t3, _a3 = pdf_intake.clean_section("1" + _nl + "문제 본문입니다 충분히 깁니다." + _nl + "풀이" + _nl + "답안 내용")
check("풀이·해설·해답 머리도 정답 구역으로 본다", _a3 == "답안 내용" and _t3 == "문제 본문입니다 충분히 깁니다.", (_t3, _a3))
_t4, _a4 = pdf_intake.clean_section("1" + _nl + "정답")
check("본문이 남지 않으면 원래 조각을 그대로 돌려준다", _t4 == "1" + _nl + "정답" and _a4 is None, (_t4, _a4))
_t5, _a5 = pdf_intake.clean_section("<기본문제>" + _nl + "배열의 합을 구하시오 이 문장은 본문입니다." + _nl + "입력 예: 1 2 3")
check("앞의 구역 표시(<기본문제>)도 지우고 본문·입출력 예는 그대로 둔다", _t5.startswith("배열의 합을") and "입력 예: 1 2 3" in _t5 and _a5 is None, _t5)
print("유형 힌트: 물음에 답하는 개념 문제는 코딩이 아니다")
_nl = chr(10)
_q1 = "상속에 대한 다음 물음에 답하시오." + _nl + "a) 상속의 주체는 자식인가 부모인가?" + _nl + "b) 다중 상속이 가능한가?" + _nl + "e) 부모의 메소드를 호출할 때 사용하는 키워드는?"
check("짧은 값으로 답하는 물음 문제는 단답형", pdf_intake.hint(_q1, False, False) == "단답형", pdf_intake.hint(_q1, False, False))
_q2 = "다음 물음에 답하시오." + _nl + "a) 이 코드의 실행 결과에 대하여 설명하시오." + _nl + "b) 그 이유를 서술하시오." + _nl + "c) 두 방식의 차이는 무엇인가?"
check("소문항이 둘 이상이면 설명을 묻는 소문항이어도 소문항별 정답(단답형)", pdf_intake.hint(_q2, False, False) == "단답형", pdf_intake.hint(_q2, False, False))
_q4 = "다음 물음에 답하시오. 캡슐화의 의미와 장점을 서술하고 그 이유를 설명하시오."
check("소문항 없이 서술 하나를 묻는 문제는 주관식", pdf_intake.hint(_q4, False, False) == "주관식", pdf_intake.hint(_q4, False, False))
_q3 = "다음 질문에 답하세요" + _nl + "1) Book 클래스의 생성자를 구현하세요." + _nl + "2) 복사 생성자를 추가하여 구현 하세요."
check("코드를 작성·구현하라는 문제는 개념 문제로 보지 않는다 (기존 판정 유지)", pdf_intake.hint(_q3, False, True) == "디버깅" and pdf_intake.hint("두 수의 합을 출력하는 프로그램을 작성하시오.", False, False) == "코딩")
print("한 문제 안의 코드 작성·수정 소문항 나누기")
_nl = chr(10)
_b = "Book 클래스에 대하여 질문에 답하세요" + _nl + "class Book {" + _nl + "  int price;" + _nl + "};" + _nl + _nl + "1) Book 클래스의 생성자를 구현 하세요." + _nl + _nl + "2) 복사 생성자 코드를 작성하세요." + _nl + _nl + "3) 아래 main() 실행 시 오류가 발생합니다. 오류가 발생하지 않도록 수정하세요." + _nl + "int main() {" + _nl + "  Book a(1);" + _nl + "}"
_sp = pdf_intake.split_subtasks(_b)
check("코드를 작성·수정하라는 소문항이 3개이면 문제 3개로 나눈다 (-1, -2, -3)", [s for s, _ in _sp] == ["-1", "-2", "-3"], [s for s, _ in _sp])
check("각 조각에 공통 머리말(설명·제공 코드)과 자기 소문항만 들어간다", all("class Book {" in t for _, t in _sp) and "복사 생성자" in _sp[1][1] and "복사 생성자" not in _sp[0][1] and "int main()" in _sp[2][1] and "int main()" not in _sp[0][1], _sp[1][1])
check("개념 물음(코드 작성 소문항이 둘 미만)은 나누지 않는다", pdf_intake.split_subtasks("다음 물음에 답하시오." + _nl + "a) 상속의 주체는?" + _nl + "b) 키워드는?" + _nl + "c) 오류를 수정하시오.") == [("", "다음 물음에 답하시오." + _nl + "a) 상속의 주체는?" + _nl + "b) 키워드는?" + _nl + "c) 오류를 수정하시오.")])
check("소문항 번호가 1, 2, 3 으로 이어지지 않으면 소문항으로 보지 않는다", pdf_intake.split_subtasks("설명" + _nl + "1) 구현하세요." + _nl + "3) 작성하세요.") == [("", "설명" + _nl + "1) 구현하세요." + _nl + "3) 작성하세요.")])
check("a) b) 소문항도 같은 방식으로 나눈다", [s for s, _ in pdf_intake.split_subtasks("a) 함수를 구현하세요." + _nl + "b) 코드를 수정하세요.")] == ["-1", "-2"])
with _tf.TemporaryDirectory() as _d2:
    _p2 = os.path.join(_d2, "자바_문제.txt")
    open(_p2, "w", encoding="utf-8").write("자바 실습" + _nl + _nl + "문제 SB11-0001" + _nl + "Book 클래스를 다룬다." + _nl + "class Book {" + _nl + "  int price;" + _nl + "};" + _nl + "1) 생성자를 구현하세요." + _nl + "2) 복사 생성자를 작성하세요." + _nl + _nl + "문제 SB11-0002" + _nl + "두 수의 합을 출력하는 프로그램을 작성하시오. 충분히 긴 문장입니다.")
    _k, _recs = parsing.build_records(None, [_p2], labels=["자바_문제.txt"])
    check("업로드: 코드 소문항 2개인 문제는 레코드 2개(SB11-0001-1, -2)로, 나머지 문제는 그대로", [r["key"] for r in _recs] == ["SB11-0001-1", "SB11-0001-2", "SB11-0002"], [r["key"] for r in _recs])
    check("나눈 레코드에는 나눴다는 메모가 있고 공통 머리말이 있다", any("소문항 2개를 문제 2개로 나눔" in m for m in _recs[0]["intake"]["메모"]) and "class Book {" in _recs[1]["원본조각"] and "복사 생성자" in _recs[1]["원본조각"] and "복사 생성자" not in _recs[0]["원본조각"], _recs[1]["원본조각"])
print("PDF 글머리 기호 글자(l, o)")
_nl = chr(10)
_t, _a = pdf_intake.clean_section("l 멤버 변수를 선언하시오." + _nl + "o 메소드를 작성하시오 충분히 긴 문장입니다." + _nl + "lamp 는 그대로 둔다 영어 단어")
check("줄 앞의 글머리 기호 글자 l, o 만 떼고 영어 단어는 그대로 둔다", _t.startswith("멤버 변수를 선언하시오.") and "\n메소드를 작성하시오" in _t and "lamp 는 그대로" in _t, _t)
print("서버가 풀이 방식별로 문제를 나눈다 (모두 작성이든 택1이든)")
_nl = chr(10)
with _tf.TemporaryDirectory() as _d3:
    _p3 = os.path.join(_d3, "파이썬_문제.txt")
    open(_p3, "w", encoding="utf-8").write("파이썬" + _nl + _nl + "문제 PY41-0001" + _nl + "문자열의 단어 순서를 뒤집어 출력하는 프로그램을 작성하시오." + _nl + "아래 방법 모두 작성하시오." + _nl + "방법1) for 반복문 이용하시오" + _nl + "방법2) LC 사용" + _nl + _nl + "문제 PY41-0002" + _nl + "두 수의 합을 출력하는 프로그램을 작성하시오. 충분히 긴 문장입니다.")
    _k3, _r3 = parsing.build_records(None, [_p3], labels=["파이썬_문제.txt"])
    check("방법1, 방법2 가 있는 문제는 '모두 작성'이어도 서버가 문제 2개(PY41-0001-1, -2)로 나눈다", [r["key"] for r in _r3] == ["PY41-0001-1", "PY41-0001-2", "PY41-0002"], [r["key"] for r in _r3])
    check("나눈 레코드는 어느 방식 문제인지 표시와 메모를 가진다", _r3[0]["방식분할"] == "방법1" and _r3[1]["방식분할"] == "방법2" and any("서버가 문제 2개로 나눔" in m for m in _r3[1]["intake"]["메모"]) and "방식분할" not in _r3[2], [(r["key"], r.get("방식분할")) for r in _r3])
print("프로그램을 쓰라는 말이 없는 질문 유형 힌트 / 파일별 대체 읽기")
check("'~이름을 쓰시오' 질문은 코딩이 아니라 단답형", pdf_intake.hint("큐의 삽입 연산 이름을 쓰시오.", False, False) == "단답형")
check("'설명하시오' 서술은 주관식", pdf_intake.hint("재귀 호출이 무엇인지 자신의 말로 설명하시오.", False, False) == "주관식")
check("프로그램·함수를 작성하라면 그대로 코딩", pdf_intake.hint("두 수의 합을 출력하는 프로그램을 작성하시오.", False, False) == "코딩" and pdf_intake.hint("리스트를 뒤집는 함수를 작성하시오", False, False) == "코딩")
_nl = chr(10)
with _tf.TemporaryDirectory() as _d4:
    _a = os.path.join(_d4, "문제지.txt"); _b = os.path.join(_d4, "표.csv")
    open(_a, "w", encoding="utf-8").write("문제 AB11-0001" + _nl + "두 수의 합을 출력하는 프로그램을 작성하시오. 충분히 긴 문장입니다." + _nl)
    open(_b, "w", encoding="utf-8").write("번호,질문,보기,정답" + _nl + "1,HTTP 의 기본 포트 번호는 무엇입니까 정말로,80;443;21;22,80" + _nl + "2,SQL 에서 중복을 제거하는 키워드는 무엇입니까,DISTINCT,DISTINCT" + _nl)
    _k4, _r4 = parsing.build_records(None, [_a, _b], labels=["문제지.txt", "표.csv"])
    check("다른 파일에서 문제가 나와도, 문제를 못 찾은 파일(머리글 없는 표)은 버리지 않고 문서 전체로 넣는다", any(r.get("문서전체") and r["key"] == "표" for r in _r4) and any(r["key"] == "AB11-0001" for r in _r4), [r["key"] for r in _r4])
check("①②③④ 보기가 줄지어 있으면 객관식", pdf_intake.hint("스택의 특징으로 옳은 것은?" + chr(10) + "① FIFO" + chr(10) + "② LIFO" + chr(10) + "③ 양쪽" + chr(10) + "④ 인덱스", False, False) == "객관식")
check("1) 2) 3) 보기 + 고르라는 말이면 객관식", pdf_intake.hint("리스트 길이를 구하는 함수는? 고르시오." + chr(10) + "1) size()" + chr(10) + "2) length()" + chr(10) + "3) len()", False, False) == "객관식")
check("보기 모양이어도 고르라는 말이 없는 순서 목록(1) 2) 3))은 객관식이 아니다", pdf_intake.hint("프로그램을 작성하시오." + chr(10) + "1) 입력을 받는다" + chr(10) + "2) 합을 구한다" + chr(10) + "3) 출력한다", False, False) == "코딩")
check("코드를 주고 출력 결과를 쓰시오 → 단답형", pdf_intake.hint("다음 코드의 출력 결과를 쓰시오." + chr(10) + "s = 1" + chr(10) + "print(s)", False, True) == "단답형")
check("메서드 이름을 쓰시오 → 단답형 (낱말에 메서드가 있어도)", pdf_intake.hint("딕셔너리의 키 목록을 돌려주는 메서드 이름을 쓰시오.", False, False) == "단답형")
check("메서드를 작성하시오 는 그대로 코딩", pdf_intake.hint("키 목록을 돌려주는 메서드 이름을 쓰고 메서드를 작성하시오.", False, False) == "코딩")
check("질문이 ? 로 끝나고 1) 2) 3) 4) 보기가 있으면 객관식 (고르라는 말이 없어도)", pdf_intake.hint("리스트의 길이를 구하는 내장 함수는?" + chr(10) + "1) size()" + chr(10) + "2) length()" + chr(10) + "3) len()" + chr(10) + "4) count()", False, False) == "객관식")

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
