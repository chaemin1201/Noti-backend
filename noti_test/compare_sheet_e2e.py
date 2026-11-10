"""엑셀 원래 값과 AI 변환 결과(run_real_e2e.py 의 --out JSON)를 항목별로 비교한다. AI 호출·코드 실행 없음.

    python compare_sheet_e2e.py 표본.xlsx e2e결과.json

비교 항목: 제목, 유형, 난이도, 설명(마크다운 기호 제거만 허용), 조건(태그 붙이기만 허용), 제공코드, 정답코드, 입력, 기대 출력
판정: 같음 / 공백만 다름 / 다름(내용 표시) / 없음"""
import json, re, sys
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.readers import xlsx_intake
from app.inputdata.intake.checks.fix import has_markdown_bold

sheet_rows = xlsx_intake.read(sys.argv[1])
sheet = {}
_dup = {}
for r in sheet_rows:                                    # 같은 이름이 여러 행이면 AI 결과와 같은 순서로 하나씩 짝짓는다
    k = r["fields"]["이름"].replace("문제 ", "").strip(); sheet.setdefault(k, []).append(r["fields"])
res = json.load(open(sys.argv[2], encoding="utf-8"))
n = lambda s: "\n".join(l.rstrip() for l in (s or "").replace("\r\n", "\n").split("\n")).strip()
loose = lambda s: re.sub(r"\s+", "", s or "")
TAG = re.compile(r"^\[(필수|금지|허용|출력형식)\]\s*")
unbold = lambda s: re.sub(r"(?<![\w)\]*])\*\*(?=[^\s*])(.*?)(?<=[^\s*])\*\*", r"\1", s or "")

def judge(a, b, strip=lambda s: s):
    if b is None or b == "": return "없음" if not a else "다름(원본 비어 있음)"
    if n(strip(a)) == n(strip(b)): return "같음"
    if loose(strip(a)) == loose(strip(b)): return "공백만 다름"
    return "다름"

tot = {}
rows = [it for it in res["items"] if it.get("payload")]
held = [it for it in res["items"] if not it.get("payload")]
print(f"AI 결과 {len(res['items'])}개 (변환됨 {len(rows)}, 보류 {len(held)}) / 표본 {len(sheet)}개\n")
for it in rows:
    p = it["payload"]; key = it["result_id"]
    cand = sheet.get(key) or sheet.get(p.get("title")) or []
    if not cand:                                        # 제목이 줄었으면(예: 'C07_02') 이름의 첫 토큰(ID)으로 찾는다
        tok = re.split(r"[\s-]", key)[0]
        cand = next((v for k, v in sheet.items() if re.split(r"[\s-]", k)[0] == tok), [])
    f = None
    if cand:                                            # 같은 이름이 여럿이면 정답코드가 같은 행을 찾는다 (없으면 순서대로)
        code0 = (p.get("reference_codes") or [{}])[0].get("code", "")
        f = next((c for c in cand if n(c.get("정답코드")) == n(code0)), cand[_dup.setdefault(key, 0) % len(cand)])
        _dup[key] = _dup.get(key, 0) + 1
    if not f:
        print(f"== {key}: 엑셀에서 같은 이름을 찾지 못함 (제목이 바뀌었을 수 있음)"); tot["제목 못 찾음"] = tot.get("제목 못 찾음", 0) + 1; continue
    code = (p.get("reference_codes") or [{}])[0].get("code", ""); base = (p.get("base_code") or [{}])[0].get("code", "")
    tc = (p.get("test_cases") or [{}])[0]
    conds = [TAG.sub("", c) for c in (p.get("problem_condition") or [])]; scond = [TAG.sub("", l.strip()) for l in (f.get("조건") or "").splitlines() if l.strip()]
    checks = {
        "제목": "같음" if p["title"] == f["이름"].replace("문제 ", "").strip() else "다름",
        "유형": "같음" if p["problemType"] == f.get("유형") else f"다름({f.get('유형')}→{p['problemType']})",
        "난이도": "같음" if (p.get("difficulty") or "") == (f.get("난이도") or "").lower() else "다름",
        "설명": judge(p["description"], f.get("설명"), unbold),
        "조건": "같음" if [n(c) for c in conds] == [n(unbold(c)) for c in scond] else "다름",
        "제공코드": judge(base, f.get("제공코드")) if f.get("제공코드") or base else "해당 없음",
        "정답코드": judge(code, f.get("정답코드")),
        "입력": judge(tc.get("input", ""), f.get("입력", "")) if f.get("입력") or tc.get("input") else "해당 없음",
        "기대출력": judge(tc.get("expected_output", ""), f.get("출력")),
    }
    print(f"== {key}  [{it['status']}] md남음={has_markdown_bold(p['description'])}")
    print("   " + " | ".join(f"{k}:{v}" for k, v in checks.items()))
    for k, v in checks.items():
        tot.setdefault(k, {}); tot[k][v.split("(")[0]] = tot[k].get(v.split("(")[0], 0) + 1
        if v.startswith("다름") and k in ("정답코드", "기대출력", "입력", "조건"):
            a = {"정답코드": code, "기대출력": tc.get("expected_output", ""), "입력": tc.get("input", ""), "조건": " / ".join(conds)}[k]
            b = {"정답코드": f.get("정답코드"), "기대출력": f.get("출력"), "입력": f.get("입력"), "조건": " / ".join(scond)}[k]
            print(f"      {k} AI : {n(a)[:110]!r}\n      {k} 엑셀: {n(b)[:110]!r}")
for it in held:
    rv = it.get("review") or {}; print(f"== {it['result_id']}: 보류 — {str(rv.get('보류사유'))[:100]}")
print("\n== 항목별 합계")
for k, v in tot.items(): print(f"   {k}: {v}")
