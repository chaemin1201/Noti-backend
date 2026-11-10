"""스캔 PDF(글 층 없음)와 구형 .ppt 읽기 시험.
noti_test 폴더에서:  python test_scan_ppt.py        (Pillow, olefile 필요. 스캔 판정은 poppler pdftotext 가 있을 때만)"""
import io, os, struct, sys, tempfile
import _bootstrap
_bootstrap.setup()
from PIL import Image
from app.inputdata.intake import parsing, service, config
from app.inputdata.intake.readers import pdf_intake, ppt_legacy

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
def rec(ver, inst, typ, payload=b""):
    return struct.pack("<HHI", ver | (inst << 4), typ, len(payload)) + payload
def container(typ, *kids, inst=0):
    return rec(0xF, inst, typ, b"".join(kids))
def chars(s): return rec(0, 0, 4000, s.encode("utf-16-le"))
def bytes_text(s): return rec(0, 0, 4008, s.encode("cp1252"))
def fopt(pib): return rec(3, 1, 0xF00B, struct.pack("<HI", 260 | 0x4000, pib))
def fbse(off): return rec(2, 6, 0xF007, b"\x06\x06" + b"\x00" * 16 + b"\x00\x00" + struct.pack("<I", 0) + struct.pack("<I", 1) + struct.pack("<I", off) + b"\x00" * 8)
def jpeg_blip(data): return rec(0, 0x46A, 0xF01D, b"\x00" * 16 + b"\xff" + data)

def jpg(color, size=(40, 40)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "JPEG"); return b.getvalue()

print("1. 구형 .ppt 기록 읽기 (합성 스트림)")
J1, J2 = jpg((255, 0, 0)), jpg((0, 0, 255))
pictures = jpeg_blip(J1) + jpeg_blip(J2)
off2 = len(jpeg_blip(J1))
slwt = container(4080, rec(0, 0, 1011, b"\x00" * 20), rec(0, 0, 3999, struct.pack("<I", 0)), chars("문제 1: 두 수의 합"), rec(0, 0, 1011, b"\x00" * 20), bytes_text("Problem 2 title"), inst=0)
doc = container(1000, container(1035, container(0xF000, container(0xF001, fbse(0), fbse(off2)))), slwt)
slide1 = container(1006, container(1036, container(0xF004, fopt(1)), container(0xF004, container(0xF00D, chars("입력: 3 4" + chr(11) + "출력: 7")))))
slide2 = container(1006, container(1036, container(0xF004, fopt(2)), container(0xF004, container(0xF00D, chars("Problem 2 title")))))
stream = doc + slide1 + slide2
imgs = []
txt = ppt_legacy.parse(stream, pictures, imgs)
slides = txt.split(chr(12))
check("슬라이드가 쪽 구분으로 나뉜다 (2장)", len(slides) == 2, txt)
check("제목·본문 자리 글(SlideListWithText)이 슬라이드마다 먼저 들어간다", "문제 1: 두 수의 합" in slides[0] and "Problem 2 title" in slides[1], slides)
check("글상자 글이 들어가고 세로탭(줄바꿈)이 줄바꿈이 된다", "입력: 3 4" + NL + "출력: 7" in slides[0], slides[0])
check("같은 글이 두 곳에 있으면 한 번만 쓴다", slides[1].count("Problem 2 title") == 1, slides[1])
check("그림 자리는 [이미지] 이고 그림 파일이 같은 순서로 채워진다", txt.count("[이미지]") == 2 and imgs == [J1, J2], (txt, [len(x or b'') for x in imgs]))
imgs2 = []
ppt_legacy.parse(stream, None, imgs2)
check("Pictures 스트림이 없으면 그림은 None (본문의 [이미지] 표시는 남는다)", imgs2 == [None, None])
check("깨진 스트림이어도 죽지 않는다", isinstance(ppt_legacy.parse(b"\x0f\x00\xec\x03\xff\xff\xff\x7f"), str) and ppt_legacy.parse(b"") == "")
with tempfile.TemporaryDirectory() as d:
    bad = os.path.join(d, "x.ppt"); open(bad, "wb").write(b"not an ole file")
    try: pdf_intake.read_text(bad); ok = False
    except SystemExit as e: ok = ".pptx" in str(e)
    check("OLE 파일이 아닌 .ppt 는 .pptx 로 저장하라는 안내와 함께 거절", ok)

