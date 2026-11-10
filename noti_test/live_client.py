"""떠 있는 개발 서버(dev_server.py)에 파일을 올려 끝까지 확인하는 클라이언트 (테스트 전용).
curl 은 윈도우에서 한글 파일 이름을 UTF-8 로 보내지 않아 서버에 깨져 도착하므로 이 도구로 올린다.

    python live_client.py 파일1 [파일2 …] [--port 8765] [--wait 900] [--approve] [--out 결과.json]
"""
import argparse, json, mimetypes, os, sys, time
import httpx

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="+"); ap.add_argument("--port", type=int, default=8765); ap.add_argument("--wait", type=int, default=900)
ap.add_argument("--approve", action="store_true"); ap.add_argument("--out")
a = ap.parse_args()
MIME = {".pdf": "application/pdf", ".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip", ".csv": "text/csv",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
base = f"http://127.0.0.1:{a.port}"
files = [("files", (os.path.basename(p), open(p, "rb").read(), MIME.get(os.path.splitext(p)[1].lower()) or mimetypes.guess_type(p)[0] or "application/octet-stream")) for p in a.files]
c = httpx.Client(base_url=base, timeout=120)
r = c.post("/intake/jobs", files=files)
print("업로드:", r.status_code, r.text[:300])
if r.status_code != 202: sys.exit(1)
job = r.json()["job_id"]
t0 = time.time()
while time.time() - t0 < a.wait:
    j = c.get(f"/intake/jobs/{job}").json()
    if j["status"] in ("done", "paused", "failed"): break
    time.sleep(10)
print("작업 상태:", j["status"], j.get("counts"), "|", j.get("message") or "")
items = c.get(f"/intake/jobs/{job}/items").json()
for it in items:
    p = it.get("payload") or {}; rv = it.get("review") or {}
    print(f"[{it['status']:12s}] {str(it.get('result_id'))[:40]:40s} {p.get('problemType') or '-':4s} 테스트 {len(p.get('test_cases') or [])} 조건 {len(p.get('problem_condition') or [])}"
          f" | 난이도 {p.get('difficulty')} 태그 {p.get('tags')}")
    for x in it.get("approval_reasons") or []: print("      · 승인 이유:", str(x)[:100])
    for x in rv.get("확인필요") or []: print("      ? 확인필요:", str(x)[:110])
    if rv.get("보류사유"): print("      ⏸ 보류:", str(rv["보류사유"])[:110])
    for x in it.get("check_fails") or []: print("      ✗ 검사 실패:", str(x)[:110])
    if it.get("error"): print("      ! 오류:", it["error"])
if a.approve:
    print("승인:", c.post(f"/intake/jobs/{job}/approve", json={"all": True}).json().get("summary"))
if a.out: json.dump({"job": j, "items": items}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("저장:", a.out)
