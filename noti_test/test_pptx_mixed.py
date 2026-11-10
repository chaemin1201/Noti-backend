"""① 파워포인트(.pptx) 읽기·나누기·그림  ② 여러 형식의 문제지를 한 번에 올리는 경우(엑셀 + 엑셀과 상관없는 워드·한글·PDF·PPT)
noti_test 폴더에서:  python test_pptx_mixed.py        (python-docx, openpyxl, Pillow 필요)"""
import io, os, sys, tempfile, zipfile
import _bootstrap
_bootstrap.setup()
try:
    from PIL import Image
    import docx, openpyxl
except ImportError as e:
    print(f"⏭ 건너뜀: {e.name} 가 필요합니다"); sys.exit(2)
from app.inputdata.intake import parsing
from app.inputdata.intake.readers import pdf_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def png(color=(200, 30, 30)):
    b = io.BytesIO(); Image.new("RGB", (60, 30), color).save(b, "PNG"); return b.getvalue()

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
def sp(*paras, ph=None):
    body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paras)
    return f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="x"/><p:cNvSpPr/><p:nvPr>{f"<p:ph type=\'{ph}\'/>" if ph else ""}</p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/>{body}</p:txBody></p:sp>'
def pic(rid): return f'<p:pic><p:nvPicPr><p:cNvPr id="2" name="p"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/></p:blipFill><p:spPr/></p:pic>'
def slide(*shapes): return f'<p:sld {NS}><p:cSld><p:spTree>{"".join(shapes)}</p:spTree></p:cSld></p:sld>'
def rel(*items):
    return '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(f'<Relationship Id="{i}" Type="http://x/{t}" Target="{g}"/>' for i, t, g in items) + "</Relationships>"

def make_pptx(path, slides, notes=None, images=None):
    with zipfile.ZipFile(path, "w") as z:
        ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i}"/>' for i in range(1, len(slides) + 1))
        z.writestr("ppt/presentation.xml", f'<p:presentation {NS}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", rel(*[(f"rId{i}", "slide", f"slides/slide{i}.xml") for i in range(1, len(slides) + 1)]))
        for i, s in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", s)
            r = [("rId1", "image", "../media/image1.png")]
            if notes and i in notes: r.append(("rId2", "notesSlide", f"../notesSlides/notesSlide{i}.xml")); z.writestr(f"ppt/notesSlides/notesSlide{i}.xml", f'<p:notes {NS}><p:cSld><p:spTree>{sp("1", ph="sldNum")}{sp(notes[i], ph="body")}</p:spTree></p:cSld></p:notes>')
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rel(*r))
        z.writestr("ppt/media/image1.png", images or png())

print("1. 파워포인트 읽기")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "자바_슬라이드.pptx")
    make_pptx(p, [slide(sp("자바 기초 실습", "표지")),
                  slide(sp("실습 1. 두 수의 합을 출력하시오.", "입력: 3 4"), pic("rId1")),
                  slide(sp("실습 2. 짝수인지 판단하시오."))],
              notes={2: "정답은 7"})
    imgs = []; txt = pdf_intake.read_text(p, imgs)
    check("슬라이드마다 쪽 구분이 들어가고 글이 순서대로 읽힌다", txt.count("\f") == 2 and "두 수의 합" in txt and txt.index("두 수의 합") < txt.index("짝수인지"), repr(txt[:120]))
    check("그림은 [이미지] 와 함께 같은 순서로 꺼낸다", txt.count("[이미지]") == 1 and len(imgs) == 1 and imgs[0][:4] == b"\x89PNG")
    check("발표자 노트의 본문만 [발표자 노트] 로 붙는다 (슬라이드 번호 칸 제외)", "[발표자 노트] 정답은 7" in txt and "[발표자 노트] 1" not in txt, txt)
    secs = list(pdf_intake.sections_with_images(p, label="자바_슬라이드.pptx"))
    check("'실습 N.' 제목으로 문제가 나뉘고 그림이 해당 문제에 붙는다", [s[0] for s in secs] == ["자바_슬라이드_01", "자바_슬라이드_02"] and [len(s[3]) for s in secs] == [1, 0], [(s[0], len(s[3])) for s in secs])
    check("형식 이름은 파워포인트", pdf_intake.format_of(p) == "파워포인트")
    q = os.path.join(d, "평문.pptx"); make_pptx(q, [slide(sp("표지")), slide(sp("다음 코드의 출력 결과를 쓰시오.", "print(1+2)")), slide(sp("변수의 뜻을 설명하시오. 자세히 쓰시오"))])
    secs = list(pdf_intake.sections_with_images(q, label="평문.pptx"))
    check("번호 제목이 없으면 글이 있는 슬라이드 하나를 문제 하나로 본다 (짧은 표지는 제외)", [s[0] for s in secs] == ["평문_02", "평문_03"], [s[0] for s in secs])
    r = os.path.join(d, "old.ppt"); open(r, "wb").write(b"\xd0\xcf\x11\xe0")
    try: pdf_intake.read_text(r); ok = False
    except SystemExit as e: ok = ".pptx" in str(e)
    check("구형 .ppt 는 .pptx 로 저장해 올리라고 안내한다", ok)

