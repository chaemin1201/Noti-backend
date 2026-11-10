"""AI 를 부르지 않고 문제지가 문제로 어떻게 나뉘는지만 본다 (문제 수, 경계, 그림, 이상 징후). API 키가 필요 없다.

noti_test 폴더에서:  python preview_parse.py 파일1 [파일2 ...] [--pattern '문제\\s+(\\S+)'] [--limit 50]
표(.xlsx/.csv/.db) 와 원본(.pdf/.docx/.pptx/.hwp/.txt …)을 함께 줄 수 있다."""
import os, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import parsing


def main(argv):
    files, pattern, limit = [], None, None
    it = iter(argv)
    for a in it:
        if a == "--pattern": pattern = next(it, None)
        elif a == "--limit": limit = int(next(it, "0")) or None
        else: files.append(a)
    if not files:
        print(__doc__); return 2
    tables, originals, bad = [], [], []
    for f in files:
        if not os.path.isfile(f): bad.append(f"파일이 없습니다: {f}"); continue
        k = parsing.kind_of(os.path.basename(f))
        if k == "table": tables.append(f)
        elif k == "original": originals.append(f)
        else: bad.append(f"지원하지 않는 형식입니다: {os.path.basename(f)}")
    for b in bad: print("⚠", b)
    if not tables and not originals: return 2
    try:
        kind, recs = parsing.build_records(tables, originals, pattern, [os.path.basename(p) for p in originals], table_labels=[os.path.basename(p) for p in tables])
    except parsing.IntakeInputError as e:
        print("❌", e); return 2
    print(parsing.format_text(parsing.preview_of(kind, recs), limit))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
