#!/usr/bin/env python3
"""실제로 실행 중인 서버에 파일을 올려 결과를 보는 도구 (noti_test 의 가짜 앱·임시 DB 를 쓰지 않는다).

run_real_e2e.py 는 이 PC 에서 가짜 로그인과 임시 DB 로 서버 코드를 직접 돌린다. 이 도구는 이미 떠 있는 서버(개발·스테이징)의 HTTP API 만 부른다:
  업로드(POST /intake/jobs) → 진행 확인(GET /intake/jobs/{id}) → 문제별 결과(GET /intake/jobs/{id}/items) → (선택) 승인
결과는 run_real_e2e.py 와 같은 JSON 으로 저장하므로 make_report.py 로 같은 보고서를 만들 수 있다.

안전
  - 기본은 등록하지 않는다: auto_register=false 로 올리고 승인(--approve)도 하지 않는다. 서버 DB 에는 intake_job·intake_item 만 생기고 문제 테이블은 그대로다.
  - 서버의 AI 키를 쓰므로 문제 수만큼 AI 호출 비용이 든다. 처음에는 --preview-only 로 문제 수만 확인하세요 (AI 호출 없음).
  - 토큰은 화면에 출력하지 않는다.

사용법 (PowerShell)
  $env:NOTI_TOKEN = "로그인으로 받은 액세스 토큰"
  python run_real_server.py --base-url http://localhost:8000 --preview-only --upload 문제.xlsx
  python run_real_server.py --base-url http://localhost:8000 --upload 문제.xlsx 과제.docx --out 서버결과.json
  python make_report.py 서버결과.json 서버결과.html
주소 앞부분이 다르면 --prefix 로 맞춘다 (기본 /intake, 서버에서 router 를 prefix 와 함께 연결했다면 예: /inputdata/intake).
인증 방식이 Bearer 토큰이 아니면 --header "이름: 값" 을 여러 번 줄 수 있다.
"""
import argparse, json, mimetypes, os, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TYPES = ("코딩", "디버깅", "객관식", "단답형", "주관식")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="실제 서버에 문제지를 올려 결과를 본다")
    ap.add_argument("--base-url", required=True, help="서버 주소 (예: http://localhost:8000)")
    ap.add_argument("--prefix", default="/intake", help="intake 라우터의 경로 (기본 /intake)")
    ap.add_argument("--token", default=os.environ.get("NOTI_TOKEN", ""), help="액세스 토큰 (기본: 환경변수 NOTI_TOKEN)")
    ap.add_argument("--header", action="append", default=[], help='추가 헤더 "이름: 값" (여러 번 가능)')
    ap.add_argument("--upload", nargs="+", required=True, help="올릴 파일들")
    ap.add_argument("--mode", default="none", help="채점 모드 (기본 none)")
    ap.add_argument("--preview-only", action="store_true", help="AI 를 부르지 않고 문제로 나눈 결과만 본다")
    ap.add_argument("--auto-register", action="store_true", help="검사를 통과한 문제를 바로 등록 (기본 꺼짐: 실제 DB 에 문제가 들어간다)")
    ap.add_argument("--approve", action="store_true", help="처리가 끝나면 승인 가능한 문제를 모두 승인해 등록 (실제 DB 에 문제가 들어간다)")
    ap.add_argument("--wait", type=int, default=900, help="처리 완료를 기다릴 최대 초 (기본 900)")
    ap.add_argument("--out", default="서버결과.json")
    ap.add_argument("--timeout", type=int, default=120, help="요청 하나의 제한 시간(초)")
    return ap.parse_args(argv)


def headers_of(args):
    h = {}
    if args.token: h["Authorization"] = "Bearer " + args.token
    for x in args.header:
        if ":" in x:
            k, v = x.split(":", 1); h[k.strip()] = v.strip()
    return h


def fail(msg):
    print("오류:", msg); raise SystemExit(1)


def check(r, what):
    if r.status_code in (401, 403):
        fail(f"{what}: 인증 실패({r.status_code}). 토큰이 맞는지, 만료되지 않았는지 확인하세요.")
    if r.status_code == 404:
        fail(f"{what}: 404. --prefix 를 확인하세요 (서버에서 intake 라우터를 연결한 경로). 지금: 요청 주소 {r.request.url}")
    if r.status_code >= 400:
        fail(f"{what}: {r.status_code} {r.text[:300]}")
    return r