print("2. 여러 형식의 문제지를 한 번에 (엑셀 + 짝이 없는 워드·PPT)")
with tempfile.TemporaryDirectory() as d:
    xl = os.path.join(d, "f0.xlsx"); wb = openpyxl.Workbook(); ws = wb.active; ws.append(["이름", "유형", "설명", "정답코드", "출력"])
    ws.append(["문제 EX_01 합", "코딩", "두 수를 더하시오", "print(1+2)", "3"]); wb.save(xl)
    wd = os.path.join(d, "f1.docx"); doc = docx.Document(); doc.add_paragraph("실습 1. 워드 문제 하나."); doc.add_paragraph("실습 2. 워드 문제 둘."); doc.save(wd)
    pp = os.path.join(d, "f2.pptx"); make_pptx(pp, [slide(sp("실습 1. 슬라이드 문제 하나입니다."), pic("rId1")), slide(sp("실습 2. 슬라이드 문제 둘입니다."))])
    kind, recs = parsing.build_records(xl, [wd, pp], labels=["워드_문제.docx", "슬라이드_문제.pptx"])
    by = {r["key"]: r for r in recs}
    check("종류는 '혼합', 엑셀 1 + 워드 2 + PPT 2 = 5문제", kind == "혼합" and len(recs) == 5, (kind, [r["key"] for r in recs]))
    ex = by["EX_01 합"]
    check("엑셀 행은 원본과 대조하지 않고 엑셀 단독으로 남는다 (짝이 없는 원본을 '못 찾음'으로 오판하지 않음)", ex["입력종류"] == "엑셀" and "대조" not in ex and "원본조각" not in ex, ex["입력종류"])
    check("워드·PPT 문제는 원본 입력으로 따로 만들어진다", sorted(r["원본형식"] for r in recs if r["입력종류"] == "원본") == ["워드", "워드", "파워포인트", "파워포인트"])
    check("PPT 의 그림은 해당 문제에 붙는다", len(by["슬라이드_01"].get("이미지") or []) == 1 and not by["슬라이드_02"].get("이미지"))
    # 엑셀과 같은 ID 의 원본이 있으면 지금처럼 대조한다
    wd2 = os.path.join(d, "f3.docx"); doc = docx.Document(); doc.add_paragraph("문제 PY11-0001 두 수의 합"); doc.add_paragraph("두 수를 더하시오"); doc.save(wd2)
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(["이름", "유형", "설명", "정답코드", "출력"]); ws.append(["문제 PY11-0001", "코딩", "두 수를 더하시오", "print(1+2)", "3"]); xl2 = os.path.join(d, "f4.xlsx"); wb.save(xl2)
    kind, recs = parsing.build_records(xl2, [wd2], labels=["문제.docx"])
    check("엑셀과 문제 ID 가 같은 원본은 이전처럼 '둘 다'로 대조한다", kind == "둘 다" and recs[0]["입력종류"] == "둘 다" and "대조" in recs[0], (kind, recs[0]["입력종류"]))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
