"""한글 문서(.hwp / .hwpx)를 본문 순서대로 텍스트로 만든다. (pdf_intake.read_text 가 부른다)"""
import re
import struct
import zipfile
import zlib
from xml.etree import ElementTree as ET

from . import images as safety      # 업로드 파일 안전 점검(images.py 안)

IMG_MARK = "[이미지]"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- 자동 번호 (hwp·hwpx 공통)
_HANGUL = "가나다라마바사아자차카타파하"
_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLED_HANGUL = "㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻"


def _roman(n):
    out = ""
    for v, r in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += r; n -= v
    return out


def _fmt_num(n, kind):
    """번호 n 을 형식(kind)대로 글자로. 모르는 형식은 숫자."""
    def pick(chars):
        return chars[n - 1] if 1 <= n <= len(chars) else str(n)
    k = (kind or "DIGIT").upper()
    if k == "LATIN_CAPITAL": return chr(64 + n) if 1 <= n <= 26 else str(n)
    if k == "LATIN_SMALL": return chr(96 + n) if 1 <= n <= 26 else str(n)
    if k == "ROMAN_SMALL": return _roman(n)
    if k == "ROMAN_CAPITAL": return _roman(n).upper()
    if k == "HANGUL_SYLLABLE": return pick(_HANGUL)
    if k == "HANGUL_JAMO": return pick(_JAMO)
    if k == "CIRCLED_DIGIT": return pick(_CIRCLED)
    if k == "CIRCLED_HANGUL_SYLLABLE": return pick(_CIRCLED_HANGUL)
    return str(n)


class _AutoNumber:
    """번호 서식 id → {수준(1부터): (형식, 문구, 시작값)}. 문단마다 label() 을 부르면 번호를 세어 글자로 돌려준다."""

    def __init__(self, formats):
        self.formats, self.count = formats, {}

    def label(self, num_id, level):
        heads = self.formats.get(num_id)
        if not heads or level not in heads: return ""
        _, pat, start = heads[level]
        if "^N" in pat: return ""                              # 개요·쪽 번호 같은 특수 문구
        if not re.search(r"\^[1-7]", pat): return "-" if pat.strip() else ""
        c = self.count.setdefault(num_id, {})
        c[level] = c.get(level, start - 1) + 1
        for deeper in [k for k in c if k > level]: del c[deeper]       # 하위 수준은 다시 시작

        def sub(m):
            lv = int(m.group(1)); h = heads.get(lv)
            return _fmt_num(c.get(lv, h[2] if h else 1), h[0] if h else "DIGIT")
        return re.sub(r"\^([1-7])", sub, pat)


# ---------------------------------------------------------------- .hwpx
def _hwpx_numbering(z):
    """header.xml 에서 (번호 세기 도구, 문단 모양 id → (종류, 번호서식 id, 수준)). 없으면 None."""
    try:
        root = ET.fromstring(z.read("Contents/header.xml"))
    except (KeyError, ET.ParseError):
        return None
    kinds, formats = {}, {}
    for el in root.iter():
        n = _local(el.tag)
        if n == "paraPr":
            h = next((c for c in el if _local(c.tag) == "heading"), None)
            if h is not None and h.get("type") in ("NUMBER", "BULLET"):
                kinds[el.get("id")] = (h.get("type"), h.get("idRef"), int(h.get("level") or 0) + 1)
        elif n == "numbering":
            formats[el.get("id")] = {int(ph.get("level")): (ph.get("numFormat") or "DIGIT", ph.text or "", int(ph.get("start") or 1))
                                     for ph in el if _local(ph.tag) == "paraHead"}
    return (_AutoNumber(formats), kinds) if kinds else None


def _hwpx_run_text(t):
    """<hp:t> 안의 글자. 탭·줄바꿈은 자식 요소로 들어 있다."""
    out = [t.text or ""]
    for c in t:
        n = _local(c.tag)
        if n == "tab": out.append("\t")
        elif n in ("lineBreak", "lineBreakEx"): out.append("\n")
        out.append(c.tail or "")
    return "".join(out)


