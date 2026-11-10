"""텍스트(.txt, 인코딩과 제목 모양)와 DB(SQLite) 파일 읽기 시험.
noti_test 폴더에서:  python test_formats_new.py"""
import hashlib, json, os, sqlite3, sys, tempfile
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import parsing
from app.inputdata.intake.readers import pdf_intake
from app.inputdata.intake.readers import images as safety
from app.inputdata.intake.checks.fix import fix_title as fidelity_fix_title
from app.inputdata.intake.readers import xlsx_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

NL = chr(10)
TXT = NL.join(["자바 실습", "", "문제 1: 두 수의 합을 출력하시오.", "입력: 3 4", "출력: 7", "", "문제 2: 짝수인지 판단하시오.", "입력: 4", "출력: 짝수"])

with tempfile.TemporaryDirectory() as d:
    print("1. 텍스트 파일 인코딩")
    for enc, label in (("utf-8-sig", "UTF-8(BOM)"), ("utf-8", "UTF-8"), ("cp949", "CP949(한국어 윈도우 메모장)"), ("utf-16", "UTF-16")):
        p = os.path.join(d, f"t_{label[:5]}.txt"); open(p, "wb").write(TXT.encode(enc))
        check(f"{label} 로 저장된 .txt 를 읽는다", pdf_intake.read_text(p) == TXT or pdf_intake.read_text(p).lstrip("﻿") == TXT, pdf_intake.read_text(p)[:30])
    p = os.path.join(d, "bad.txt"); open(p, "wb").write(b"\xff\xfe\x00 \x81\x41 abc")
    check("어떤 인코딩도 아니면 깨진 글자는 바꿔서라도 읽는다 (오류로 올리지 못하게 하지 않음)", isinstance(pdf_intake.read_text(p), str))
    big = os.path.join(d, "big.txt"); open(big, "wb").write(b"a" * (51 * 1024 * 1024))
    try: safety.read_text_file(big); ok = False
    except safety.UnsafeFile: ok = True
    check("50MB 를 넘는 텍스트는 거절한다", ok)

    print("2. 텍스트의 문제 제목 모양")
    for name, body in (("문제 1:", "문제 1: 가" + NL + "내용" + NL + "문제 2: 나" + NL + "내용"), ("[문제 1]", "[문제 1] 가" + NL + "내용" + NL + "[문제 2] 나" + NL + "내용"),
                       ("Q1.", "Q1. 가" + NL + "내용" + NL + "Q2. 나" + NL + "내용"), ("문제 1번.", "문제 1번. 가" + NL + "내용" + NL + "문제 2번. 나" + NL + "내용"),
                       ("문제 1)", "문제 1) 가" + NL + "내용" + NL + "문제 2) 나" + NL + "내용"), ("실습 1.", "실습 1. 가" + NL + "내용" + NL + "실습 2. 나" + NL + "내용")):
        check(f"'{name}' 모양의 제목으로 문제 2개를 나눈다", [m[0] for m in pdf_intake.heading_marks(body, "S")] == ["S_01", "S_02"], pdf_intake.heading_marks(body, "S"))
    check("'문제를 풀어 보세요' 같은 일반 문장은 제목으로 보지 않는다", pdf_intake.heading_marks("문제를 풀어 보세요" + NL + "문제점은 없다" + NL + "문제 해결", "S") == [])
    p = os.path.join(d, "자바_문제.txt"); open(p, "wb").write(TXT.encode("cp949"))
    kind, recs = parsing.build_records(None, [p], labels=["자바_문제.txt"])
    check("CP949 텍스트 파일을 올려도 문제 2개로 나뉘어 처리된다", kind == "원본" and len(recs) == 2 and recs[0]["원본형식"] == "텍스트" and "두 수의 합" in recs[0]["원본조각"], (kind, len(recs)))

    print("3. CSV 인코딩")
    cp = os.path.join(d, "문제.csv")
    open(cp, "wb").write(("이름,설명,정답코드" + NL + "문제 A_01 합,두 수를 더하시오,print(1)" + NL).encode("cp949"))
    rows = xlsx_intake.read(cp)
    check("CP949 로 저장된 CSV 도 읽는다 (한국어 윈도우 엑셀의 'CSV' 저장 기본)", len(rows) == 1 and rows[0]["fields"]["설명"] == "두 수를 더하시오", rows)

    print("4. DB(SQLite)")
    db = os.path.join(d, "problems.db")
    cx = sqlite3.connect(db)
    cx.execute("create table problem (id integer primary key, title text, description text, difficulty text, problem_type text, reference_code text, options text, secret blob, extra_col text)")
    cx.execute("insert into problem values (1, 'DB01_01 합', '두 수를 더하시오', 'easy', '코딩', 'print(1+2)', null, x'00', 'x')")
    cx.execute("insert into problem values (2, 'DB01_02 보기', '옳은 것은?', 'medium', '객관식', null, ?, null, 'y')", (json.dumps(["가", "나", "다"], ensure_ascii=False),))
    cx.execute("insert into problem values (3, '', '', null, null, null, null, null, null)")                 # 빈 행
    cx.execute("create table log (id integer, message text)"); cx.execute("insert into log values (1, '로그')")      # 문제 표가 아님
    cx.execute("create view v as select title as 이름, description as 설명 from problem where id = 1")
    cx.commit(); cx.close()
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    rows = xlsx_intake.read(db)
    names = [r["fields"]["이름"] for r in rows]
    check("영어 열 이름(title, description …)의 표를 문제 표로 읽는다 (문제 표가 아닌 log 는 건너뜀, 빈 행은 건너뜀)", "DB01_01 합" in names and "DB01_02 보기" in names and all("로그" not in str(r["fields"]) for r in rows), names)
    r1 = next(r for r in rows if r["fields"]["이름"] == "DB01_01 합")
    check("열 이름이 항목으로 옮겨진다 (difficulty→난이도, problem_type→유형, reference_code→정답코드)", r1["fields"].get("난이도") == "easy" and r1["fields"].get("유형") == "코딩" and r1["fields"].get("정답코드") == "print(1+2)", r1["fields"])
    r2 = next(r for r in rows if r["fields"]["이름"] == "DB01_02 보기")
    check("JSON 목록으로 저장된 보기는 줄로 풀린다", r2["fields"].get("보기") == "가" + NL + "나" + NL + "다", r2["fields"])
    check("모르는 열(extra_col)은 버리지 않고 메모로 알린다, 바이트 열은 값으로 쓰지 않는다", any("extra_col" in m for m in r1["intake"]["메모"]) and "secret" not in str(r1["fields"]))
    check("읽기 전용: 읽은 뒤 DB 파일이 바뀌지 않았다", hashlib.sha256(open(db, "rb").read()).hexdigest() == before)
    check("표형식 이름은 DB", pdf_intake.format_of(db) == "DB" and pdf_intake.format_of("a.sqlite3") == "DB")
    check("확장자 .db/.sqlite/.sqlite3 는 표 파일로 분류된다 (PPT 는 원본)", all(parsing.kind_of(n) == "table" for n in ("a.db", "a.sqlite", "a.SQLITE3")) and parsing.kind_of("a.pptx") == "original")
    kind, recs = parsing.build_records(db, [], labels=[], table_labels=["problems.db"])
    check("뷰(view)는 읽지 않아 같은 문제가 중복되지 않는다", len([r for r in xlsx_intake.read(db) if r["fields"]["이름"] == "DB01_01 합"]) == 1)
    check("DB 가 업로드 처리에서 문제 레코드(입력종류 엑셀, 표형식 DB)가 된다", kind == "엑셀" and len(recs) == 2 and recs[0]["표형식"] == "DB", (kind, len(recs)))

    fake = os.path.join(d, "fake.db"); open(fake, "wb").write(b"this is not sqlite at all")
    try: xlsx_intake.read(fake); msg = ""
    except SystemExit as e: msg = str(e)
    check("SQLite 가 아닌 .db 는 알아듣게 거절한다", "SQLite" in msg, msg)
    e = None
    try: parsing.build_records(fake, [], labels=[])
    except parsing.IntakeInputError as x: e = x
    check("업로드 처리에서는 사용자에게 보이는 안내가 된다", e is not None and "SQLite" in str(e), e)
    nt = os.path.join(d, "notable.db"); c2 = sqlite3.connect(nt); c2.execute("create table t (a text)"); c2.commit(); c2.close()
    try: xlsx_intake.read(nt); msg = ""
    except SystemExit as e2: msg = str(e2)
    check("문제 표가 없으면 있는 표와 열을 알려 준다", "title" in msg or "열" in msg and "t(a)" in msg, msg)
    cb = os.path.join(d, "cell.db"); c3 = sqlite3.connect(cb); c3.execute("create table p (title text, description text)")
    c3.execute("insert into p values ('큰 칸', ?)", ("가" * 300_000,)); c3.commit(); c3.close()
    check("칸 하나가 너무 크면 20만 글자로 자른다", len(xlsx_intake.read(cb)[0]["fields"]["설명"]) == 200_000)
    c4 = sqlite3.connect(os.path.join(d, "many.db")); c4.execute("create table p (title text, description text)")
    c4.executemany("insert into p values (?, ?)", [(f"n{i}", "설명") for i in range(1500)]); c4.commit(); c4.close()
    check("표 하나에서 읽는 행은 1000개까지", len(xlsx_intake.read(os.path.join(d, "many.db"))) == 1000)
    print("5. 학습지 DB (문제 표 + 줄 표 + 그림 표) 와 '영문 접두 번호 제목' 텍스트")
    ws = os.path.join(d, "ws.db"); cw = sqlite3.connect(ws)
    cw.execute("create table documents (id integer primary key, week text, file_name text, title text)")
    cw.execute("create table problems (id integer primary key, document_id integer, problem_no integer, section text, statement text)")
    cw.execute("create table problem_lines (id integer primary key, problem_id integer, kind text, line_no integer, content text)")
    cw.execute("create table problem_images (id integer primary key, problem_id integer, seq integer, mime text, width integer, height integer, data blob)")
    cw.execute("insert into documents values (1, '08', 'f', 'C++ 08 복사&이동생성자')")
    cw.execute("insert into problems values (1, 1, 1, '개념 확인', '복사 생성자를 구현하세요')")
    cw.execute("insert into problems values (2, 1, 2, '응용', '이동 생성자를 구현하세요')")
    for i, (k, c) in enumerate([("given_code", "class A {};"), ("solution_code", "int main() {}"), ("solution_code", "// 끝"), ("result", "OK"), ("requirement", "깊은 복사")], 1):
        cw.execute("insert into problem_lines values (?, 1, ?, ?, ?)", (i, k, i, c))
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
    cw.execute("insert into problem_images values (1, 1, 1, 'image/png', 1, 1, ?)", (png,)); cw.commit(); cw.close()
    rows = xlsx_intake.read(ws)
    check("학습지 DB 의 문제 하나가 행 하나가 된다 (이름은 문서 제목 앞부분 + 번호)", [r["fields"]["이름"] for r in rows] == ["C++_08_01", "C++_08_02"], [r["fields"]["이름"] for r in rows])
    f1 = rows[0]["fields"]
    check("줄은 종류별로 칸에 모인다 (조건·제공코드·정답코드·출력)", f1.get("조건") == "깊은 복사" and f1.get("제공코드") == "class A {};" and f1.get("정답코드") == "int main() {}" + NL + "// 끝" and f1.get("출력") == "OK", f1)
    kind, recs = parsing.build_records(ws, [], labels=[], table_labels=["ws.db"])
    check("DB 에 담긴 그림은 AI 에 붙는다 (그림 없는 문제는 없음)", len(recs[0].get("이미지") or []) == 1 and not recs[1].get("이미지"), [len(r.get("이미지") or []) for r in recs])
    tt = os.path.join(d, "c08.txt"); open(tt, "wb").write(("C++ 08 복사&이동생성자" + NL + "학번 :  이름 :" + NL + NL + "(1) 첫 문제를 푸세요" + NL + "내용" + NL + NL + "(2) 둘째 문제를 푸세요" + NL + "내용").encode("utf-8"))
    kind, recs = parsing.build_records(None, [tt], labels=["c08.txt"])
    check("'C++ 08 제목' 처럼 띄어 쓴 문서 제목도 (n) 항목을 C++_08_01 … 로 나눈다", [r["key"] for r in recs] == ["C++_08_01", "C++_08_02"], [r["key"] for r in recs])
    t8 = NL.join(["실습 1. 가", "내용", "실습 2. 나", "내용", "실습 . 번호 빠진 제목", "내용", "실습 4. 라", "내용"])
    check("자동 번호가 빠져 \"실습 . 문장\" 이 된 제목도 앞 번호 다음 번호로 나눈다", [m[0] for m in pdf_intake.heading_marks(t8, "S")] == ["S_01", "S_02", "S_03", "S_04"], pdf_intake.heading_marks(t8, "S"))
    check("앞 번호가 없는 번호 빠진 제목은 제목으로 보지 않는다", pdf_intake.heading_marks("실습 . 첫" + NL + "내용" + NL + "실습 . 둘", "S") == [])
    print("6. 문제지 언어 추정")
    jt = os.path.join(d, "자바.txt"); open(jt, "wb").write(NL.join(["자바 실습", "", "문제 1: 합", "public static void main(String[] a) { System.out.println(1); }", "문제 2: 곱", "Scanner sc = new Scanner(System.in); System.out.println(2);"]).encode("utf-8"))
    kind, recs = parsing.build_records(None, [jt], labels=["자바.txt"])
    check("문제지 전체 글로 언어를 추정해 모든 문제에 intake.언어힌트로 붙인다", [r["intake"].get("언어힌트") for r in recs] == ["java", "java"], [r["intake"].get("언어힌트") for r in recs])
    check("단서가 없거나 여러 언어가 비슷하면 힌트를 만들지 않는다", pdf_intake.language_hint("그냥 글") is None and pdf_intake.language_hint("System.out.println(1); System.out.println(2); cout << 1; cout << 2;") is None)
    t1 = os.path.join(d, "c08_one.txt"); open(t1, "wb").write(("C++ 08 복사&이동생성자" + NL + "학번 :  이름 :" + NL + NL + "(1) 복사 생성자를 구현하세요" + NL + "내용" + NL + NL + "(3) 다른 문제" + NL + "내용").encode("utf-8"))
    kind, recs = parsing.build_records(ws, [t1], labels=["c08_one.txt"], table_labels=["ws.db"])
    by = {r["key"]: r["입력종류"] for r in recs}
    check("표의 문제 중 짝이 되는 문서 조각이 있는 것만 '둘 다', 나머지는 표 단독 입력이고 짝 없는 문서 문제는 따로 처리한다", by.get("C++_08_01") == "둘 다" and by.get("C++_08_02") == "엑셀" and by.get("C++_08_03") == "원본", by)
    print("7. 파일 이름으로 언어 추정")
    nm = os.path.join(d, "자바프로그래밍_풀이.txt"); open(nm, "wb").write(NL.join(["자바프로그래밍 풀이", "", "문제 1: 합", "정답은 55 입니다.", "문제 2: 곱", "정답은 6 입니다."]).encode("utf-8"))
    kind, recs = parsing.build_records(None, [nm], labels=["자바프로그래밍_풀이.txt"])
    check("글에 코드 단서가 없어도 파일 이름에 자바가 있으면 언어 힌트는 java", [r["intake"].get("언어힌트") for r in recs] == ["java", "java"], [r["intake"].get("언어힌트") for r in recs])
    nn = os.path.join(d, "문제.txt"); open(nn, "wb").write(NL.join(["풀이", "", "문제 1: 합", "정답은 55 입니다.", "문제 2: 곱", "정답은 6 입니다."]).encode("utf-8"))
    kind, recs = parsing.build_records(None, [nn], labels=["문제.txt"])
    check("글에도 이름에도 단서가 없으면 힌트를 만들지 않는다", [r["intake"].get("언어힌트") for r in recs] == [None, None], [r["intake"].get("언어힌트") for r in recs])
    print("8. 문제 경계를 못 찾은 문서 (INTAKE_WHOLE_DOC)")
    nb = os.path.join(d, "번호없음.txt"); open(nb, "wb").write((NL.join(["문자열을 뒤집는 프로그램을 작성하시오. 입력은 한 줄이다.", "다음으로 정수 두 개를 더해 출력하는 프로그램을 작성하시오."]) * 2).encode("utf-8"))
    os.environ.pop("INTAKE_WHOLE_DOC", None)
    try: parsing.build_records(None, [nb], labels=["번호없음.txt"]); ok = False
    except parsing.IntakeInputError: ok = True
    check("기본(끔)은 문제를 못 찾은 문서를 안내와 함께 거절한다", ok)
    os.environ["INTAKE_WHOLE_DOC"] = "on"
    try:
        kind, recs = parsing.build_records(None, [nb], labels=["번호없음.txt"])
        check("INTAKE_WHOLE_DOC=on 이면 문서 전체를 레코드 하나로 만든다 (문서전체 표시와 확인 메모 포함)", len(recs) == 1 and recs[0].get("문서전체") and recs[0]["key"] == "번호없음" and any("경계" in m for m in recs[0]["intake"]["메모"]), recs and recs[0].get("key"))
        check("문서 전체 레코드의 사용자 글에는 문제 단위로 나누라는 안내가 들어가고, 제목은 서버가 되돌리지 않는다", "[문서 전체]" in parsing.user_text(recs[0]) and "번호없음_01" in parsing.user_text(recs[0]) and fidelity_fix_title(recs[0], {"title": "번호없음_01"}) is None)
        tiny = os.path.join(d, "짧음.txt"); open(tiny, "wb").write("짧은 글".encode("utf-8"))
        try: parsing.build_records(None, [tiny], labels=["짧음.txt"]); ok = False
        except parsing.IntakeInputError: ok = True
        check("글이 너무 짧으면(문제가 아닌 문서) 켜 두어도 거절한다", ok)
    finally:
        os.environ.pop("INTAKE_WHOLE_DOC", None)
