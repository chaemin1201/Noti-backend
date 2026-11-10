"""AI 결과 두 벌(프롬프트·모델·설정을 바꾸기 전/후)을 문제별로 비교한다. AI 를 부르지 않는다.

noti_test 폴더에서:  python compare_runs.py 이전.jsonl 이후.jsonl [--show 20]
파일 형식(줄마다 JSON, 둘 다 가능):
  · run_ai_tests.py --save 로 남긴 {"test":"T1","text":"AI 출력 전체"}
  · {"id":"…","payload":{…}|null,"review":{…}}   (golden_cases.jsonl 과 같은 모양)
  · 서버 GET /intake/jobs/{id}/items 를 저장한 JSON 목록 ({"result_id","status","payload","review"} 들)
같은 키(test 또는 id)끼리 짝지어 상태·확인필요·채움·형식 실패·항목 변화를 보여 주고, 나빠진 것(후퇴)을 먼저 나열한다."""
import json, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.llm import parse_lines

FIELDS = ("problemType", "title", "description", "difficulty", "tags", "rating_mode", "problem_condition", "test_cases",
          "reference_codes", "base_code", "options", "correct_answers", "answer_text")


def _row(d, key=None):
    """한 줄 → {"key","rows":[{id,payload,review}]}. 못 읽으면 rows 가 비어 있다 (형식 실패)."""
    if "text" in d and ("test" in d or "id" not in d):
        rows = parse_lines(d.get("text") or "")[0]
        return d.get("test") or key, rows
    if "result_id" in d:
        return d["result_id"], [{"id": d["result_id"], "payload": d.get("payload"), "review": d.get("review") or {}}]
    if "id" in d:
        return d["id"], [d]
    return key, []


def load(path):
    """{키: [결과 행...]} (같은 키가 여러 줄·여러 번 실행이면 이어 붙인다)"""
    raw = open(path, encoding="utf-8").read().strip()
    items = []
    if raw.startswith("["):
        items = json.loads(raw)
    else:
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln:
                try: items.append(json.loads(ln))
                except ValueError: items.append({"text": ln})
    out = {}
    for it in items:
        k, rows = _row(it)
        out.setdefault(k, []).extend(rows)
        if not rows: out[k] = out.get(k, [])
    return out


def _status(rows):
    if not rows: return "형식실패"
    st = {(r.get("review") or {}).get("상태") or ("보류" if r.get("payload") is None else "등록가능") for r in rows}
    return "보류" if "보류" in st else "등록가능"


def _count(rows, name):
    return sum(len((r.get("review") or {}).get(name) or []) for r in rows)


def summarize(res):
    keys = list(res)
    st = [_status(res[k]) for k in keys]
    return {"문제": len(keys), "등록가능": st.count("등록가능"), "보류": st.count("보류"), "형식실패": st.count("형식실패"),
            "확인필요 합계": sum(_count(res[k], "확인필요") for k in keys), "채움 합계": sum(_count(res[k], "채움") for k in keys),
            "조언 합계": sum(_count(res[k], "조언") for k in keys), "확인필요 있는 문제": sum(1 for k in keys if _count(res[k], "확인필요"))}


def diff_one(a_rows, b_rows):
    """(후퇴 목록, 변화 목록)"""
    bad, note = [], []
    sa, sb = _status(a_rows), _status(b_rows)
    if sa != sb:
        (bad if (sa == "등록가능" and sb != "등록가능") or sb == "형식실패" else note).append(f"상태 {sa} → {sb}")
    if not a_rows or not b_rows: return bad, note
    if len(a_rows) != len(b_rows): note.append(f"결과 줄 수 {len(a_rows)} → {len(b_rows)} (방식 분할 차이?)")
    pa, pb = (a_rows[0].get("payload") or {}), (b_rows[0].get("payload") or {})
    for f in FIELDS:
        va, vb = pa.get(f), pb.get(f)
        if va == vb: continue
        if va not in (None, "", [], {}) and vb in (None, "", [], {}): bad.append(f"{f} 가 비었다")
        elif va in (None, "", [], {}) and vb not in (None, "", [], {}): note.append(f"{f} 가 새로 채워졌다")
        elif f == "description": bad.append("description 이 달라졌다 (원문 보존 확인)")
        elif f in ("test_cases", "reference_codes"): note.append(f"{f} 내용이 달라졌다")
        else: note.append(f"{f}: {str(va)[:40]} → {str(vb)[:40]}")
    ca, cb = _count(a_rows, "확인필요"), _count(b_rows, "확인필요")
    if cb > ca: bad.append(f"확인필요 {ca} → {cb}")
    elif cb < ca: note.append(f"확인필요 {ca} → {cb}")
    return bad, note


def main(argv):
    show, files, it = 30, [], iter(argv)
    for a in it:
        if a == "--show": show = int(next(it, "30"))
        else: files.append(a)
    if len(files) != 2:
        print(__doc__); return 2
    A, B = load(files[0]), load(files[1])
    sa, sb = summarize(A), summarize(B)
    print(f"{'':<16}{'이전':>8}{'이후':>8}")
    for k in sa: print(f"{k:<16}{sa[k]:>8}{sb[k]:>8}{'  ←' if sa[k] != sb[k] else ''}")
    common = [k for k in A if k in B]
    only_a, only_b = [k for k in A if k not in B], [k for k in B if k not in A]
    if only_a: print(f"\n이전에만 있음: {only_a[:10]}")
    if only_b: print(f"이후에만 있음: {only_b[:10]}")
    regress, changed = [], []
    for k in common:
        bad, note = diff_one(A[k], B[k])
        if bad: regress.append((k, bad))
        elif note: changed.append((k, note))
    print(f"\n비교한 문제 {len(common)}개: 후퇴 {len(regress)} / 변화만 있음 {len(changed)} / 같음 {len(common) - len(regress) - len(changed)}")
    if regress:
        print("\n[후퇴 — 먼저 확인]")
        for k, bad in regress[:show]: print(f"  {k}: " + "; ".join(bad))
    if changed:
        print("\n[변화]")
        for k, note in changed[:show]: print(f"  {k}: " + "; ".join(note))
    return 1 if regress else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
