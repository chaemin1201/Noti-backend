#!/usr/bin/env python3
"""검사를 통과한 문제만 Noti API(POST /inputdata)로 등록하고, 결과를 파일로 남긴다.

사용법
  export NOTI_TOKEN="<로그인 토큰>"
  python register.py 결과.jsonl --url https://서버/inputdata            # 등록
  python register.py 결과.jsonl --url https://서버/inputdata --dry-run  # 보내지 않고 대상만 확인

흐름
  1) protocol_check 로 검사 → FAIL 은 보내지 않고 register_blocked.jsonl 에 저장
  2) 보류(상태=보류) 문제는 보내지 않음
  3) 나머지를 --batch-size 개씩 묶어 POST (인증: Authorization: Bearer 토큰, 가정)
  4) 응답의 created / duplicates / errors 를 문제와 짝지어 register_result.jsonl 에 저장
  5) 오류가 난 문제만 register_retry.jsonl 에 저장 → AI 에게 오류 내용과 함께 다시 보내 고치게 한다
중복 문제는 서버가 건너뛰므로 같은 파일을 다시 실행해도 안전하다.
"""
try:
    import sys as _s; _s.stdout.reconfigure(encoding="utf-8", errors="replace")      # Windows 콘솔(cp949)에서도 이모지 출력
except Exception: pass
import argparse, json, os, sys, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol_check import check_case


def load_cases(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def split_cases(cases, use_check=True):
    """(보낼 것, 막힌 것, 보류) 로 나눈다."""
    seen, send, blocked, hold = {}, [], [], []
    for c in cases:
        if (c.get("review") or {}).get("상태") == "보류" or c.get("payload") is None:
            hold.append(c); continue
        if use_check:
            fails, warns = check_case(c, seen, skip_exec=False)
            if fails:
                blocked.append({**c, "check_fails": fails}); continue
        send.append(c)
    return send, blocked, hold


def http_post(url, token, body):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"요청 실패 HTTP {e.status}: {e.read().decode('utf-8', 'replace')[:300]}")


def register(send, post, batch_size=20):
    """post(body_dict) -> 응답 dict. 문제별 결과 목록을 돌려준다."""
    results = []
    for start in range(0, len(send), batch_size):
        batch = send[start:start + batch_size]
        resp = post({"problems": [c["payload"] for c in batch]})
        created = {x["index"]: x for x in resp.get("created_problems", [])}
        dups = {x["index"]: x for x in resp.get("duplicates", [])}
        errs = {x["index"]: x for x in resp.get("errors", [])}
        for i, c in enumerate(batch, 1):
            if i in created: r = {"result": "created", "problem_id": created[i]["problem_id"]}
            elif i in dups: r = {"result": "duplicate", "existing_problem_id": dups[i]["existing_problem_id"]}
            elif i in errs: r = {"result": "error", "error": errs[i]["error"], "status_code": errs[i].get("status_code")}
            else: r = {"result": "unknown"}          # 응답에 이 문제가 없음 → 사람이 확인
            results.append({"id": c.get("id"), **r, "case": c})
    return results


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--url"); ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--skip-check", action="store_true")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    send, blocked, hold = split_cases(load_cases(a.file), use_check=not a.skip_check)
    print(f"등록 대상 {len(send)} · 검사 불통과 {len(blocked)} · 보류 {len(hold)}")
    for b in blocked: print(f"  ✗ 막힘 {b.get('id')}: {b['check_fails'][0]}")
    flagged = [c for c in send if (c.get("review") or {}).get("확인필요")]
    if flagged:      # 승인 단계: 사람이 훑어보고 문제가 없을 때만 등록하도록 목록을 보여 준다
        print(f"\n[승인 확인] 확인필요가 있는 등록 대상 {len(flagged)}개 — 등록 전에 훑어보세요")
        for c in flagged:
            items = c["review"]["확인필요"]
            print(f"  · {c.get('id')}: {items[0][:60]}" + (f" 외 {len(items) - 1}건" if len(items) > 1 else ""))
        print("  (문제가 있는 것은 입력 파일에서 해당 줄을 빼고 다시 실행하세요. 이미 등록된 문제는 서버가 중복으로 건너뜁니다.)\n")
    write_jsonl(os.path.join(a.out_dir, "register_blocked.jsonl"), blocked)
    if a.dry_run or not send:
        print("(dry-run) 보내지 않았습니다." if a.dry_run else "보낼 문제가 없습니다."); return
    token = os.environ.get("NOTI_TOKEN")
    if not a.url or not token: raise SystemExit("--url 과 환경변수 NOTI_TOKEN 이 필요합니다.")
    results = register(send, lambda body: http_post(a.url, token, body), a.batch_size)
    write_jsonl(os.path.join(a.out_dir, "register_result.jsonl"), results)
    retry = [r for r in results if r["result"] in ("error", "unknown")]
    write_jsonl(os.path.join(a.out_dir, "register_retry.jsonl"), retry)
    cnt = {k: sum(1 for r in results if r["result"] == k) for k in ("created", "duplicate", "error", "unknown")}
    print(f"등록 {cnt['created']} · 중복(건너뜀) {cnt['duplicate']} · 오류 {cnt['error']} · 확인필요 {cnt['unknown']}")
    for r in retry: print(f"  ✗ {r['id']}: {r.get('error', '응답에 없음')}")
    sys.exit(1 if retry else 0)


if __name__ == "__main__":
    main()
