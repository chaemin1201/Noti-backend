"""문서 속 그림(코드·실행 화면 스크린샷)을 AI 에 보내는 경로 시험.
  ① 그림 준비(BMP→PNG, 개수·크기 제한)  ② 워드: 그림마다 [이미지] 와 파일  ③ hwpx  ④ 문제 구간별로 그림 나누기  ⑤ 레코드·AI 요청에 그림이 실리는가
noti_test 폴더에서:  python test_images.py        (Pillow, python-docx 필요)"""
import base64, io, os, sys, tempfile, zipfile
import _bootstrap
_bootstrap.setup()
try:
    from PIL import Image
    import docx
except ImportError as e:
    print(f"⏭ 건너뜀: {e.name} 가 필요합니다 (pip install pillow python-docx)"); sys.exit(2)
from app.inputdata.intake import parsing, llm
from app.inputdata.intake.readers import images
from app.inputdata.intake.readers import pdf_intake

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def pic(fmt="PNG", size=(40, 20), color=(200, 30, 30)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, fmt); return b.getvalue()

print("1. 그림 준비")
check("BMP 는 PNG 로 바꾼다 (Gemini 가 BMP 를 받지 않음)", images.prepare(pic("BMP"))[0] == "image/png")
check("EMF 처럼 못 쓰는 형식은 None", images.prepare(b"\x01\x00\x00\x00" + b"x" * 40) is None and images.prepare(None) is None)
big = images.prepare(pic("PNG", (4000, 3000)))
w, h = Image.open(io.BytesIO(big[1])).size
check("너무 큰 그림은 긴 변 1600 이하로 줄인다", max(w, h) <= images.MAX_SIDE, (w, h))
att, notes = images.attach([pic(), None, pic("BMP")])
check("자리 번호(n)는 [이미지] 순서이고 없는 자리는 건너뛴다", [a["n"] for a in att] == [1, 3] and not notes, [a["n"] for a in att])
att, notes = images.attach([pic()] * (images.MAX_IMAGES + 2))
check("한 문제에 붙이는 그림 수를 제한하고 알린다", len(att) == images.MAX_IMAGES and len(notes) == 2, (len(att), notes))
check("b64 가 되돌려 읽힌다", Image.open(io.BytesIO(base64.b64decode(att[0]["b64"]))).size == (40, 20))

print("2. 워드(.docx): 그림마다 [이미지] 와 파일")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "t.docx"); doc = docx.Document()
    doc.add_paragraph("실습 1. 첫 문제를 푸시오.")
    r = doc.add_paragraph("코드 화면").add_run(); r.add_picture(io.BytesIO(pic(color=(10, 10, 200))))
    r.add_picture(io.BytesIO(pic(color=(10, 200, 10))))
    doc.add_paragraph("실습 2. 둘째 문제를 푸시오.")
    doc.add_paragraph("실행 화면").add_run().add_picture(io.BytesIO(pic(color=(200, 200, 10))))
    doc.add_paragraph("실습 3. 그림 없는 문제를 푸시오.")
    doc.save(p)
    imgs = []; txt = pdf_intake.docx_text(p, imgs)
    check("한 문단에 그림 2개면 [이미지] 도 2개", txt.count("[이미지]") == 3 and len(imgs) == 3 and all(imgs), (txt.count("[이미지]"), len(imgs)))
    check("그림 파일이 실제 색과 같다 (순서가 맞다)", Image.open(io.BytesIO(imgs[0])).getpixel((1, 1))[2] > 150 and Image.open(io.BytesIO(imgs[1])).getpixel((1, 1))[1] > 150)
    check("images 를 주지 않으면 이전과 같이 글만 돌려준다", pdf_intake.docx_text(p).count("[이미지]") == 3)

    print("3. 문제 구간별로 그림 나누기")
    secs = list(pdf_intake.sections_with_images(p, label="자바_실습_문제.docx"))
    check("문제 3개, 그림은 2 / 1 / 0 개", [len(s[3]) for s in secs] == [2, 1, 0], [(s[0], len(s[3])) for s in secs])
    kind, recs = parsing.build_records(None, [p], labels=["자바_실습_문제.docx"])
    check("레코드에 그림이 붙고 메모로 알린다", [len(r.get("이미지") or []) for r in recs] == [2, 1, 0] and "그림 2개를 함께 보냄" in " ".join(recs[0]["intake"]["메모"]), recs[0]["intake"]["메모"])
    check("AI 에 보내는 글에는 그림 데이터가 들어가지 않는다", "b64" not in parsing.user_text(recs[0]) and len(parsing.user_text(recs[0])) < 3000)
    check("그림이 없는 문제는 첨부 목록이 비어 있다", parsing.attached_images(recs[2]) == [] and "이미지" not in recs[2])
    pair = parsing.build_records(None, [p, p], labels=["a_문제.docx", "a_풀이.docx"])[1]
    check("문제 파일과 풀이 파일을 함께 올려도 문제 파일의 그림은 붙는다", [len(r.get("이미지") or []) for r in pair] == [2, 1, 0] and all(r.get("정답자료") for r in pair))

