"""문서 속 그림을 AI 에 보낼 수 있는 모양으로 준비한다.

코드·실행 결과를 그림(스크린샷)으로 넣은 문제지가 많다. 읽기 코드가 그림 파일을 문서 순서대로 꺼내 오면 여기서 AI 가 받는 형식(PNG/JPEG)으로
바꾸고 크기를 줄인다. 한 문제에 붙이는 그림 수와 크기는 제한한다(DB 와 요청 크기). 못 쓰는 그림(EMF 등)은 건너뛰고 그 사실을 알린다.
Pillow(pip install pillow)가 있으면 BMP·GIF 도 PNG 로 바꾸고 큰 그림을 줄인다. 없으면 PNG/JPEG 만 쓴다.
"""
import base64, io, os, zipfile, zlib

MAX_IMAGES = 8                 # 한 문제에 붙일 그림 수
MAX_SIDE = 1600                # 긴 변 픽셀 (글자를 읽을 수 있는 크기)
MAX_BYTES = 1_200_000          # 그림 하나의 크기
MAX_TOTAL = 4_000_000          # 한 문제에 붙이는 그림 전체 크기
MAX_PIXELS = 50_000_000         # 이보다 큰 그림은 열지 않는다 (작은 파일이 풀리면 거대해지는 그림 폭탄 방지)
JOB_BUDGET = 60_000_000         # 한 작업의 모든 문제에 붙이는 그림 전체 크기(글자 수). DB 에 같이 저장되므로 제한한다. INTAKE_MAX_JOB_IMAGE_MB 로 바꾼다


