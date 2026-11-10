"""문제 하나를 AI 에 여러 번 보내 원본 출력의 모양을 보는 진단 도구 (실제 AI 를 부른다). 같은 문제가 실행마다 다르게 나오는 이유를 볼 때 쓴다.
사용법:  python diag_one.py 파일 문제ID [횟수]      예: python diag_one.py "과제.docx" C++_08_03 5"""
import json, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
from app.inputdata.intake import service, parsing, llm, config

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
path, key = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
import os
kind, recs = parsing.build_records(path if path.lower().endswith((".xlsx", ".csv")) else None, [] if path.lower().endswith((".xlsx", ".csv")) else [path], labels=[os.path.basename(path)])
rec = next(r for r in recs if r["key"] == key)
print("입력 레코드:", rec["원본형식"] if "원본형식" in rec else rec.get("표형식"), "| 원본조각", len(rec.get("원본조각") or ""), "자 | 그림", len(rec.get("이미지") or []), "장 | 유형힌트", (rec.get("intake") or {}).get("유형힌트"))
ai, model = service._default_ai()
for k in range(n):
    user = parsing.user_text(rec)
    info = {}
    text = ai(user, rec.get("이미지") or None, info)
    rows, bad = llm.parse_lines(text)
    print(f"--- 시도 {k + 1}: 줄 {len(rows)}개, 읽지 못한 줄 {len(bad)}개, 출력 {len(text)}자")
    for r in rows:
        p = r.get("payload")
        rv = r.get("review") or {}
        if p is None: print("   보류:", (rv.get("보류사유") or "")[:150]); continue
        print("   id:", r.get("id"), "| 유형:", p.get("problemType"), "| 키:", sorted(p), "| base_code 줄:", len(((p.get("base_code") or [{}])[0].get("code") or "").splitlines()) if p.get("base_code") else 0,
              "| 정답코드 줄:", len(((p.get("reference_codes") or [{}])[0].get("code") or "").splitlines()) if p.get("reference_codes") else 0, "| 테스트:", len(p.get("test_cases") or []))
    if bad: print("   읽지 못한 줄 앞부분:", [b[:60] for b in bad][:2])