print("3b. 파일 이름에 '풀이'가 있어도, 그 파일에서만 나오는 문제는 그림이 붙는다")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "f0.docx"); doc = docx.Document()
    doc.add_paragraph("실습 1. 그림이 든 문제.").add_run().add_picture(io.BytesIO(pic()))
    doc.add_paragraph("실습 2. 그림 없는 문제."); doc.save(p)
    recs = parsing.build_records(None, [p], labels=["cpp_풀이.docx"])[1]
    check("풀이 파일 하나만 올려도 그림이 붙는다 (워드 08_03~05 가 그림 없이 보내졌던 결함)", [len(r.get("이미지") or []) for r in recs] == [1, 0], [len(r.get("이미지") or []) for r in recs])

print("4. hwpx")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "t.hwpx")
    xml = ('<sec xmlns:hp="urn:hp" xmlns:hc="urn:hc"><hp:p><hp:run><hp:t>실습 1. 그림 문제</hp:t></hp:run></hp:p>'
           '<hp:p><hp:run><hp:pic><hc:img binaryItemIDRef="image1"/></hp:pic></hp:run></hp:p>'
           '<hp:p><hp:run><hp:t>실습 2. 다음 문제</hp:t></hp:run></hp:p></sec>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Contents/section0.xml", xml); z.writestr("BinData/image1.png", pic())
    imgs = []; txt = pdf_intake.read_text(p, imgs)
    check("hwpx 의 그림이 참조 이름으로 꺼내진다", txt.count("[이미지]") == 1 and len(imgs) == 1 and imgs[0] and imgs[0][:4] == b"\x89PNG", (txt, len(imgs)))

print("4b. PDF: 그림이 있는 쪽을 문제별로 나눈다 (poppler 대신 모의 데이터)")
PTXT = "실습 1. 첫째\n내용\n\f이어지는 내용\n그림 쪽\n\f실습 2. 둘째\n내용\n\f실습 3. 셋째\n끝"
saved = (pdf_intake.read_text, pdf_intake.pdf_image_pages, pdf_intake.render_pdf_page)
pdf_intake.read_text = lambda path, images=None: PTXT
pdf_intake.pdf_image_pages = lambda path, **k: {2, 4}
PG = {n: pic(color=(n * 40, 0, 0)) for n in range(1, 6)}
pdf_intake.render_pdf_page = lambda path, page, dpi=110: PG[page]
try:
    secs = list(pdf_intake.sections_with_images("x.pdf", label="자바_실습.pdf"))
    check("문제 3개를 찾고 쪽 번호가 맞다", [s[0] for s in secs] == ["자바_실습_01", "자바_실습_02", "자바_실습_03"] and [s[1] for s in secs] == [1, 3, 4], [(s[0], s[1]) for s in secs])
    check("문제가 걸친 쪽 중 그림이 있는 쪽만 붙는다 (1번: 2쪽, 2번: 없음, 3번: 4쪽)", [s[3] for s in secs] == [[PG[2]], [], [PG[4]]], [s[3] for s in secs])
    check("images 를 끄면 쪽을 그리지 않는다", all(s[3] == [] for s in pdf_intake.sections_with_images("x.pdf", label="자바_실습.pdf", with_images=False)))
    kind, recs = parsing.build_records(None, ["x.pdf"], labels=["자바_실습.pdf"])
    check("레코드 메모가 쪽 전체 화면임을 알린다", "쪽 전체 화면" in " ".join(recs[0]["intake"]["메모"]) and len(recs[0]["이미지"]) == 1, recs[0]["intake"]["메모"])
finally:
    pdf_intake.read_text, pdf_intake.pdf_image_pages, pdf_intake.render_pdf_page = saved

print("4c. 그림에서 옮긴 설명 글은 원본 글 대조에서 막히지 않는다")
from app.inputdata.intake.checks import checker
NL = chr(10)
LINES = ["첫 번째 줄의 문장입니다 가나다", "두 번째 줄의 문장입니다 라마바", "세 번째 줄은 그림에서 옮긴 글입니다", "네 번째 줄도 그림에서 옮긴 글입니다", "다섯 번째 줄 그림에서 옮긴 글입니다"]
case = {"id": "T", "payload": {"problemType": "주관식", "title": "T", "description": NL.join(LINES), "answer_text": "답"},
        "review": {"확인필요": []}, "원본조각": NL.join(LINES[:2]) + NL + "[이미지]"}
f1, _ = checker.check_case(dict(case), {}, True)
f2, _ = checker.check_case({**case, "그림있음": True}, {}, True)
check("그림이 없으면 원본에 없는 줄이 많을 때 막는다", any(x.startswith("src:") for x in f1), f1)
check("그림이 있는 문제는 같은 설명도 통과한다", not any(x.startswith("src:") for x in f2), f2)

print("4d. PDF: 수식이 글로 빠진 쪽도 화면을 보낸다 (그림 파일이 없어도)")
PUA = chr(0xE04B) + chr(0xE0EA) + chr(0xE044)
LTXT = "실습 1. 함수값을 구하시오." + chr(10) + "계산하여 출력" + chr(10) + chr(12) + "   " + PUA + " " + PUA + "  ≤" + chr(10) + "출력결과" + chr(10) + chr(12) + "실습 2. 평범한 문제" + chr(10) + "내용"
saved = (pdf_intake.read_text, pdf_intake.pdf_image_pages, pdf_intake.render_pdf_page)
pdf_intake.read_text = lambda path, images=None: LTXT
pdf_intake.pdf_image_pages = lambda path, **k: set()
pdf_intake.render_pdf_page = lambda path, page, dpi=110: PG[page]
try:
    check("수식 글꼴 코드 문자가 든 줄을 수식이 빠진 흔적으로 본다", len(pdf_intake.lossy_lines(LTXT)) == 1 and not pdf_intake.lossy_lines("a <= b 이면 x ** 2" + chr(10) + "int main() { return 0; }"))
    secs = list(pdf_intake.sections_with_images("x.pdf", label="자바_실습.pdf"))
    check("그림 파일이 없어도 수식이 빠진 쪽(2쪽)을 해당 문제에만 붙인다", [s[0] for s in secs] == ["자바_실습_01", "자바_실습_02"] and [s[3] for s in secs] == [[PG[2]], []], [(s[0], len(s[3])) for s in secs])
finally:
    pdf_intake.read_text, pdf_intake.pdf_image_pages, pdf_intake.render_pdf_page = saved

print("4e. 쪽 그리기: pdftoppm 이 없으면 pypdfium2 로 대신한다")
import types
real_run = pdf_intake.subprocess.run
pdf_intake.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("pdftoppm"))      # pdftoppm 이 없는 환경
class _Img:
    def save(self, buf, fmt): buf.write(b"PNGDATA")