def sniff(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"): return "image/gif"
    if b[:2] == b"BM": return "image/bmp"
    return None


def prepare(blob):
    """(mime, 바이트) 또는 None(쓸 수 없는 그림)."""
    if not blob: return None
    mime = sniff(blob)
    if not mime: return None
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    except ImportError:
        return (mime, blob) if mime in ("image/png", "image/jpeg", "image/webp") and len(blob) <= MAX_BYTES else None
    try:
        im = Image.open(io.BytesIO(blob)); im.load()
        if max(im.size) > MAX_SIDE:
            im.thumbnail((MAX_SIDE, MAX_SIDE))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO(); im.save(out, "PNG", optimize=True)
        data = out.getvalue()
        if len(data) > MAX_BYTES:                      # 사진처럼 PNG 가 너무 크면 JPEG 로
            out = io.BytesIO(); im.convert("RGB").save(out, "JPEG", quality=85); data = out.getvalue(); mime = "image/jpeg"
            if len(data) > MAX_BYTES: return None
        else:
            mime = "image/png"
        return mime, data
    except Exception:
        return None


def shrink(att, side=900, keep=4):
    """attach() 가 만든 목록을 더 작게 만든다: 앞에서 keep 장만, 긴 변 side 픽셀로. 그림이 많아 AI 가 오래 생각하다 연결이 끊길 때 다시 보내는 용도이다.
    n(원본의 [이미지] 번호)은 그대로 둔다. Pillow 가 없으면 장 수만 줄인다."""
    out = []
    for im in att[:keep]:
        try:
            from PIL import Image
            raw = Image.open(io.BytesIO(base64.b64decode(im["b64"]))); raw.load()
            raw.thumbnail((side, side))
            buf = io.BytesIO(); raw.save(buf, "PNG", optimize=True)
            out.append({"n": im["n"], "mime": "image/png", "b64": base64.b64encode(buf.getvalue()).decode("ascii")})
        except Exception:
            out.append(im)
    return out


def attach(blobs):
    """문서에서 꺼낸 그림 목록(없는 자리는 None)을 AI 에 붙일 목록으로 만든다.
    돌려주는 값: ([{"n": 문제 안 번호(1부터), "mime", "b64"}], [메모]).  n 은 원본조각의 [이미지] 를 나온 순서대로 센 번호이다."""
    out, notes, total = [], [], 0
    for i, blob in enumerate(blobs, 1):
        if blob is None: continue
        p = prepare(blob)
        if p is None:
            notes.append(f"[이미지] {i}번은 AI 가 읽을 수 없는 형식이라 붙이지 못했습니다"); continue
        if len(out) >= MAX_IMAGES or total + len(p[1]) > MAX_TOTAL:
            notes.append(f"[이미지] {i}번은 그림이 너무 많거나 커서 붙이지 못했습니다"); continue
        total += len(p[1])
        out.append({"n": i, "mime": p[0], "b64": base64.b64encode(p[1]).decode("ascii")})
    return out, notes


def job_budget():
    """한 작업이 그림에 쓸 수 있는 전체 용량(글자 수)."""
    v = os.environ.get("INTAKE_MAX_JOB_IMAGE_MB")
    try: return int(float(v) * 1_000_000) if v else JOB_BUDGET
    except ValueError: return JOB_BUDGET


# ====================================================================================================
# 업로드 파일 안전 점검
# 업로드된 파일을 열기 전의 안전 점검: 압축 폭탄(작은 파일이 풀리면 거대해지는 것)을 막는다.
#
# 사용자가 올린 파일은 믿을 수 없다. docx·pptx·hwpx·xlsx 는 zip 이고 .hwp 는 zlib 으로 압축된 조각이라, 풀 때 크기를 제한하지 않으면
# 몇 MB 파일이 수 GB 메모리를 쓰게 만들 수 있다. 한도는 환경변수로 바꾼다 (INTAKE_MAX_UNZIPPED_MB, 기본 300).
# ====================================================================================================

class UnsafeFile(SystemExit):
    """사용자에게 그대로 안내할 수 있는 거절 사유 (parsing 이 IntakeInputError 로 바꿔 준다)."""


def _limit_mb():
    try: return max(10, int(os.environ.get("INTAKE_MAX_UNZIPPED_MB", "300")))
    except ValueError: return 300


def check_zip(path):
    """zip 계열 파일(docx, pptx, hwpx, xlsx)의 풀린 크기·항목 수·압축비를 풀기 전에 점검한다. 문제가 있으면 UnsafeFile."""
    cap = _limit_mb() * 1024 * 1024
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        raise UnsafeFile("파일이 손상되었거나 올바른 형식이 아닙니다.")
    if len(infos) > 5000: raise UnsafeFile("파일 안의 항목이 너무 많아 처리할 수 없습니다.")
    if sum(i.file_size for i in infos) > cap or any(i.file_size > cap // 2 for i in infos):
        raise UnsafeFile(f"압축을 풀면 {_limit_mb()}MB 를 넘어 처리할 수 없습니다.")
    if any(i.file_size > 5 * 1024 * 1024 and i.compress_size and i.file_size / i.compress_size > 200 for i in infos):
        raise UnsafeFile("압축 비율이 비정상적으로 높은 파일이라 처리할 수 없습니다.")


def inflate(data, limit=None):
    """raw deflate(zlib wbits=-15) 를 풀되 결과가 limit 바이트를 넘으면 UnsafeFile. 한글(.hwp)의 압축 조각용."""
    limit = limit or _limit_mb() * 1024 * 1024
    d = zlib.decompressobj(-15)
    out = d.decompress(data, limit + 1)
    if len(out) > limit or d.unconsumed_tail:
        raise UnsafeFile(f"한글 문서가 풀리면 {_limit_mb()}MB 를 넘어 처리할 수 없습니다.")
    return out


def read_text_file(path, limit=50 * 1024 * 1024):
    """텍스트 파일을 글로 읽는다. 인코딩을 순서대로 시도한다: UTF-16(BOM), UTF-8(BOM 포함), CP949(한국어 윈도우 메모장 기본), 그래도 안 되면 깨진 글자는 바꿔서 읽는다.
    한국어 윈도우에서 저장한 .txt/.csv 는 CP949 인 경우가 흔해서, UTF-8 로만 읽으면 올리자마자 오류가 난다."""
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit: raise UnsafeFile("텍스트 파일이 너무 큽니다.")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try: return data.decode("utf-16")
        except UnicodeDecodeError: pass
    for enc in ("utf-8-sig", "cp949"):
        try: return data.decode(enc)
        except UnicodeDecodeError: continue
    return data.decode("utf-8", "replace")
