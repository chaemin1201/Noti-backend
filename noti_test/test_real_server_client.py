"""run_real_server.py (실제 서버의 HTTP API 만 부르는 도구) 시험. 서버 대신 httpx.MockTransport 로 응답을 흉내낸다.
noti_test 폴더에서:  python test_real_server_client.py        (httpx 필요)"""
import contextlib, io, json, os, sys, tempfile
import httpx
import run_real_server as rs

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
ITEMS = [
    {"item_id": 1, "seq": 1, "result_id": "A_01", "source_key": "A_01", "status": "needs_review", "payload": {"problemType": "코딩", "title": "A_01"}, "review": {"확인필요": []}, "approval_reasons": ["정답 코드를 서버에서 실행해 확인하지 않았습니다."], "check_fails": []},
    {"item_id": 2, "seq": 2, "result_id": "A_02", "source_key": "A_02", "status": "held", "payload": None, "review": {"보류사유": "본문을 읽을 수 없음"}, "approval_reasons": [], "check_fails": []},
]
seen = {"calls": [], "polls": 0}

def handler(request):
    path, m = request.url.path, request.method
    seen["calls"].append((m, path, request.headers.get("authorization")))
    if m == "POST" and path == "/intake/jobs":
        body = request.read().decode("utf-8", "replace")
        seen["upload_body"] = body
        return httpx.Response(202, json={"job_id": "11111111-aaaa", "status": "processing", "input_kind": "엑셀", "records_total": 2, "warnings": []})
    if m == "GET" and path == "/intake/jobs/11111111-aaaa":
        seen["polls"] += 1
        done = seen["polls"] >= 2
        return httpx.Response(200, json={"job_id": "11111111-aaaa", "status": "done" if done else "processing", "records_total": 2, "records_done": 2 if done else 1, "counts": {"needs_review": 1, "held": 1}, "message": None})
    if m == "GET" and path == "/intake/jobs/11111111-aaaa/items":
        return httpx.Response(200, json=ITEMS)
    if m == "POST" and path == "/intake/jobs/11111111-aaaa/approve":
        seen["approved"] = True
        return httpx.Response(200, json={"summary": {"registered": 1}, "results": []})
    if m == "POST" and path == "/intake/preview":
        return httpx.Response(200, json={"records": 2, "by_kind": {"엑셀": 2}})
    return httpx.Response(404, json={"detail": "Not Found"})

def go(extra, sleep_patch=True):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try: code = rs.main(["--base-url", "http://srv", "--token", "SECRET-TOKEN-123", "--upload", XL] + extra, transport=httpx.MockTransport(handler))
        except SystemExit as e: code = e.code
    return code, out.getvalue()

with tempfile.TemporaryDirectory() as d:
    XL = os.path.join(d, "문제.csv"); open(XL, "w", encoding="utf-8").write("이름,설명" + NL + "A_01,합")
    OUT = os.path.join(d, "r.json")
    rs.time.sleep = lambda s: None                       # 진행 확인 대기를 건너뜀 (시험 속도)

    print("1. 기본 실행: 올리고, 기다리고, 결과를 저장한다 (등록하지 않음)")
    code, text = go(["--out", OUT])
    check("정상 종료", code == 0, text[-300:])
    check("업로드에 Bearer 토큰이 붙고 auto_register 는 false 로 올라간다 (실제 DB 에 바로 등록되지 않게)", ("POST", "/intake/jobs", "Bearer SECRET-TOKEN-123") in seen["calls"] and "false" in seen["upload_body"], seen["upload_body"][:200])
    check("기본은 승인을 호출하지 않는다", not seen.get("approved") and not any(c[1].endswith("/approve") for c in seen["calls"]))
    check("처리가 끝날 때까지 진행 확인을 반복한다", seen["polls"] >= 2, seen["polls"])
    check("토큰을 화면에 출력하지 않는다", "SECRET-TOKEN-123" not in text)
    check("유형별 개수에 0 인 유형도 나오고 보류 문제는 유형으로 세지 않는다", "객관식 0" in text and "코딩 1" in text and "유형 없음" not in text, text)
    r = json.load(open(OUT, encoding="utf-8"))
    check("결과 JSON 은 run_real_e2e 와 같은 모양이다 (job, before, items) — make_report.py 로 보고서를 만들 수 있다", set(("job", "before", "items")) <= set(r) and len(r["before"]) == 2, list(r))
    import make_report
    html = make_report.build(OUT, os.path.join(d, "r.html"))
    check("그 JSON 으로 보고서가 만들어진다", os.path.getsize(html) > 5000)

    print("2. 옵션")
    seen["calls"].clear(); seen["polls"] = 0; seen.pop("approved", None)
    code, text = go(["--out", OUT, "--approve", "--auto-register"])
    check("--approve 를 주면 승인을 호출한다", seen.get("approved") is True and "승인 결과" in text)
    check("--auto-register 를 주면 true 로 올라간다", "true" in seen["upload_body"])
    seen["calls"].clear()
    code, text = go(["--preview-only"])
    check("--preview-only 는 미리보기만 부르고 작업을 만들지 않는다", code == 0 and [c[:2] for c in seen["calls"]] == [("POST", "/intake/preview")], seen["calls"])

    print("3. 오류 안내")
    code, text = go(["--prefix", "/없는경로", "--out", OUT])
    check("경로가 틀리면(404) --prefix 를 확인하라고 안내한다", code == 1 and "--prefix" in text, text)
    def deny(request): return httpx.Response(401, json={"detail": "x"})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try: rs.main(["--base-url", "http://srv", "--token", "T", "--upload", XL], transport=httpx.MockTransport(deny))
        except SystemExit as e: code = e.code
    check("인증이 실패하면(401) 토큰을 확인하라고 안내한다", code == 1 and "인증 실패" in out.getvalue(), out.getvalue())

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