def _hwpx_para(p, sink, depth, num=None, ctx=None):
    """문단 하나 → sink 에 줄 추가. 문단 안의 표는 문단 글자 다음 줄에 풀어 쓴다."""
    text, tables = [], []
    lab = ""
    if num:
        auto, kinds = num
        k = kinds.get(p.get("paraPrIDRef"))
        if k: lab = "-" if k[0] == "BULLET" else auto.label(k[1], k[2])      # 빈 문단도 번호는 센다

    def walk(el):
        for c in el:
            n = _local(c.tag)
            if n == "t": text.append(_hwpx_run_text(c))
            elif n == "tbl": tables.append(c)
            elif n in ("pic", "ole", "video"):
                text.append(" " + IMG_MARK)
                if ctx is not None: ctx[1].append(_hwpx_image(ctx[0], c) if n == "pic" else None)
            elif n == "equation":
                s = next((x.text for x in c.iter() if _local(x.tag) == "script"), "")
                if s: text.append(s.strip())
            elif n in ("run", "ctrl", "rect", "container", "drawText", "subList"):
                walk(c)                                   # 글상자(drawText) 안 글자도 이어서 읽는다
    walk(p)
    line = "".join(text).replace("\xa0", " ").rstrip()
    if lab and line.strip(): line = lab + " " + line
    if line or not tables: sink.append(line)
    for t in tables:
        if depth < 3: _hwpx_table(t, sink, depth + 1, num, ctx)


def _hwpx_table(tbl, sink, depth, num=None, ctx=None):
    for tr in (c for c in tbl if _local(c.tag) == "tr"):
        cells = []
        for tc in (c for c in tr if _local(c.tag) == "tc"):
            lines = []
            for sub in (c for c in tc if _local(c.tag) == "subList"):
                for p in (c for c in sub if _local(c.tag) == "p"):
                    _hwpx_para(p, lines, depth, num, ctx)
            cells.append("\n".join(lines).rstrip())
        sink.append(cells[0] if len(cells) == 1 else "   ".join(x.replace("\n", " ") for x in cells))


def _hwpx_image(z, pic):
    """<hp:pic> 가 가리키는 그림 파일(BinData/<참조>.<확장자>)의 바이트. 없으면 None."""
    ref = next((x.get("binaryItemIDRef") for x in pic.iter() if _local(x.tag) == "img" and x.get("binaryItemIDRef")), None)
    if not ref: return None
    name = next((n for n in z.namelist() if re.match(r"BinData/" + re.escape(ref) + r"(\.\w+)?$", n)), None)
    return z.read(name) if name else None


def hwpx_text(path, images=None):
    safety.check_zip(path)
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if not names: raise SystemExit("hwpx 문서에서 본문(Contents/section*.xml)을 찾지 못했습니다.")
        num = _hwpx_numbering(z)
        out = []
        for n in names:
            root = ET.fromstring(z.read(n))
            for p in (c for c in root if _local(c.tag) == "p"):
                _hwpx_para(p, out, 0, num, (z, images) if images is not None else None)
            out.append("\f")                              # 구역 경계를 페이지 경계처럼 표시
    return "\n".join(out).rstrip("\f\n")


# ---------------------------------------------------------------- .hwp (5.0 바이너리)
TAG_NUMBERING = 23           # HWPTAG_BEGIN(16) + 7   (DocInfo)
TAG_PARA_SHAPE = 25          # HWPTAG_BEGIN(16) + 9   (DocInfo)
TAG_PARA_HEADER = 66         # HWPTAG_BEGIN(16) + 50
TAG_PARA_TEXT = 67           # HWPTAG_BEGIN(16) + 51
TAG_CTRL_HEADER = 71         # HWPTAG_BEGIN(16) + 55
TAG_SHAPE_PICTURE = 85       # HWPTAG_BEGIN(16) + 69   (그림 개체: 71바이트째에 BinData 번호)
TAG_EQEDIT = 88              # HWPTAG_BEGIN(16) + 72
_EXT_CTRL = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}       # 확장 컨트롤: 8 WCHAR 차지
_INLINE_CTRL = {4, 5, 6, 7, 8, 9, 19, 20}                          # 인라인 컨트롤: 8 WCHAR 차지 (9 = 탭)
_HWP_NUMFMT = {0: "DIGIT", 1: "CIRCLED_DIGIT", 2: "ROMAN_CAPITAL", 3: "ROMAN_SMALL", 4: "LATIN_CAPITAL", 5: "LATIN_SMALL",
               8: "HANGUL_SYLLABLE", 9: "CIRCLED_HANGUL_SYLLABLE", 10: "HANGUL_JAMO"}


