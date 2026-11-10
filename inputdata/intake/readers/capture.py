# app/inputdata/intake/readers/capture.py
"""원본 캡처: 올린 문서를 쪽 이미지로 만들어, 문제마다 그 문제가 있는 쪽의 이미지를 짝지어 준다 (승인 화면 왼쪽에 '원본 그대로' 보여 주기 위해).

  PDF                       → 그대로 쪽 이미지로 (poppler pdftoppm 또는 pypdfium2)
  워드·PPT·한글 (.docx .pptx .ppt .hwp .hwpx) → LibreOffice 로 PDF 로 바꾼 뒤 쪽 이미지로 (LibreOffice 가 없으면 건너뜀: 읽은 글로 대신 보여 줌)
  엑셀·csv·md·txt          → 캡처하지 않는다 (엑셀은 열 값 표, 글 파일은 글 그대로 보여 주는 것이 낫다)

문제 ↔ 쪽 짝짓기: 문제 원문(원본조각)의 첫 줄·끝 줄을 쪽마다의 글에서 찾는다 (문서에는 믿을 만한 쪽 번호가 없다).
캡처는 AI 처리와 따로(백그라운드) 만든다. 이 파일은 동기 함수이므로 호출하는 쪽에서 스레드로 돌린다."""
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import pdf_intake

SUPPORTED = (".pdf", ".docx", ".pptx", ".ppt", ".hwp", ".hwpx")
MAX_SPAN = 3                              # 한 문제에 붙이는 쪽 수 (문제가 여러 쪽에 걸쳐도 앞 3쪽까지)
JPEG_MAX = (1000, 1400)


def _c(s):
    return re.sub(r"\s+", "", str(s or ""))


def soffice_exe():
    """LibreOffice 실행 파일 경로. 환경변수 LIBREOFFICE_PATH, PATH, 윈도우의 흔한 설치 위치 순. 없으면 None."""
    p = os.environ.get("LIBREOFFICE_PATH")
    if p and os.path.exists(p): return p
    for n in ("soffice", "libreoffice"):
        w = shutil.which(n)
        if w: return w
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if os.path.exists(p): return p
    return None


def to_pdf(path, outdir, timeout=120):
    """문서를 PDF 로. PDF 는 그대로, 변환 도구가 없거나 실패하면 None."""
    if path.lower().endswith(".pdf"): return path
    exe = soffice_exe()
    if not exe: return None
    profile = Path(os.path.join(outdir, "lo_profile")).as_uri()          # 다른 LibreOffice 와 설정 폴더가 부딪히지 않게
    try:
        subprocess.run([exe, "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation={profile}", "--convert-to", "pdf", "--outdir", outdir, path],
                       capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    out = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + ".pdf")
    return out if os.path.exists(out) else None


def pages_text(pdf):
    """PDF 의 쪽마다의 글 목록. 읽을 수 없으면 빈 목록."""
    try:
        t = pdf_intake.read_text(pdf)
    except (SystemExit, Exception):
        return []
    parts = t.split(chr(12))
    if parts and not parts[-1].strip(): parts = parts[:-1]
    return parts


def find_pages(text, ptexts, max_span=MAX_SPAN):
    """문제 원문 text 가 있는 쪽 번호 목록 (1부터). 첫 줄들이 처음 나오는 쪽부터 끝 줄들이 나오는 쪽까지 (최대 max_span 쪽). 못 찾으면 []."""
    lines = [l for l in (_c(x) for x in str(text or "").split("\n")) if len(l) >= 8]
    if not lines or not ptexts: return []
    pc = [_c(t) for t in ptexts]
    start = None
    for ln in lines[:3]:
        for i, t in enumerate(pc):
            if ln[:30] in t: start = i if start is None else min(start, i); break
        if start is not None: break
    if start is None: return []
    end = start
    for ln in reversed(lines[-3:]):
        for i in range(len(pc) - 1, start - 1, -1):
            if ln[-30:] in pc[i]: end = max(end, i); break
    end = min(end, start + max_span - 1)
    return list(range(start + 1, end + 2))


def jpeg_of(pdf, page, dpi=100, n_pages=None):
    """PDF 한 쪽을 JPEG 바이트로 (가로·세로 최대 1000×1400). 그릴 수 없으면 None."""
    png = pdf_intake.render_pdf_page(pdf, page, dpi=dpi, n_pages=n_pages)
    if not png: return None
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail(JPEG_MAX)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=72, optimize=True)
    return buf.getvalue()


def capture(files, records, max_pages=40, dpi=100, render=None):
    """files: [(표시 이름, 확장자(.docx), 바이트)], records: 문제 레코드 목록. render 는 시험용으로 jpeg_of 를 바꿔 끼우는 자리.
    {"status": "done|none|unsupported", "captures": [{"file","page","mime","data"}], "map": {문제 key: [{"file","page"}]}, "unsupported": [표시 이름]}"""
    render = render or jpeg_of
    unsupported, docs = [], []
    with tempfile.TemporaryDirectory() as d:
        for i, (label, ext, data) in enumerate(files):
            ext = (ext or "").lower()
            if ext not in SUPPORTED: continue
            src = os.path.join(d, f"f{i}{ext}")
            with open(src, "wb") as fh: fh.write(data)
            pdf = to_pdf(src, d)
            if not pdf: unsupported.append(label); continue
            docs.append((label, pdf, pages_text(pdf)))
        if not docs:
            return {"status": "unsupported" if unsupported else "none", "captures": [], "map": {}, "unsupported": unsupported}
        want, rec_pages = [], {}                                  # want: 그릴 (파일, 쪽) 순서, rec_pages: 문제 → [(파일, 쪽)]
        pdf_labels = {l for l, e, _ in files if (e or "").lower() == ".pdf"}
        only_pdf = [x for x in docs if x[0] in pdf_labels]                                  # 올린 파일 중 PDF 인 것
        for rec in records:
            hit = None
            for label, pdf, texts in docs:
                pg = find_pages(rec.get("원본조각"), texts)
                if pg: hit = (label, pg); break
            if not hit and rec.get("원본형식") == "PDF" and len(only_pdf) == 1:             # 글을 못 찾은 PDF(스캔 등)는 레코드가 아는 쪽 번호를 쓴다
                try: hit = (only_pdf[0][0], [int(rec.get("page"))])
                except (TypeError, ValueError): hit = None
            if not hit: continue
            keyed = [(hit[0], p) for p in hit[1]]
            rec_pages[str(rec.get("key"))] = keyed
            for k in keyed:
                if k not in want: want.append(k)
        per_file, done, captures = {}, {}, []
        pdfs = {label: (pdf, len(texts) or None) for label, pdf, texts in docs}
        for label, page in want:
            if per_file.get(label, 0) >= max_pages: continue
            pdf, n = pdfs[label]
            jpg = render(pdf, page, dpi, n)
            if not jpg: continue
            per_file[label] = per_file.get(label, 0) + 1
            done[(label, page)] = True
            captures.append({"file": label, "page": page, "mime": "image/jpeg", "data": jpg})
    mp = {}
    for key, ks in rec_pages.items():
        got = [{"file": f, "page": p} for f, p in ks if done.get((f, p))]
        if got: mp[key] = got
    return {"status": "done" if captures else "none", "captures": captures, "map": mp, "unsupported": unsupported}
