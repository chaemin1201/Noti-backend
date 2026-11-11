"""원본 문제지(PDF)를 문제 단위로 나누고 사전 점검한다. (원본만 받는 경로의 입력 준비)"""
import re, subprocess, unicodedata

from . import images as safety      # 업로드 파일 안전 점검(images.py 안)

ID_RE = re.compile(r"문제\s+([A-Z]{1,3}\d{2,3}-\d{4})")
FOOT_RE = re.compile(r"문제지\(\d+\).*\s\d+\s*$|^\s*\d+\s*$")
METHOD_RE = re.compile(r"방법\s*\d|풀이\s*\d|택\s*1|모두\s*작성")
ITEM_RE = re.compile(r"^[ \t|\f]*\((\d{1,2})\)[ \t]+(?=\S)", re.M)                   # "(3) 아래의 main() 이 …" 같은 번호 항목
HEADING_RE = re.compile(r"^[ \t|\f]*[\[(<]?\s*(?:실습|문제|과제|예제|Problem|Q)\s*(\d{1,3})\s*번?\s*(?:[\])>]\s*[.):：]?|[.):：])", re.M)       # "실습 1." "문제 1)" "문제 1:" "[문제 1]" "Q1." "문제 1번."
HEADING_NONUM_RE = re.compile(r"^[ 	|]*(?:실습|문제|과제)[ 	]*[.):：][ 	]*(?=\S)", re.M)       # 번호 없는 제목 ("실습 . 10000보다 작은 …")
NUMBER_RE = re.compile(r"^[ 	|]{0,3}(\d{1,2})\.[ 	]+(?=\S)", re.M)                             # "1. 상속에 대한 …" 처럼 낱말 없이 번호만 있는 제목
TITLE_SPACED_RE = re.compile(r"^[\s|]*([A-Za-z+#]{1,6})[ 	]+(\d{1,2})[ 	]+\S", re.M)                  # "C++ 08 복사&이동생성자" → 접두 "C++_08" (텍스트·한글 문서의 제목 모양)
TITLE_RE = re.compile(r"^[\s|]*([^\s_|\-]+_[^\s_|]+)_", re.M)                              # "C++_06_클래스와객체 학번 :" → 접두 "C++_06"
BLANK_RE = re.compile(r"#{5,}|/{5,}|-{5,}\s*.*작성|_{4,}|코드\s*(추가|작성)")


def norm(s): return re.sub(r"\s+", "", unicodedata.normalize("NFC", s))


def clean(text):
    lines = [l.rstrip() for l in text.splitlines() if not FOOT_RE.search(l.strip() or "x")]
    out = "\n".join(lines).strip("\n")
    ind = [len(l) - len(l.lstrip()) for l in out.splitlines() if l.strip()]
    if ind:                                   # 페이지 레이아웃 때문에 붙은 공통 들여쓰기 제거 (코드의 상대 들여쓰기는 유지)
        cut = min(ind)
        out = "\n".join(l[cut:] if l.strip() else "" for l in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out)


_CONCEPT_RE = re.compile(r"물음에\s*답|질문에\s*답|다음\s*물음|답하시오|답하세요")
_WRITE_CODE_RE = re.compile(r"(프로그램|코드|메소드|메서드|함수|클래스|생성자|소스).{0,14}(작성|구현|완성|추가|생성)\s*(하시오|하세요|해\s*보|해보)|(작성|구현|완성)하시오.*(프로그램|코드)")
_EXPLAIN_RE = re.compile(r"설명|이유|의미|서술|역할|어떻게|차이|무엇인가")


_OPT_LINE = re.compile(r"(?m)^[ \t]*(?:[①-⑩]|\(?[1-9]\)|[1-9][.)]|\(?[A-Ea-e][.)])[ \t]*\S")        # 보기 줄: ① … / 1) … / A. …
_CIRCLED = re.compile(r"(?m)^[ \t]*[①-⑩][ \t]*\S")
_PICK_RE = re.compile(r"고르시오|고르세요|옳은\s*것|옳지\s*않은|아닌\s*것|해당하는\s*것|알맞은\s*것|맞는\s*것|틀린\s*것|가장\s*적절")
_ANS_VALUE_RE = re.compile(r"(?:이름|명령어|명령|용어|값|키워드|표기|기호|번호|개수|횟수)[을를]?\s*(?:쓰시오|쓰세요|적으시오|적으세요|구하시오|구하세요)")
_MAKE_RE = re.compile(r"작성하(?:시오|세요|여|고)|구현하(?:시오|세요|여|고)|만드시오|만들어|프로그램을\s*만|코드를\s*(?:작성|짜)")


_IMPERATIVE_RE = re.compile(r"(?:쓰|나열하|생성하|작성하|구현하|설명하|서술하|답하|구하|적|고치|수정하|완성하)(?:시오|세요|십시오)|(?:쓰|적)시오")