def _records(data):
    i, n = 0, len(data)
    while i + 4 <= n:
        h, = struct.unpack_from("<I", data, i); i += 4
        tag, level, size = h & 0x3FF, (h >> 10) & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            size, = struct.unpack_from("<I", data, i); i += 4
        yield tag, level, data[i:i + size]
        i += size


def _para_text(b):
    out, i, n = [], 0, len(b) // 2
    while i < n:
        ch, = struct.unpack_from("<H", b, i * 2)
        if ch >= 32:
            out.append(chr(ch)); i += 1
        elif ch in _EXT_CTRL or ch in _INLINE_CTRL:
            if ch == 9: out.append("\t")
            elif ch == 11:                                # 그리기 개체·표. 컨트롤 ID 가 뒤집혀 들어 있다 ('gso ' = 그림·도형)
                cid = b[i * 2 + 2: i * 2 + 6][::-1].decode("latin-1", "replace")
                if cid == "gso ": out.append(" " + IMG_MARK)
            i += 8
        else:
            if ch == 10: out.append("\n")
            elif ch in (24, 30, 31): out.append("-" if ch == 24 else " ")
            i += 1
    return "".join(out)


def _hwp_numbering_record(b):
    """NUMBERING 레코드 → {수준: (형식, 문구, 시작값)}. 수준마다 머리 정보 12바이트 + 문구(WORD 길이 + UTF-16) 가 7번 이어진다."""
    heads, i = {}, 0
    for level in range(1, 8):
        if i + 14 > len(b): break
        attr, = struct.unpack_from("<I", b, i); i += 12            # 속성 4 + 너비 보정 2 + 본문과의 거리 2 + 글자 모양 4
        ln, = struct.unpack_from("<H", b, i); i += 2
        pat = b[i:i + ln * 2].decode("utf-16-le", "replace"); i += ln * 2
        heads[level] = [_HWP_NUMFMT.get((attr >> 5) & 0xF, "DIGIT"), pat, 1]
    if i + 2 + 28 <= len(b):                                       # 5.0.2.5 이상: 수준별 시작 번호 UINT32 x 7 (앞에 UINT16 하나)
        for level, st in enumerate(struct.unpack_from("<7I", b, i + 2), 1):
            if level in heads and st < 1000: heads[level][2] = st
    return {k: tuple(v) for k, v in heads.items()}


def _hwp_numbering(ole, compressed):
    """DocInfo 에서 (번호 세기 도구, 문단 모양 목록[(머리 종류, 번호서식 번호, 수준)]). 읽을 수 없으면 None."""
    try:
        data = ole.openstream("DocInfo").read()
        if compressed: data = safety.inflate(data)
        formats, shapes = {}, []
        for tag, _lv, body in _records(data):
            if tag == TAG_NUMBERING:
                formats[len(formats) + 1] = _hwp_numbering_record(body)       # 번호 서식 번호는 1부터
            elif tag == TAG_PARA_SHAPE and len(body) >= 32:
                attr, = struct.unpack_from("<I", body, 0); numid, = struct.unpack_from("<H", body, 30)
                shapes.append(((attr >> 23) & 3, numid, ((attr >> 25) & 7) + 1))  # 머리 종류 0 없음 1 개요 2 번호 3 글머리표
            else:
                if tag == TAG_PARA_SHAPE: shapes.append((0, 0, 1))
        return (_AutoNumber(formats), shapes) if any(s[0] in (2, 3) for s in shapes) else None
    except Exception:
        return None                                                          # 번호를 못 읽어도 글자는 그대로 읽는다