def files_of(paths):
    out = []
    for p in paths:
        if not os.path.isfile(p): fail(f"파일이 없습니다: {p}")
        out.append(("files", (os.path.basename(p), open(p, "rb").read(), mimetypes.guess_type(p)[0] or "application/octet-stream")))
    return out


def run(client, args):
    base = args.prefix.rstrip("/")
    files = files_of(args.upload)
    print(f"서버: {args.base_url}{base}   파일 {len(files)}개   등록: {'승인까지 함' if args.approve else ('통과분 바로 등록' if args.auto_register else '하지 않음')}")
    if args.preview_only:
        r = check(client.post(base + "/preview", files=files), "미리보기")
        pv = r.json()
        print(json.dumps(pv, ensure_ascii=False, indent=1)[:3000])
        return 0
    t0 = time.time()
    r = check(client.post(base + "/jobs", files=files, data={"mode": args.mode, "auto_register": "true" if args.auto_register else "false"}), "업로드")
    up = r.json(); job = up["job_id"]
    print(f"1. 업로드 완료: 작업 {job[:8]}… 문제 {up['records_total']}개, 입력 종류 {up['input_kind']}")
    for w in up.get("warnings") or []: print("   ⚠", w)
    last = None
    j = {}
    while time.time() - t0 < args.wait:
        j = check(client.get(f"{base}/jobs/{job}"), "진행 확인").json()
        cur = (j.get("records_done"), j.get("status"))
        if cur != last:
            print(f"   진행 {j.get('records_done')}/{j.get('records_total')} · {j.get('status')} · {j.get('counts')}"); last = cur
        if j.get("status") != "processing": break
        time.sleep(3)
    else:
        print(f"   {args.wait}초 안에 끝나지 않았습니다. 서버에서 계속 처리 중일 수 있으니 GET {base}/jobs/{job} 로 확인하세요.")
    print(f"2. 처리 {j.get('status')} · 소요 {time.time() - t0:.0f}초 · 상태별 {j.get('counts')}")
    if j.get("message"): print("   작업 메시지:", j["message"])
    items, off = [], 0
    while True:
        page = check(client.get(f"{base}/jobs/{job}/items", params={"limit": 200, "offset": off, "with_record": "true"}), "결과 조회").json()
        items += page
        if len(page) < 200: break
        off += 200
    tc = {t: 0 for t in TYPES}
    for it in items:
        t = (it.get("payload") or {}).get("problemType")
        if t: tc[t] = tc.get(t, 0) + 1          # 보류 문제는 유형이 정해지지 않았으므로 유형별 개수에 넣지 않는다
    print("   유형별 개수:", " · ".join(f"{k} {v}" for k, v in tc.items()))
    print("3. 문제별 결과")
    for it in items:
        p = it.get("payload") or {}
        print(f"   [{it['status']:12}] {str(it.get('result_id') or it.get('source_key')):22} {p.get('problemType') or ''}")
        for m in (it.get("approval_reasons") or [])[:2]: print("        · 승인 이유:", str(m)[:100])
        if (it.get("review") or {}).get("보류사유"): print("        ⏸ 보류사유:", str(it["review"]["보류사유"])[:130])
        for m in (it.get("check_fails") or [])[:2]: print("        ✗ 검사 실패:", str(m)[:130])
    after = items
    if args.approve:
        ap_ = check(client.post(f"{base}/jobs/{job}/approve", json={"all": True}), "승인").json()
        print("4. 승인 결과:", ap_.get("summary"))
        after = check(client.get(f"{base}/jobs/{job}/items", params={"limit": 200}), "결과 조회").json()
    json.dump({"job": j, "before": items, "items": after, "registered": [], "seconds": round(time.time() - t0, 1)}, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("결과 저장:", os.path.abspath(args.out), "  → python make_report.py", args.out)
    return 0


def main(argv=None, transport=None):
    args = parse_args(argv)
    import httpx
    if not args.token and not args.header:
        print("주의: 토큰이 없습니다. 인증이 필요한 서버라면 NOTI_TOKEN 환경변수나 --token 을 주세요.")
    with httpx.Client(base_url=args.base_url, headers=headers_of(args), timeout=args.timeout, transport=transport) as client:
        return run(client, args)


if __name__ == "__main__":
    sys.exit(main())