def _n_opts(text):
    """보기 줄 수: ①… / 1) … / A. … 로 시작하고, 짧고(80자 이하), 줄 안에 물음표가 없고, 명령문('~쓰시오', '~나열하시오')이 아닌 줄."""
    return sum(1 for l in text.split(chr(10)) if _OPT_LINE.match(l) and "?" not in l and len(l.strip()) <= 80 and not _IMPERATIVE_RE.search(l))


_CODE_RE = re.compile(r"#include|def |print\(|printf|int main|for\s*\w+\s+in\s|for\s*\(|\bclass\s+\w+\s*[:{(]|\b(public|private|protected)\s*:")


def has_code(text):
    """글 안에 코드(주어진 코드·클래스 선언 등)가 들어 있는가."""
    return bool(_CODE_RE.search(text or ""))


def hint(text, blank, code):
    if len(_CIRCLED.findall(text)) >= 3 or (_n_opts(text) >= 3 and (_PICK_RE.search(text) or ("?" in text and not _MAKE_RE.search(text)))):      # 보기가 줄지어 있고 고르라는 말이 있으면 객관식
        return "객관식"
    n_sub = len(re.findall(r"(?m)^[ \t]*\(?(?:[a-zA-Z가-하]|\d{1,2})[).]+[ \t]+\S", text))
    n_write = len(_WRITE_CODE_RE.findall(text))
    if _CONCEPT_RE.search(text) and (n_write == 0 or (n_sub >= 3 and n_write == 1)):       # "다음 물음에 답하시오. a) …는? b) …인가?" 처럼 코드를 쓰는 것이 아니라 묻는 문제 (소문항이 셋 이상이고 코드를 쓰라는 소문항이 하나뿐이면 그것도 물음 중 하나)
        if n_sub >= 2: return "단답형"      # 소문항이 둘 이상이면 소문항별 정답(단답형)
        return "주관식" if _EXPLAIN_RE.search(text) and len(_EXPLAIN_RE.findall(text)) >= 3 else "단답형"
    if re.search(r"(출력\s*)?결과를?\s*(?:작성|쓰시오|쓰세요|적으시오|적으세요|구하시오|구하세요)|출력되는\s*(?:값|내용)[을를]?\s*(?:쓰시오|쓰세요|적으시오)", text): return "단답형"
    if _ANS_VALUE_RE.search(text) and not _MAKE_RE.search(text): return "단답형"                          # "~ 이름을 쓰시오" 처럼 값 하나를 쓰는 문제 (프로그램·함수 낱말이 있어도)
    if blank or (code and re.search(r"완성|추가|구현|수정|고치|작성하시오", text)): return "디버깅"      # 주어진 코드(클래스 선언·함수 틀 포함)를 완성·구현·수정하는 문제
    if re.search(r"(기술|설명)\s*(을\s*)?(하|해)\s*(시오|보)", text) and "프로그램" not in text: return "주관식"
    if not _PROGRAM_CUE.search(text):                                                  # 프로그램·코드를 쓰라는 말이 없는 질문은 코딩이 아니다
        if _EXPLAIN_RE.search(text): return "주관식"
        if re.search(r"쓰시오|적으시오|무엇인가|무엇입니까|구하시오|답하시오|고르시오|이름은|\?\s*$", text.strip()): return "단답형"
    return "코딩"


_PROGRAM_CUE = re.compile(r"프로그램|코드|함수|클래스|메서드|메소드|소스|구현|입력\s*받|출력하는|알고리즘을?\s*(?:작성|구현)|스크립트|쿼리를?\s*작성|SELECT\b|def\s|public\s+class|#include|print\s*\(")


IMG_MARK = "[이미지]"


def _w(el, tag):
    return el.xpath(f"./w:{tag}")


_WNS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _x(el, path):
    from lxml import etree
    return etree.XPath(path, namespaces=_WNS)(el)


def _numbering(doc):
    """워드의 자동 번호 정의를 읽는다. (numId → abstractNumId, abstractNumId → {수준: (형식, 문구, 시작값)})"""
    try:
        root = doc.part.numbering_part.element
    except Exception:
        return {}, {}
    num_to_abs = {}
    for n in _x(root, "./w:num"):
        nid = n.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId")
        ab = _x(n, "./w:abstractNumId")
        if ab: num_to_abs[nid] = ab[0].get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
    abstract = {}
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for a in _x(root, "./w:abstractNum"):
        lv = {}
        for l in _x(a, "./w:lvl"):
            fmt = _x(l, "./w:numFmt"); txt = _x(l, "./w:lvlText"); st = _x(l, "./w:start")
            lv[int(l.get(ns + "ilvl"))] = (fmt[0].get(ns + "val") if fmt else "decimal", txt[0].get(ns + "val") if txt else "", int(st[0].get(ns + "val")) if st else 1)
        abstract[a.get(ns + "abstractNumId")] = lv
    return num_to_abs, abstract