def _bin_items(ole, compressed):
    """BinData/BIN000N.확장자 → {번호: 그림 바이트}. 번호는 16진수 4자리이다. 압축되어 있으면 풀고, 풀 수 없으면 원본 그대로 쓴다."""
    out = {}
    for e in ole.listdir():
        m = len(e) == 2 and e[0] == "BinData" and re.match(r"BIN([0-9A-Fa-f]{4})\.\w+$", e[1])
        if not m: continue
        raw = ole.openstream(e).read()
        data = raw
        if compressed:
            try: data = safety.inflate(raw, 50 * 1024 * 1024)
            except (zlib.error, safety.UnsafeFile): data = raw
        out[int(m.group(1), 16)] = data
    return out


def hwp_text(path, images=None):
    """images: 리스트를 주면 본문의 [이미지] 와 같은 순서로 그림 파일(바이트, 못 찾으면 None)을 채운다."""
    try:
        import olefile
    except ImportError:
        raise SystemExit("hwp 를 읽으려면 olefile (pip install olefile) 이 필요합니다. 또는 한글에서 hwpx·PDF 로 저장해 올려 주세요.")
    if not olefile.isOleFile(path): raise SystemExit("hwp 파일 형식이 아닙니다. (HWP 3.0 등 옛 형식은 한글에서 다시 저장해 올려 주세요)")
    with olefile.OleFileIO(path) as ole:
        header = ole.openstream("FileHeader").read()
        flags, = struct.unpack_from("<I", header, 36)
        if flags & 0x02: raise SystemExit("암호가 걸린 hwp 문서는 읽을 수 없습니다. 암호를 풀고 다시 올려 주세요.")
        if flags & 0x04 or not ole.exists("BodyText/Section0"):
            raise SystemExit("배포용 hwp 문서는 읽을 수 없습니다. 한글에서 PDF 로 저장해 올려 주세요.")
        compressed = bool(flags & 0x01)
        num = _hwp_numbering(ole, compressed)
        secs = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
                      key=lambda e: int(e[1][7:] or 0))
        out = []
        bins = _bin_items(ole, compressed) if images is not None else {}
        for e in secs:
            data = ole.openstream(e).read()
            if compressed: data = safety.inflate(data)
            pending = ""
            queues, cur = {}, None                 # 문단 수준별로 아직 짝을 못 찾은 그림 자리, 지금 읽는 그림 컨트롤의 자리
            for tag, _lv, body in _records(data):
                if tag == TAG_CTRL_HEADER and images is not None:
                    cur = None
                    if body[:4][::-1] == b"gso " and queues.get(_lv): cur = queues[_lv].pop(0)       # 같은 문단의 글(PARA_TEXT)에서 센 그림 자리 (컨트롤은 글과 같은 수준)
                elif tag == TAG_SHAPE_PICTURE and images is not None and cur is not None and len(body) >= 73:
                    images[cur] = bins.get(struct.unpack_from("<H", body, 71)[0])
                if tag == TAG_PARA_HEADER:
                    pending = ""
                    if num and len(body) >= 10:
                        auto, shapes = num
                        sid, = struct.unpack_from("<H", body, 8)
                        if sid < len(shapes):
                            kind, numid, level = shapes[sid]
                            if kind == 3: pending = "-"
                            elif kind == 2: pending = auto.label(numid, level)     # 빈 문단도 번호는 센다
                elif tag == TAG_PARA_TEXT:
                    t = _para_text(body).replace("\xa0", " ").rstrip()
                    if images is not None:
                        for _ in range(t.count(IMG_MARK)):
                            queues.setdefault(_lv, []).append(len(images)); images.append(None)
                    if pending and t.strip(): t = pending + " " + t
                    pending = ""
                    out.append(t)
                elif tag == TAG_EQEDIT and len(body) >= 6:
                    ln, = struct.unpack_from("<H", body, 4)
                    out.append(body[6:6 + ln * 2].decode("utf-16-le", "replace").strip())
            out.append("\f")
    return "\n".join(out).rstrip("\f\n")
