"""엑셀 문제 목록의 '정답코드(전체 코드)'를 실제로 실행해서 '기대 출력(예상 출력)'과 맞는지 본다. AI 호출 없음.

    python verify_sheet_codes.py --dir "엑셀 폴더" [--only c,cpp] [--limit 5] [--timeout 10] [--out 결과.json]

안전장치 (Windows 에서는 자원 제한을 걸 수 없으므로 아래로 대신한다)
- 문제마다 새 임시 폴더에서 실행하고 끝나면 지운다. 컴파일 30초, 실행 --timeout 초(기본 10) 제한. 서버 환경변수(키 등)는 넘기지 않는다.
- 파일 삭제·프로세스 생성·네트워크 같은 위험한 호출이 보이면 실행하지 않고 '건너뜀'으로 따로 목록을 보여 준다.
- 사용자 폴더의 원본 엑셀은 읽기만 한다.
판정: 일치 / 공백만 다름 / 입력 섞임 보정 후 일치 / 불일치 / 컴파일 실패 / 실행 오류 / 시간 초과 / 건너뜀(위험 호출) / 실행 환경 없음"""
import argparse, collections, json, os, re, shutil, subprocess, sys, tempfile
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.readers import xlsx_intake

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True); ap.add_argument("--only", default=""); ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--timeout", type=int, default=10); ap.add_argument("--out", default="verify_result.json")
args = ap.parse_args()
FILES = [("c 문제 정리.xlsx", "c"), ("cpp 문제 정리.xlsx", "cpp"), ("java 문제 정리.xlsx", "java"), ("javascript 문제 정리.xlsx", "javascript"), ("파이썬 문제 정리.xlsx", "python")]
only = {x.strip() for x in args.only.split(",") if x.strip()}

DANGER = re.compile(r"""\bsystem\s*\(|\bpopen\b|\bexec[lv]p?e?\s*\(|\bfork\s*\(|os\.system|os\.popen|os\.remove|os\.unlink|os\.rmdir|os\.rename|subprocess|shutil|rmtree|\bsocket\b|
                        urllib|requests|http\.|https\.|\bremove\s*\(|\bunlink\s*\(|\brmdir\s*\(|Runtime\.getRuntime|ProcessBuilder|child_process|fs\.(unlink|rm|rmdir|rename|writeFile|appendFile)|
                        Files\.(delete|move|write)|\.delete\s*\(|ServerSocket|new\s+URL\s*\(|import\s+ctypes|__import__|eval\s*\(\s*input""", re.X)