def _para_numpr(p):
    """문단(또는 그 스타일)의 (numId, 수준). 번호가 없으면 None."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    def of(pPr):
        if pPr is None: return None
        np_ = pPr.xpath("./w:numPr")
        if not np_: return None
        nid = np_[0].xpath("./w:numId"); lv = np_[0].xpath("./w:ilvl")
        if not nid: return None
        return nid[0].get(ns + "val"), int(lv[0].get(ns + "val")) if lv else 0
    r = of(p._p.pPr)
    if r: return r
    st = p.style
    for _ in range(6):
        if st is None: break
        r = of(st.element.pPr)
        if r: return r
        st = st.base_style
    return None


def _fmt_num(n, fmt):
    if fmt == "lowerLetter": return chr(96 + n) if 1 <= n <= 26 else str(n)
    if fmt == "upperLetter": return chr(64 + n) if 1 <= n <= 26 else str(n)
    if fmt == "decimalZero": return f"{n:02d}"
    if fmt in ("lowerRoman", "upperRoman"):
        vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]; out = ""; m = n
        for v, r in vals:
            while m >= v: out += r; m -= v
        return out if fmt == "lowerRoman" else out.upper()
    return str(n)


def docx_text(path, images=None):
    """워드 문서를 본문 순서대로 텍스트로 만든다."""
    import docx                                               # ImportError 는 호출한 쪽에서 처리
    safety.check_zip(path)
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(path)
    num_to_abs, abstract = _numbering(d)
    counters = {}

    def label(p):
        r = _para_numpr(p)
        if not r: return ""
        nid, lvl = r
        lv = abstract.get(num_to_abs.get(nid), {})
        if lvl not in lv: return ""
        fmt, txt, start = lv[lvl]
        c = counters.setdefault(nid, {})
        c[lvl] = c.get(lvl, start - 1) + 1
        for deeper in [k for k in c if k > lvl]: del c[deeper]          # 하위 수준은 다시 시작
        if fmt == "bullet": return "-"
        out = txt
        for i in range(9):
            out = out.replace(f"%{i + 1}", _fmt_num(c.get(i, abstract[num_to_abs[nid]].get(i, (0, 0, 1))[2]), abstract[num_to_abs[nid]].get(i, ("decimal",))[0]))
        return out

    def para(p):
        t = p.text.replace("\xa0", " ")
        pics = p._p.xpath(".//w:drawing | .//w:pict")
        if pics:
            t = (t + (" " + IMG_MARK) * len(pics)).strip()
            if images is not None:
                for el in pics:
                    rid = (el.xpath(".//a:blip/@r:embed") or el.xpath(".//v:imagedata/@r:id") or [None])[0]
                    try: images.append(p.part.related_parts[rid].blob if rid else None)
                    except Exception: images.append(None)
        lab = label(p)
        return (lab + " " + t).rstrip() if lab and t.strip() else t

    out = []

    def table(t, sink, depth=0):
        for row in t.rows:
            cells, seen = [], set()
            for c in row.cells:
                if id(c._tc) in seen: continue                 # 병합된 칸은 한 번만
                seen.add(id(c._tc))
                lines = []
                for el in c._tc.iterchildren():
                    if el.tag.endswith("}p"): lines.append(para(Paragraph(el, c)))
                    elif el.tag.endswith("}tbl") and depth < 3:
                        sub = []; table(Table(el, c), sub, depth + 1); lines += sub
                cells.append("\n".join(lines).rstrip())
            sink.append(cells[0] if len(cells) == 1 else "   ".join(x.replace("\n", " ") for x in cells))

    for el in d.element.body.iterchildren():
        if el.tag.endswith("}p"): out.append(para(Paragraph(el, d)))
        elif el.tag.endswith("}tbl"): table(Table(el, d), out)
    return "\n".join(out)


def pptx_text(path, images=None):
    """파워포인트(.pptx)를 슬라이드 순서대로 읽는다. 글상자·표·그림·발표자 노트를 만든 순서(위에서 아래가 아닐 수 있음)대로 풀어 쓰고,"""
    import zipfile, posixpath
    from xml.etree import ElementTree as ET
    safety.check_zip(path)
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "ppt/presentation.xml" not in names: raise SystemExit("파워포인트(.pptx) 형식이 아닙니다. 구형 .ppt 는 파워포인트에서 .pptx 로 다시 저장해 올려 주세요.")

        def rels(part):
            d, b = posixpath.split(part)
            rp = f"{d}/_rels/{b}.rels"
            if rp not in names: return {}
            out = {}
            for r in ET.fromstring(z.read(rp)):
                if r.get("TargetMode") != "External": out[r.get("Id")] = (r.get("Type", ""), posixpath.normpath(posixpath.join(d, r.get("Target", ""))))
            return out

        def para_text(p):
            parts = []
            for c in p:
                if c.tag in (A + "r", A + "fld"): parts.append("".join(t.text or "" for t in c if t.tag == A + "t"))
                elif c.tag == A + "br": parts.append("\n")
            return "".join(parts).replace("\xa0", " ").rstrip()

        def walk(el, sink, rl):
            for c in el:
                if c.tag == P + "sp":
                    for tb in (x for x in c if x.tag == P + "txBody"):
                        for p in (x for x in tb if x.tag == A + "p"): sink.append(para_text(p))
                elif c.tag == P + "graphicFrame":
                    for tbl in c.iter(A + "tbl"):
                        for tr in (x for x in tbl if x.tag == A + "tr"):
                            cells = ["\n".join(para_text(p) for p in tc.iter(A + "p")).strip() for tc in tr if tc.tag == A + "tc"]
                            sink.append("   ".join(x.replace("\n", " ") for x in cells))
                elif c.tag == P + "pic":
                    sink.append(" " + IMG_MARK)
                    if images is not None:
                        blip = next(c.iter(A + "blip"), None)
                        tgt = rl.get(blip.get(R + "embed")) if blip is not None else None
                        images.append(z.read(tgt[1]) if tgt and tgt[1] in names else None)
                elif c.tag == P + "grpSp":
                    walk(c, sink, rl)

        pres = ET.fromstring(z.read("ppt/presentation.xml")); prel = rels("ppt/presentation.xml")
        slides = [prel[s.get(R + "id")][1] for s in pres.iter(P + "sldId") if s.get(R + "id") in prel]
        out = []
        for sp in slides:
            if sp not in names: continue
            root, rl, lines = ET.fromstring(z.read(sp)), rels(sp), []
            walk(next((x for x in root.iter(P + "spTree")), root), lines, rl)
            note = next((t[1] for t in rl.values() if t[0].endswith("/notesSlide") and t[1] in names), None)
            if note:                                                 # 발표자 노트에 정답·풀이가 있는 경우가 많다 (본문 글상자 'body' 만)
                nl = []
                for s in ET.fromstring(z.read(note)).iter(P + "sp"):
                    ph = next((x for x in s.iter(P + "ph")), None)
                    if ph is not None and ph.get("type") == "body":
                        nl += [para_text(p) for p in s.iter(A + "p")]
                nl = [x for x in nl if x.strip()]
                if nl: lines.append("[발표자 노트] " + " ".join(nl))
            out.append("\n".join(lines).strip("\n"))
    return "\n\f".join(out)                        # PDF 와 같이 쪽 구분 앞에 줄바꿈을 둬서 다음 슬라이드의 첫 줄도 줄 맨 앞으로 읽힌다


def slide_marks(txt, stem):
    """번호 제목이 없는 슬라이드 묶음의 마지막 방법: 글이 어느 정도 있는 슬라이드 하나를 문제 하나로 본다 [(문제ID, 시작, 본문시작)]."""
    out, pos = [], 0
    for i, s in enumerate(txt.split("\f"), 1):
        if len(norm(s)) >= 10: out.append((f"{stem}_{i:02d}", pos, pos))
        pos += len(s) + 1
    return out if len(out) >= 1 else []


FORMATS = {".pdf": "PDF", ".docx": "워드", ".pptx": "파워포인트", ".ppt": "파워포인트", ".hwp": "한글", ".hwpx": "한글", ".txt": "텍스트", ".md": "마크다운",
           ".db": "DB", ".sqlite": "DB", ".sqlite3": "DB", ".xlsx": "엑셀", ".xlsm": "엑셀", ".csv": "CSV", ".tsv": "CSV", ".tab": "CSV"}


def format_of(path):
    """파일 확장자 → 형식 이름. 형식마다 변환 중 생기는 손실이 달라서 AI 에게 함께 보낸다 (프롬프트의 <형식별 필터링>)."""
    low = path.lower()
    return next((v for k, v in FORMATS.items() if low.endswith(k)), "기타")


def poppler_exe(name):
    """poppler 도구(pdftotext, pdfimages, pdftoppm)의 실행 파일 경로. PATH 에 없으면 환경변수 POPPLER_PATH 폴더와 윈도우의 흔한 설치 위치(Git for Windows, MSYS2)에서 찾고, 없으면 None."""
    import os, shutil
    p = shutil.which(name)
    if p: return p
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (os.environ.get("POPPLER_PATH"), r"C:\Program Files\Git\mingw64\bin", r"C:\msys64\mingw64\bin"):
        if d and os.path.isfile(os.path.join(d, exe)): return os.path.join(d, exe)
    return None


POPPLER_HELP = ("PDF 를 읽으려면 poppler 의 pdftotext 가 필요합니다. 서버(리눅스)는 `apt install poppler-utils`, 윈도우 개발 PC 는 poppler 를 설치하고 PATH 에 넣거나 "
                "환경변수 POPPLER_PATH 에 폴더를 적으세요.")


def read_text(path, images=None):
    """PDF / DOCX / HWP / HWPX / TXT / MD 에서 텍스트를 읽는다."""
    low = path.lower()
    if low.endswith((".hwp", ".hwpx")):
        try:
            from . import hwp_text
        except ImportError:                        # 서버 패키지가 아닌 폴더에서 직접 실행할 때
            import hwp_text
        return hwp_text.hwpx_text(path, images) if low.endswith(".hwpx") else hwp_text.hwp_text(path, images)
    if low.endswith(".pdf"):
        # -enc UTF-8 이 없으면 pdftotext 는 Latin1 로 내보내서 한글이 모두 사라진다 (윈도우, 로케일이 없는 리눅스 컨테이너)
        exe = poppler_exe("pdftotext")
        if not exe: raise SystemExit(POPPLER_HELP)
        return subprocess.run([exe, "-enc", "UTF-8", "-layout", path, "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
    if low.endswith(".pptx") or low.endswith(".ppt"):
        if low.endswith(".ppt"):
            try:
                from . import ppt_legacy
            except ImportError:                    # 서버 패키지가 아닌 폴더에서 직접 실행할 때
                import ppt_legacy
            return ppt_legacy.ppt_text(path, images)
        return pptx_text(path, images)
    if low.endswith(".docx"):
        try:
            return docx_text(path, images)            # 표 안의 코드가 한 줄씩 그대로 읽힘 (python-docx 필요: pip install python-docx)
        except ImportError:
            pass
        try:
            r = subprocess.run(["pandoc", "-t", "plain", "--wrap=none", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0: return r.stdout
        except OSError:                                       # pandoc 도 없음
            pass
        raise SystemExit("워드(.docx)를 읽으려면 서버에 python-docx 패키지가 필요합니다 (pip install python-docx). 서버 관리자에게 문의하세요.")
    return safety.read_text_file(path)                        # .txt/.md: UTF-8, UTF-16, CP949 를 알아서 읽는다


def numbered_marks(txt):
    """문서 제목(첫 줄 근처)의 접두와 "(n)" 항목으로 [(문제ID, 시작, 본문시작)] 을 만든다. 예: C++_06 + (3) → C++_06_03"""
    head = "\n".join(txt.splitlines()[:25])
    t = TITLE_RE.search(head)
    if t: prefix = t.group(1)
    else:
        t = TITLE_SPACED_RE.search(head)
        if not t: return []
        prefix = f"{t.group(1)}_{t.group(2)}"
    return [(f"{prefix}_{int(m.group(1)):02d}", m.start(), m.end()) for m in ITEM_RE.finditer(txt)]


def marks_of(txt, id_re=None):
    """[(문제ID, 시작, 본문시작)]. 'ID 정규식' 이 우선이고, 하나도 없을 때만 번호 항목 형식을 쓴다."""
    ms = [(m.group(1), m.start(), m.end()) for m in (id_re or ID_RE).finditer(txt)]
    return ms or ([] if id_re else numbered_marks(txt))


def file_stem(path):
    """파일 이름에서 문제 묶음 이름을 만든다. 문제 파일과 풀이 파일이 같은 이름이 되도록 '풀이·문제·정답' 꼬리와 앞의 연도를 뗀다."""
    s = re.sub(r"\.[A-Za-z0-9]+$", "", path.replace(chr(92), "/").split("/")[-1])
    s = re.sub(r"[_\s-]*(풀이|정답|해설|문제)\s*$", "", s)
    s = re.sub(r"^\d{4}[_\s-]+", "", s)
    return re.sub(r"\s+", "", s).strip("_-")


def heading_marks(txt, stem):
    """ID 정규식도 '(n) 항목'도 없을 때의 마지막 방법: '실습 1.' 같은 번호 제목으로 [(문제ID, 시작, 본문시작)] 을 만든다."""
    out, last, group = [], 0, 0
    if len(HEADING_RE.findall(txt)) < 2:                   # 낱말 제목이 없으면 번호만 있는 제목: 1, 2, 3 … 순서로 이어지는 번호만 인정한다 (코드·목록 속 숫자 제외)
        for m in NUMBER_RE.finditer(txt):
            if int(m.group(1)) == last + 1:
                last += 1; out.append((f"{stem}_{last:02d}", m.start(), m.end()))
        return out if len(out) >= 2 else []
    marks = [(m.start(), m.end(), int(m.group(1))) for m in HEADING_RE.finditer(txt)]
    for m in HEADING_NONUM_RE.finditer(txt):                  # 자동 번호가 글로 안 옮겨져 "실습 . 문장" 처럼 번호만 빠진 제목: 앞 번호 다음 번호로 본다
        if any(s <= m.start() < e for s, e, _ in marks): continue
        marks.append((m.start(), m.end(), None))
    marks.sort()
    for start, end, n in marks:
        if n is None:
            if last == 0: continue
            n = last + 1
        if n <= last: group += 1
        last = n
        suffix = "" if group == 0 else chr(ord("a") + group)
        out.append((f"{stem}_{n:02d}{suffix}", start, end))
    return out if len(out) >= 2 else []                    # 번호 제목이 하나뿐이면 문제지가 아닐 가능성이 커서 쓰지 않는다


def pdf_image_pages(path, min_w=100, min_h=40):
    """그림(래스터)이 들어 있는 쪽 번호 집합. 로고·아이콘 같은 작은 그림은 뺀다. pdfimages 가 없거나 실패하면 빈 집합."""
    try:
        r = subprocess.run([poppler_exe("pdfimages") or "pdfimages", "-list", path], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    pages = set()
    for ln in r.stdout.splitlines()[2:]:
        c = ln.split()
        if len(c) > 4 and c[0].isdigit() and c[3].isdigit() and c[4].isdigit() and int(c[3]) >= min_w and int(c[4]) >= min_h and c[2] != "smask":
            pages.add(int(c[0]))
    return pages


def _render_pdfium(path, page, dpi):
    """pypdfium2(pip install pypdfium2)로 한 쪽을 그린다. 없으면 None. poppler 를 설치할 수 없는 환경(윈도우 개발 PC 등)의 대체 경로이다."""
    try:
        import io, pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(path)
        try:
            img = doc[page - 1].render(scale=dpi / 72).to_pil()
            buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()
        finally:
            doc.close()
    except Exception:
        return None


def embedded_jpegs(path, min_side=300, limit=200 * 1024 * 1024):
    """PDF 안에 들어 있는 JPEG(DCTDecode) 그림을 파일에 나온 순서대로 돌려준다. 스캔 PDF 는 쪽마다 쪽 크기의 JPEG 하나가 들어 있는 경우가 많아,"""
    import os
    if os.path.getsize(path) > limit: return []
    data = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n", data):
        head = data[max(0, data.rfind(b"obj", 0, m.start())): m.start()]
        if b"/DCTDecode" not in head or b"/Image" not in head: continue
        w = re.search(rb"/Width\s+(\d+)", head); h = re.search(rb"/Height\s+(\d+)", head)
        if not w or not h or min(int(w.group(1)), int(h.group(1))) < min_side: continue
        end = data.find(b"endstream", m.end())
        blob = data[m.end(): end if end > 0 else len(data)]
        i, j = blob.find(b"\xff\xd8\xff"), blob.rfind(b"\xff\xd9")
        if i >= 0 and j > i: out.append(blob[i: j + 2])
    return out


def render_pdf_page(path, page, dpi=110, n_pages=None):
    """PDF 한 쪽을 PNG 바이트로 그린다 (그림 속 코드·실행 화면, 글에서 빠진 수식은 쪽 전체를 보내 AI 가 읽게 한다). poppler 의 pdftoppm 을 먼저 쓰고,"""
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        try:
            subprocess.run([poppler_exe("pdftoppm") or "pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", path, os.path.join(d, "p")],
                           capture_output=True, timeout=60)
            fs = sorted(os.listdir(d))
            if fs: return open(os.path.join(d, fs[0]), "rb").read()
        except (OSError, subprocess.SubprocessError):
            pass
    pic = _render_pdfium(path, page, dpi)
    if pic or not n_pages: return pic
    jp = embedded_jpegs(path)                                  # 쪽마다 그림 하나인 스캔 PDF 만: 쪽 수와 그림 수가 같을 때 순서대로 짝짓는다
    return jp[page - 1] if len(jp) == n_pages and 0 < page <= n_pages else None


_SUB_MARK = re.compile(r"(?m)^[ \t]*\(?(\d{1,2}|[a-z])\)+[ \t]+\S")
_TASK_CUE = re.compile(r"(?:작성|구현|추가|수정|완성|고치|변경|바꾸|채우)[ \t]*(?:하|해)[ \t]*(?:시오|세요|십시오|보세요|라)|오류[가를]?[ \t]*(?:발생|수정)")


def split_subtasks(body):
    """한 문제 안에 '1) … 구현하세요 2) … 작성하세요 3) … 수정하세요' 처럼 코드를 작성·수정하는 소문항이 둘 이상이면 소문항마다 문제 하나로 나눈다."""
    seq = []
    for m in _SUB_MARK.finditer(body):
        lab = m.group(1)
        want = str(len(seq) + 1) if lab.isdigit() else chr(ord("a") + len(seq))
        if lab == want: seq.append(m)
    if len(seq) < 2: return [("", body)]
    ends = [m.start() for m in seq[1:]] + [len(body)]
    parts = [body[m.start():e].strip("\n") for m, e in zip(seq, ends)]
    if sum(1 for p in parts if _TASK_CUE.search(p)) < 2: return [("", body)]
    pre = body[:seq[0].start()].strip("\n")
    return [(f"-{k}", (pre + "\n" + p).strip("\n")) for k, p in enumerate(parts, 1)]


def is_scanned(path, txt=None):
    """글 층이 없는 PDF(스캔·사진으로 만든 문서)인가. pdftotext 가 거의 아무 글도 못 꺼낸 경우."""
    if not path.lower().endswith(".pdf"): return False
    try:
        txt = read_text(path) if txt is None else txt
    except (SystemExit, Exception):
        return False
    return len(norm(txt)) < 20 and txt.count(chr(12)) >= 1


def page_count(txt):
    """pdftotext 가 쪽마다 붙이는 쪽 구분(\\f)의 수."""
    return max(1, txt.count(chr(12)))


_ANS_HEAD_RE = re.compile(r"^[ \t|]*[-•*·]?[ \t]*(?:정답(?:[ \t]*코드)?|해답|모범[ \t]*답안|풀이|해설)[ \t]*[:：]?[ \t]*$")        # "- 정답" 처럼 줄 전체가 정답 구역 머리인 줄
_LONE_NUM_RE = re.compile(r"^[ \t\-–•]*\d{1,3}[ \t.)]*$")                                                  # "-4" 처럼 번호 잔재만 있는 줄
_HEADING_LINE_RE = re.compile(r"^[ \t]*(?:문제[ \t]*\d{1,3}|개념[ \t]*확인|응용(?:[ \t]*문제)?|연습[ \t]*문제|추가[ \t]*문제|기본[ \t]*문제)[ \t]*[.:]?[ \t]*$")                # "문제 2", "개념 확인" 처럼 제목뿐인 줄
_TAG_LINE_RE = re.compile(r"^[ \t]*<[^<>\n]{1,15}>[ \t]*$")                                                  # "<추가문제>" 처럼 구역 표시만 있는 줄


def clean_section(body):
    """원본에서 나눈 문제 조각의 잡음을 걷어낸다. (본문, 문서 안의 정답 구역 또는 None)"""
    lines = str(body or "").split("\n")
    while lines and (not lines[0].strip() or _LONE_NUM_RE.match(lines[0]) or _TAG_LINE_RE.match(lines[0]) or _HEADING_LINE_RE.match(lines[0])): lines.pop(0)
    while lines and (not lines[-1].strip() or _TAG_LINE_RE.match(lines[-1])): lines.pop()
    lines = [re.sub(r"^([ \t]*)[lo][ \t]+(?=[가-힣])", r"\1", l) for l in lines]                     # PDF 가 글머리 기호(●)를 글자 l, o 로 뽑은 줄: "l 멤버 변수를 선언하시오" → "멤버 변수를 선언하시오"
    ans = None
    for k, l in enumerate(lines):
        if k > 0 and _ANS_HEAD_RE.match(l):
            ans = "\n".join(lines[k + 1:]).strip("\n") or None
            lines = lines[:k]
            break
    text = "\n".join(lines).rstrip()
    if len(norm(text)) < 10: return body, None
    return text, ans


def sections(path, id_re=None, label=None):
    """문제 제목 기준으로 나눈다. 목차에도 같은 제목이 있으므로, 같은 ID가 여러 번 나오면 본문이 가장 긴 것을 쓴다."""
    for pid, page, body, _imgs in sections_with_images(path, id_re, label, with_images=False):
        yield pid, page, body


# 수식이 글로 빠진 흔적: 수식 글꼴 전용 코드 문자(사용자 영역) 2개 이상인 줄, 수식 기호만 덩그러니 있는 줄, 기호 앞뒤가 긴 공백인 줄
_MATH = "≤≥≠±√∑∫π∞θ"
LOSSY_LINE_RE = re.compile(r"^.*[-].*[-].*$|^[ \t]*[" + _MATH + r"][ \t]*$|^.*[ \t]{12,}[" + _MATH + r"].*$|^.*[" + _MATH + r"][ \t]{12,}.*$", re.M)
MAX_PAGE_PICS = 3                       # 한 문제에 붙이는 쪽 화면 수


def lossy_lines(text):
    """수식이 글로 빠진 것으로 보이는 줄 목록 (진단·시험용)."""
    return [m.group(0).strip() for m in LOSSY_LINE_RE.finditer(text)]



def sections_with_images(path, id_re=None, label=None, with_images=True):
    """sections 와 같지만 (문제ID, 쪽, 본문, 그림목록) 을 돌려준다. 그림목록은 본문의 [이미지] 와 같은 순서의 그림 파일(바이트, 못 꺼냈으면 None)이다."""
    imgs = [] if with_images else None
    pdf_img_pages = pdf_image_pages(path) if with_images and path.lower().endswith(".pdf") else set()
    txt = read_text(path, imgs)
    ms = marks_of(txt, id_re) or ([] if id_re else heading_marks(txt, file_stem(label or path)))
    if not ms and not id_re and path.lower().endswith(".pptx"): ms = slide_marks(txt, file_stem(label or path))
    best = {}
    for i, (mid, mstart, mend) in enumerate(ms):
        end = ms[i + 1][1] if i + 1 < len(ms) else len(txt)
        body = clean(txt[mend: end])
        page = txt.count("", 0, mend) + 1                       # 제목 앞의 쪽 구분도 세도록 제목 글자가 끝나는 위치 기준
        pics = []
        if with_images and path.lower().endswith(".pdf"):                       # PDF: 그림이 있는 쪽을 통째로 그려 보낸다 (본문에는 [이미지] 표시가 없다)
            last_page = txt.count("", 0, max(end - 1, mend)) + 1
            raw = txt[mend:end]                                                # 수식이 글로 빠진 쪽도 화면을 보낸다 (그림 파일이 없는 PDF 에서 수식이 글꼴 조각으로 그려진 경우)
            lossy = {page + raw[:m.end()].count(chr(12)) for m in LOSSY_LINE_RE.finditer(raw)}      # 줄 끝까지 세야 줄 앞에 붙은 쪽 구분 문자가 포함된다
            want = sorted((pdf_img_pages | lossy) & set(range(page, last_page + 1)))[:MAX_PAGE_PICS]
            pics = [b for b in (render_pdf_page(path, pg) for pg in want) if b]
        elif imgs and len(imgs) == txt.count(IMG_MARK):                      # 표시 개수와 그림 개수가 같을 때만 짝을 믿는다
            first = txt.count(IMG_MARK, 0, mend)
            pics = imgs[first: first + txt.count(IMG_MARK, mend, end)]
            if len(pics) != body.count(IMG_MARK): pics = []                # 정리 중 표시가 지워졌으면 짝이 어긋나므로 쓰지 않는다
        if mid not in best or len(norm(body)) > len(norm(best[mid][1])):
            best[mid] = (page, body, mstart, pics)
    for pid, (page, body, _, pics) in sorted(best.items(), key=lambda kv: kv[1][2]):
        yield pid, page, body, pics


LANG_SIGNS = (("java", r"System\.out|public\s+static\s+void\s+main|\bScanner\s*\(|\bimport\s+java\.|자바"),
              ("cpp", r"#include\s*<iostream>|\bcout\b|\bcin\b|\bclass\s+\w+\s*\{|C\+\+"),
              ("c", r"#include\s*<stdio\.h>|\bprintf\s*\(|\bscanf\s*\("),
              ("javascript", r"console\.log|\bfunction\s+\w+\s*\(|자바스크립트|JavaScript"),
              ("python", r"\bdef\s+\w+\s*\(|\bprint\s*\(|파이썬|Python"))


def language_hint(body):
    """문제지 글에서 프로그래밍 언어를 추정한다. 가장 많이 나타나는 언어(최소 2번)를 돌려주고, 불분명하면 None."""
    counts = {lang: len(re.findall(rx, body)) for lang, rx in LANG_SIGNS}
    if counts["cpp"] and counts["c"] and not re.search(r"#include\s*<stdio\.h>", body): counts["c"] = 0       # printf 는 C++ 에서도 쓴다
    lang, n = max(counts.items(), key=lambda kv: kv[1])
    return lang if n >= 2 and sorted(counts.values())[-2] < n else None


def intake(body):
    notes = []
    n = len(norm(body))
    img = n < 25
    if img: notes.append("본문 텍스트가 거의 없음 → 이미지 문제일 수 있음")
    methods = sorted(set(re.sub(r"\s", "", x) for x in METHOD_RE.findall(body)))
    n_ex = len(set(re.findall(r"입력\s*(\d)", body))) or len(re.findall(r"입출력\s*예", body))
    blank = bool(BLANK_RE.search(body))
    code = has_code(body)
    link = bool(re.search(r"https?://(?!(?:www\.)?(?:trinket\.io|replit\.com|colab\.research\.google\.com|onlinegdb\.com|jdoodle\.com|programiz\.com|pythontutor\.com)\b)|\.mp4", body))      # 실행환경 링크는 제외
    n_img = body.count(IMG_MARK)
    if n_img: notes.append(f"그림 {n_img}개가 있음(내용은 텍스트로 읽히지 않음) → 실행 결과·그림이 이미지로만 있는지 확인 필요")
    if methods: notes.append(f"풀이 방식 표기 {methods} → 문제 분할 후보")
    if link: notes.append("링크/영상이 있음 → 첨부 확인 필요")
    if re.search(r"터틀|turtle|그림과 같이", body, re.I): notes.append("그래픽 출력 가능성 → 테스트 케이스 없음 예상")
    out = {"이미지의심": img, "방식표기": methods, "입출력예수": n_ex, "빈칸표기": blank, "링크": link,
           "유형힌트": hint(body, blank, code), "메모": notes}
    lang = language_hint(body)
    if lang: out["언어힌트"] = lang
    return out
