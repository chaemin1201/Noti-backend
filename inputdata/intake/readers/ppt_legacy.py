"""구형 파워포인트(.ppt, 97-2003 이진 형식) 읽기: 슬라이드 순서대로 글과 그림을 꺼낸다.

.ppt 는 OLE 복합 파일이고 슬라이드는 8바이트 머리(버전·종류·길이)를 가진 기록의 나무이다. 외부 프로그램(파워포인트·LibreOffice) 없이 olefile 만으로 읽는다.
  - 글: 슬라이드 기록(1006) 안의 TextCharsAtom(4000, UTF-16)·TextBytesAtom(4008), 문서 기록 안의 SlideListWithText(4080)가 가진 제목·본문 자리 글
  - 그림: 슬라이드 안 도형의 그림 번호(pib)를 Pictures 스트림의 그림 목록(FBSE → 위치)에 맞춰 JPEG/PNG 를 꺼낸다. EMF·WMF 등은 None(건너뜀)
  - 못 읽는 것: 발표자 노트(슬라이드와의 짝이 복잡함), 표 안의 글 일부. 슬라이드 순서는 파일에 저장된 순서를 따른다 (여러 번 저장되며 뒤섞인 파일은 어긋날 수 있다)
반환 형식은 pptx_text 와 같다: 슬라이드 사이에 쪽 구분(\\f), 그림 자리는 [이미지], images 리스트에 같은 순서로 그림 파일(못 꺼내면 None)을 채운다.
"""
import struct

IMG_MARK = "[이미지]"
MAX_STREAM = 200 * 1024 * 1024          # 이보다 큰 스트림은 읽지 않는다 (업로드 안전)

T_DOCUMENT, T_SLIDE, T_SLWT, T_PERSIST = 1000, 1006, 4080, 1011
T_CHARS, T_BYTES, T_HEADER, T_TEXTBOX = 4000, 4008, 3999, 4001
T_FOPT, T_FBSE = 0xF00B, 0xF007
PIB = 260                                # 도형 속성: 그림 번호 (1부터, FBSE 순서)


def _records(data, start, end):
    pos = start
    while pos + 8 <= end:
        vi, typ, ln = struct.unpack_from("<HHI", data, pos)
        body = pos + 8
        stop = min(body + ln, end)
        yield vi & 0xF, vi >> 4, typ, body, stop
        pos = body + ln


def _text(data, typ, a, b):
    raw = bytes(data[a:b])
    s = raw.decode("utf-16-le", "replace") if typ == T_CHARS else raw.decode("cp1252", "replace")
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n").replace("\x00", "").strip("\n")


def _walk(data, start, end, items, fbse, depth=0):
    """기록 나무를 돌며 items 에 ("text", 글) / ("pic", 그림번호) 를 나온 순서대로, fbse 에 Pictures 안 위치를 모은다."""
    if depth > 24: return
    for ver, inst, typ, a, b in _records(data, start, end):
        if ver == 0xF:
            _walk(data, a, b, items, fbse, depth + 1)
        elif typ in (T_CHARS, T_BYTES):
            t = _text(data, typ, a, b)
            if t.strip(): items.append(("text", t))
        elif typ == T_FOPT and b - a >= 6 * inst:
            for i in range(inst):
                opid, val = struct.unpack_from("<HI", data, a + 6 * i)
                if opid & 0x3FFF == PIB and opid & 0x4000 and val: items.append(("pic", val))
        elif typ == T_FBSE and b - a >= 36:
            fbse.append(struct.unpack_from("<I", data, a + 28)[0])


def _slwt_texts(data, a, b):
    """SlideListWithText: 슬라이드마다 제목·본문 자리 글 목록 (SlidePersistAtom 이 슬라이드 경계)."""
    slides, cur = [], None
    for ver, inst, typ, x, y in _records(data, a, b):
        if typ == T_PERSIST:
            cur = []; slides.append(cur)
        elif typ in (T_CHARS, T_BYTES) and cur is not None:
            t = _text(data, typ, x, y)
            if t.strip(): cur.append(t)
    return slides


def _blip(pictures, off):
    """Pictures 스트림의 off 위치에서 JPEG/PNG 그림 바이트. 다른 형식이면 None."""
    if pictures is None or off < 0 or off + 8 > len(pictures): return None
    vi, typ, ln = struct.unpack_from("<HHI", pictures, off)
    if typ not in (0xF01D, 0xF01E, 0xF02A): return None
    body = pictures[off + 8: off + 8 + ln]
    for sig in (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"):
        i = body.find(sig, 0, 64)
        if i >= 0: return bytes(body[i:])
    return None


def ppt_text(path, images=None):
    try:
        import olefile
    except ImportError:
        raise SystemExit(".ppt 를 읽으려면 olefile (pip install olefile) 이 필요합니다. 또는 파워포인트에서 .pptx 로 저장해 올려 주세요.")
    if not olefile.isOleFile(path): raise SystemExit("파워포인트(.ppt) 형식이 아닙니다. 파워포인트에서 .pptx 로 다시 저장해 올려 주세요.")
    with olefile.OleFileIO(path) as ole:
        if not ole.exists("PowerPoint Document"): raise SystemExit("파워포인트(.ppt) 형식이 아닙니다. 파워포인트에서 .pptx 로 다시 저장해 올려 주세요.")
        if ole.get_size("PowerPoint Document") > MAX_STREAM: raise SystemExit("파워포인트 파일이 너무 커서 처리할 수 없습니다.")
        doc = ole.openstream("PowerPoint Document").read()
        pictures = ole.openstream("Pictures").read() if ole.exists("Pictures") and ole.get_size("Pictures") <= MAX_STREAM else None
    return parse(doc, pictures, images)


def parse(doc, pictures=None, images=None):
    """PowerPoint Document 스트림(bytes) → 글. (시험에서 OLE 파일 없이 바로 쓸 수 있게 분리)"""
    fbse, slwt, slides = [], [], []
    for ver, inst, typ, a, b in _records(doc, 0, len(doc)):
        if typ == T_DOCUMENT and ver == 0xF:
            items = []
            _walk(doc, a, b, items, fbse)
            for v2, i2, t2, x, y in _records(doc, a, b):
                if t2 == T_SLWT and i2 == 0: slwt = _slwt_texts(doc, x, y)
        elif typ == T_SLIDE and ver == 0xF:
            items = []
            _walk(doc, a, b, items, fbse)
            slides.append(items)
    out = []
    for i, items in enumerate(slides):
        lines, seen = [], set()
        for t in (slwt[i] if i < len(slwt) else []):                     # 제목·본문 자리 글이 먼저
            lines.append(t); seen.add(t.strip())
        for kind, v in items:
            if kind == "text":
                if v.strip() in seen: continue                           # 같은 글이 두 곳에 있으면 한 번만
                lines.append(v); seen.add(v.strip())
            else:
                lines.append(" " + IMG_MARK)
                if images is not None:
                    images.append(_blip(pictures, fbse[v - 1]) if 0 < v <= len(fbse) else None)
        out.append("\n".join(lines).strip("\n"))
    return "\n\f".join(out)