print("머리글 없는 자유 형식 엑셀·CSV")
import glob, openpyxl
with tempfile.TemporaryDirectory() as d:
    wb = openpyxl.Workbook(); ws = wb.active
    for r in (["문제 1: 두 수의 합을 출력하시오.", "입력 3 4", "출력 7"], ["문제 2: 짝수인지 판단하시오.", "입력 4", "출력 짝수"]): ws.append(r)
    px = os.path.join(d, "free.xlsx"); wb.save(px)
    kind, recs = parsing.build_records(px, [], labels=[], table_labels=["자유.xlsx"])
    check("머리글이 없는 엑셀도 오류 없이 글 원본으로 읽는다 (문제 2개)", kind == "원본" and len(recs) == 2, (kind, len(recs)))
    wb = openpyxl.Workbook(); ws = wb.active
    for r in (["자료 정리"], ["앞으로 할 일", "내용 없음"], ["문제가 되는 부분을 찾아 설명한다. " * 4]): ws.append(r)
    px2 = os.path.join(d, "free2.xlsx"); wb.save(px2)
    kind, recs = parsing.build_records(px2, [], labels=[], table_labels=["자유2.xlsx"])
    check("문제 표시가 없으면 문서 전체 한 건으로 만든다", len(recs) == 1 and recs[0].get("문서전체") is True, (kind, recs[:1]))
    pc = os.path.join(d, "free.csv"); open(pc, "w", encoding="utf-8-sig").write(NL.join(["문제 1: 합", "입력 3 4", "출력 7", "", "문제 2: 차", "입력 4 3", "출력 1", ""]))
    kind, recs = parsing.build_records(pc, [], labels=[], table_labels=["자유.csv"])
    check("머리글 없는 CSV 도 같은 방식으로 읽는다", kind == "원본" and len(recs) == 2, (kind, len(recs)))
    txt = xlsx_intake.sheet_text(px)
    check("sheet_text 는 행마다 한 줄, 칸은 공백 3개로 잇는다", txt.split(NL)[0] == "문제 1: 두 수의 합을 출력하시오.   입력 3 4   출력 7", txt)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["이름", "설명", "정답코드", "출력"]); ws.append(["A_01", "합", "print(1)", "1"]); px3 = os.path.join(d, "ok.xlsx"); wb.save(px3)
    kind, recs = parsing.build_records(px3, [], labels=[], table_labels=["정상.xlsx"])
    check("머리글이 있는 엑셀은 그대로 엑셀 입력", kind == "엑셀" and len(recs) == 1, kind)
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "noti_free_*")))
    parsing.build_records(px, [], labels=[], table_labels=["자유.xlsx"])
    check("임시 글 파일은 처리 뒤 지운다", set(glob.glob(os.path.join(tempfile.gettempdir(), "noti_free_*"))) <= before)


print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