class _Page:
    def render(self, scale): return types.SimpleNamespace(to_pil=lambda: _Img()), scale
class _Bitmap:
    def __init__(self, scale): self.scale = scale
    def to_pil(self): return _Img()
class _Doc:
    def __init__(self, path): self.path = path
    def __getitem__(self, i): return types.SimpleNamespace(render=lambda scale: _Bitmap(scale))
    def close(self): pass
fake = types.ModuleType("pypdfium2"); fake.PdfDocument = _Doc
try:
    sys.modules.pop("pypdfium2", None)
    check("pypdfium2 가 없으면 None (그림 없이 글만 보낸다)", pdf_intake.render_pdf_page("x.pdf", 1) is None)
    sys.modules["pypdfium2"] = fake
    check("pypdfium2 가 있으면 그것으로 그린다", pdf_intake.render_pdf_page("x.pdf", 1) == b"PNGDATA")
finally:
    pdf_intake.subprocess.run = real_run; sys.modules.pop("pypdfium2", None)

print("5. AI 요청에 그림이 실리는가")
sent = {}
real = llm._post
llm._post = lambda url, headers, body, timeout, waits, on_retry=None: (sent.update(body=body), {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})[1]
try:
    llm.call_llm("google", "m", "k", "sys", "글", images=[{"mime": "image/png", "b64": "AAAA"}], retries=0)
    parts = sent["body"]["contents"][0]["parts"]
    check("Gemini: 글 뒤에 inline_data 로 붙는다", parts[0] == {"text": "글"} and parts[1] == {"inline_data": {"mime_type": "image/png", "data": "AAAA"}}, parts)
    llm.call_llm("google", "m", "k", "sys", "글", retries=0)
    check("그림이 없으면 요청이 이전과 같다", sent["body"]["contents"][0]["parts"] == [{"text": "글"}])
    llm._post = lambda url, headers, body, timeout, waits, on_retry=None: (sent.update(body=body), {"content": [{"type": "text", "text": "{}"}]})[1]
    llm.call_llm("anthropic", "m", "k", "sys", "글", images=[{"mime": "image/png", "b64": "AAAA"}], retries=0)
    c = sent["body"]["messages"][0]["content"]
    check("Claude: image 블록으로 붙는다", c[0] == {"type": "text", "text": "글"} and c[1]["type"] == "image" and c[1]["source"]["data"] == "AAAA", c)
finally:
    llm._post = real

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
