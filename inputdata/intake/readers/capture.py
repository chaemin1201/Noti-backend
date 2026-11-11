# app/inputdata/intake/readers/capture.py
"""원본 캡처: 올린 문서를 쪽 이미지로 만들어, 문제마다 그 문제가 있는 쪽의 이미지를 짝지어 준다 (승인 화면 왼쪽에 '원본 그대로' 보여 주기 위해)."""
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import pdf_intake

SUPPORTED = (".pdf", ".docx", ".pptx", ".ppt", ".hwp", ".hwpx")
MAX_SPAN = 4                              # 한 문제에 붙이는 쪽 수 (문제가 여러 쪽에 걸쳐도 앞 4쪽까지)
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


def _start_page(lines, pc):
    """문제의 첫 줄들이 처음 나오는 쪽 번호(0부터)와 그 쪽 글 안의 위치. 못 찾으면 (None, 0)."""
    for ln in lines[:3]:
        for i, t in enumerate(pc):
            k = t.find(ln[:30])
            if k >= 0: return i, k
    return None, 0


def find_pages(text, ptexts, max_span=MAX_SPAN, next_text=None):
    """문제 원문 text 가 있는 쪽 번호 목록 (1부터). 첫 줄이 처음 나오는 쪽부터 끝 줄이 나오는 쪽까지 (최대 max_span 쪽). 못 찾으면 []."""
    lines = [l for l in (_c(x) for x in str(text or "").split(chr(10))) if len(l) >= 8]
    if not lines or not ptexts: return []
    pc = [_c(t) for t in ptexts]
    start, _ = _start_page(lines, pc)
    if start is None: return []
    last = min(len(pc) - 1, start + max_span - 1)
    end = start
    for ln in reversed(lines[-5:]):                                        # 끝 줄들: 줄 끝 또는 줄 앞부분이 나오는 가장 뒤쪽
        hit = [i for i in range(start, last + 1) if ln[-30:] in pc[i] or ln[:30] in pc[i]]
        if hit: end = max(end, hit[-1]); break
    nxt = [l for l in (_c(x) for x in str(next_text or "").split(chr(10))) if len(l) >= 8]
    if nxt and end == start:                                               # 끝 줄이 첫 쪽에서만 보이면, 다음 문제가 뒤쪽에서 시작하는지로 한 번 더 판단
        ns, pos = _start_page(nxt, pc)
        if ns is not None and ns > start:
            end = max(end, ns if pos > 40 else ns - 1)
    end = min(end, last)
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
    """files: [(표시 이름, 확장자(.docx), 바이트)], records: 문제 레코드 목록. render 는 시험용으로 jpeg_of 를 바꿔 끼우는 자리."""
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
        for n, rec in enumerate(records):
            hit = None
            nxt = records[n + 1].get("원본조각") if n + 1 < len(records) else None          # 다음 문제가 시작하는 쪽이 이 문제의 끝 단서
            for label, pdf, texts in docs:
                pg = find_pages(rec.get("원본조각"), texts, next_text=nxt)
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