print("2. 스캔 PDF")
with tempfile.TemporaryDirectory() as d:
    pages = [Image.new("RGB", (420, 560), c) for c in ((250, 250, 250), (240, 240, 250), (250, 240, 240), (240, 250, 240), (230, 230, 230))]
    scan = os.path.join(d, "자바_실습_스캔.pdf")
    pages[0].save(scan, "PDF", save_all=True, append_images=pages[1:], resolution=100)
    jp = pdf_intake.embedded_jpegs(scan)
    check("PDF 안의 쪽 그림(JPEG)을 순서대로 꺼낸다 (5쪽)", len(jp) == 5 and all(x[:3] == b"\xff\xd8\xff" for x in jp), len(jp))
    check("작은 그림(로고)은 뺀다", pdf_intake.embedded_jpegs(scan, min_side=10000) == [])
    pic = pdf_intake.render_pdf_page(scan, 2, n_pages=5)
    check("그림 변환 도구가 없어도 쪽 번호에 맞는 그림이 나온다 (쪽 수와 그림 수가 같을 때)", pic is not None and pic[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xdb", b"\xff\xd8\xff\xee") or (pic or b"")[:3] == b"\xff\xd8\xff", (pic or b"")[:4])
    if pdf_intake.poppler_exe("pdftotext"):
        txt = pdf_intake.read_text(scan)
        check("글 층이 없는 PDF 는 스캔으로 판정한다", pdf_intake.is_scanned(scan, txt) and pdf_intake.page_count(txt) == 5, (len(txt), pdf_intake.page_count(txt)))
        kind, recs = parsing.build_records(None, [scan], labels=["자바_실습_스캔.pdf"])
        check("스캔 PDF 5쪽이 4쪽씩 2개 레코드로 만들어진다", kind == "원본" and len(recs) == 2 and [r["key"] for r in recs] == ["자바_실습_스캔_p1-4", "자바_실습_스캔_p5-5"], [r.get("key") for r in recs])
        r0 = recs[0]
        check("레코드는 문서 전체·스캔 표시와 쪽 그림 4장을 가진다", r0.get("문서전체") and r0.get("스캔") and len(r0.get("이미지") or []) == 4 and r0["원본조각"] == "", {k: (v if k != "이미지" else len(v)) for k, v in r0.items() if k != "intake"})
        check("메모에 스캔·대조 안내가 있다", any("스캔" in m and "대조" in m for m in r0["intake"]["메모"]), r0["intake"]["메모"])
        ut = parsing.user_text(r0)
        check("사용자 글은 스캔 문서이고 그림을 읽어 문제 단위로 나누라고 안내하며 JSON 으로 읽힌다", "[스캔 문서]" in ut and "자바_실습_스캔_p1-4_01" in ut and ut.split("입력: ", 1)[1].startswith("{"), ut[:200])
        check("그림은 입력 JSON 에 들어가지 않고 따로 붙는다", "b64" not in ut and len(parsing.attached_images(r0)) == 4)
        check("제목은 서버가 되돌리지 않는다 (AI 가 정한 이름_01, _02 …)", service.fix_title(r0, {"title": "자바_실습_스캔_p1-4_02"}) is None)
        os.environ["INTAKE_SCAN_PAGES"] = "3"
        try:
            _, recs3 = parsing.build_records(None, [scan], labels=["자바_실습_스캔.pdf"])
            check("INTAKE_SCAN_PAGES 로 읽을 쪽 수를 제한하고 안내를 남긴다", len(recs3) == 1 and any("앞 3쪽만" in m for m in recs3[0]["intake"]["메모"]), [m for m in recs3[0]["intake"]["메모"]])
        finally:
            os.environ.pop("INTAKE_SCAN_PAGES", None)
        orig = pdf_intake.render_pdf_page
        pdf_intake.render_pdf_page = lambda *a, **k: None
        try:
            _, none_recs = parsing.build_records(None, [scan], labels=["자바_실습_스캔.pdf"])
        finally:
            pdf_intake.render_pdf_page = orig
        h = service._forced_hold(none_recs[0])
        check("쪽 그림을 만들 수 없으면 AI 를 부르지 않고 이유와 함께 보류한다 (사람이 직접 넣게)", h and h["review"]["상태"] == "보류" and "그림으로 만들지 못해" in h["review"]["보류사유"] and h["payload"] is None, h)
        check("그림이 있는 스캔 레코드는 보류하지 않는다", service._forced_hold(r0) is None)
    else:
        print("  ⏭ poppler pdftotext 가 없어 스캔 판정·레코드 시험을 건너뜀")

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