def safe_env():
    env = {"PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}
    for k in ("PATH", "SystemRoot", "SYSTEMROOT", "windir", "TEMP", "TMP", "COMSPEC", "PATHEXT", "JAVA_HOME"):
        if os.environ.get(k): env[k] = os.environ[k]
    return env


def run(cmd, cwd, stdin, timeout):
    try:
        r = subprocess.run(cmd, input=(stdin or "").encode("utf-8"), capture_output=True, cwd=cwd, env=safe_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", "시간 초과"
    return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), r.stderr.decode("utf-8", "replace").replace("\r\n", "\n")


def norm(s): return "\n".join(l.rstrip() for l in (s or "").replace("\r\n", "\n").split("\n")).rstrip("\n")
def loose(s): return re.sub(r"\s+", "", s or "")


def strip_echo(stdin, expected):
    """기대 출력에서 '프롬프트 바로 뒤에 붙은 입력값'을 지운다 (콘솔 화면을 옮긴 데이터 보정)."""
    out = expected or ""
    for v in [l.strip() for l in (stdin or "").splitlines() if l.strip()]:
        out = re.sub(r"((?:>>|:|>|\?)[ \t]*)" + re.escape(v) + r"([ \t]*(?:\r?\n|$))", r"\1\2", out)
    return out


def execute(lang, code, stdin, timeout):
    d = tempfile.mkdtemp(prefix="vsc_")
    try:
        def w(name, text): open(os.path.join(d, name), "w", encoding="utf-8", newline="").write(text)
        if lang == "python":
            w("main.py", code); return run([sys.executable, "-I", "-X", "utf8", "main.py"], d, stdin, timeout)
        if lang in ("c", "cpp"):
            cc, ext = ("gcc", "c") if lang == "c" else ("g++", "cpp")
            if not shutil.which(cc): return "환경", "", f"{cc} 없음"
            w("main." + ext, code); rc, o, e = run([cc, "main." + ext, "-o", "a.exe"], d, "", 30)
            if rc != 0: return "컴파일", "", (e or o)[:300]
            return run([os.path.join(d, "a.exe")], d, stdin, timeout)
        if lang == "java":
            if not shutil.which("javac"): return "환경", "", "javac 없음"
            m = re.search(r"public\s+(?:final\s+|abstract\s+)?class\s+(\w+)", code)
            name = m.group(1) if m else (re.search(r"class\s+(\w+)[^{]*\{[^}]*?static\s+void\s+main", code, re.S) or re.search(r"class\s+(\w+)", code) or [None, "Main"])[1]
            w(name + ".java", code); rc, o, e = run(["javac", "-encoding", "UTF-8", name + ".java"], d, "", 60)
            if rc != 0: return "컴파일", "", (e or o)[:300]
            return run(["java", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-cp", ".", name], d, stdin, timeout)
        if lang == "javascript":
            if not shutil.which("node"): return "환경", "", "node 없음"
            w("main.js", code); return run(["node", "main.js"], d, stdin, timeout)
        return "환경", "", "지원하지 않는 언어"
    finally:
        shutil.rmtree(d, ignore_errors=True)


results = []
for fname, lang in FILES:
    if only and lang not in only: continue
    rows = xlsx_intake.read(os.path.join(args.dir, fname))
    if args.limit: rows = rows[:args.limit]
    for r in rows:
        f = r["fields"]; code = f.get("정답코드") or ""; exp = f.get("출력") or ""; stdin = f.get("입력") or ""
        rec = {"file": lang, "name": f.get("이름"), "type": f.get("유형")}
        if not code: rec["판정"] = "정답코드 없음"
        elif DANGER.search(code): rec["판정"] = "건너뜀(위험 호출)"; rec["호출"] = DANGER.search(code).group(0)[:30]
        else:
            rc, out, err = execute(lang, code, stdin, args.timeout)
            if rc == "환경": rec["판정"] = "실행 환경 없음"; rec["메모"] = err
            elif rc == "컴파일": rec["판정"] = "컴파일 실패"; rec["메모"] = err
            elif rc is None: rec["판정"] = "시간 초과"
            elif rc != 0 and not out.strip(): rec["판정"] = "실행 오류"; rec["메모"] = (err.strip().splitlines() or ["?"])[-1][:160]
            elif norm(out) == norm(exp): rec["판정"] = "일치"
            elif loose(out) == loose(exp): rec["판정"] = "공백만 다름"
            elif stdin and loose(out) == loose(strip_echo(stdin, exp)): rec["판정"] = "입력 섞임 보정 후 일치"
            else:
                rec["판정"] = "불일치"
                a, b = norm(out).split("\n"), norm(exp).split("\n")
                i = next((k for k in range(max(len(a), len(b))) if (a[k] if k < len(a) else None) != (b[k] if k < len(b) else None)), 0)
                rec["첫 차이"] = {"줄": i + 1, "실제": (a[i] if i < len(a) else "(없음)")[:70], "기대": (b[i] if i < len(b) else "(없음)")[:70]}
        results.append(rec); print(f"  {lang:10} {str(rec['name'])[:34]:34} {rec['판정']}", flush=True)

print("\n== 요약")
tot = collections.Counter(r["판정"] for r in results); print("전체", len(results), dict(tot))
for lang in dict.fromkeys(r["file"] for r in results):
    c = collections.Counter(r["판정"] for r in results if r["file"] == lang); print(f"  {lang:10}", dict(c))
bad = [r for r in results if r["판정"] not in ("일치", "공백만 다름", "입력 섞임 보정 후 일치")]
print(f"\n== 확인이 필요한 {len(bad)}개")
for r in bad[:40]:
    extra = r.get("첫 차이") or r.get("메모") or r.get("호출") or ""
    print(f"  [{r['file']}] {r['name']}: {r['판정']} {extra}")
json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n저장:", os.path.abspath(args.out))
