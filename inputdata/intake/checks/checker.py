#!/usr/bin/env python3
"""프로토콜 출력 검사기."""
import json, os, re, shutil, subprocess, sys, tempfile
import logging
from pydantic import ValidationError
from app.inputdata.schemas import problem_adapter, format_validation_errors     # 프로젝트의 실제 스키마로 검사한다
from app.inputdata.dedupe import compute_content_hash                            # 서버 중복 방지와 같은 규칙
from . import fix
from .fix import echo_warnings, has_markdown_bold

logger = logging.getLogger(__name__)

TAGS = ("필수", "금지", "허용", "출력형식")
COND_RE = re.compile(r"^\[(%s)\]\s*\S" % "|".join(TAGS))


def collapse(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _nz(s):
    s = str(s or "")
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u02bc", "'")):
        s = s.replace(a, b)
    return re.sub(r"[\s.,\u3002]+", "", s)          # 공백과 마침표·쉼표 차이는 무시 (엑셀이 문장 끝에 마침표를 붙이는 경우 등. parsing 의 대조와 같은 기준)


def _src_lines(text):
    out = []
    for l in str(text or "").splitlines():
        l = re.sub(r"^[\s\-\u2022\u00b7*]+", "", l.strip())
        if len(_nz(l)) >= 3: out.append(l)
    return out


def norm_out(s):
    return "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").split("\n")).rstrip("\n")


def _limits(managed_runtime=False):
    """자식 프로세스 제한 (POSIX). 시간 5초, 메모리 512MB, 파일 쓰기 1MB, 프로세스 새로 만들기 금지."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, ((15, 15) if managed_runtime else (5, 5)))
        if not managed_runtime:
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
        os.setsid()
    except Exception:
        pass


# Python: 프로세스·네트워크·파일 삭제/쓰기·동적 실행. 교육용 입출력 프로그램에는 필요 없다. (격리 환경이 막아 주지만, 그 앞에서 한 번 더 거른다)
_PY_DANGER_RE = re.compile(r"""\b(?:import|from)\s+(?:subprocess|socket|ctypes|shutil|importlib|multiprocessing|urllib|http|requests|pickle|marshal|ftplib|smtplib|telnetlib|webbrowser|pty|signal|resource|threading|asyncio|builtins)\b|__import__|\bos\s*\.\s*(?:system|popen|exec\w*|spawn\w*|remove|unlink|rmdir|removedirs|rename|replace|kill|fork|chmod|chown|environ|putenv|listdir|scandir|walk)\b|\b(?:eval|exec|compile)\s*\(|\bopen\s*\(""")
# C/C++: 프로세스·네트워크·파일 삭제/쓰기
_C_DANGER_RE = re.compile(r"""(?<![\w.>:])(?:system|popen|fork|vfork|execv\w*|execl\w*|execlp|socket|connect|bind|dlopen|dlsym|ptrace|remove|unlink|rmdir|rename|chmod|chown|setuid|kill)\s*\(|\bfopen\s*\([^)]*['"][^'"]*[wa+][^'"]*['"]|\bstd\s*::\s*(?:system|ofstream|thread|async)\b|<\s*(?:sys/socket|netinet/in|arpa/inet|unistd)\.h\s*>""")
# 서버 파일·네트워크·프로세스에 닿는 API 는 실행하지 않는다 (교육용 입출력 프로그램에는 필요 없음)
_JAVA_DANGER_RE = re.compile(r"\b(?:ProcessBuilder|Runtime\s*\.\s*getRuntime|java\s*\.\s*net|java\s*\.\s*nio\s*\.\s*file|Files\s*\.|FileInputStream|FileOutputStream|FileReader|FileWriter|RandomAccessFile|Socket|URLClassLoader|System\s*\.\s*(?:load|setSecurityManager)|java\s*\.\s*lang\s*\.\s*reflect|Class\s*\.\s*forName|MethodHandle)\b")
_JS_DANGER_RE = re.compile(r"""\b(?:require|import)\s*\(?\s*['"](?:node:)?(?:fs|child_process|net|http|https|dgram|dns|tls|os|cluster|worker_threads|vm|module|inspector)\b|\bprocess\s*\.\s*(?:binding|dlopen|kill|chdir|env)|\b(?:eval|Function)\s*\(\s*['"`]|\bfetch\s*\(|XMLHttpRequest|WebSocket""")


def _java_names(code):
    """(파일 이름으로 쓸 클래스, 실행할 클래스). public 클래스가 있으면 파일 이름은 그 이름이어야 하고, 실행할 클래스는 main 이 든 클래스이다."""
    pub = re.search(r"\bpublic\s+(?:(?:final|abstract|strictfp)\s+)*class\s+([A-Za-z_]\w*)", code)
    main = re.search(r"\bstatic\s+void\s+main\s*\(", code)
    run = None
    if main:
        before = [m for m in re.finditer(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", code[:main.start()])]
        run = before[-1].group(1) if before else None
    run = run or (pub.group(1) if pub else "Main")
    return (pub.group(1) if pub else run), run


def _safe_env():
    # API 키 등 서버 환경변수는 넘기지 않는다. Windows 의 gcc/g++ 는 PATH(자기 bin 폴더)·SystemRoot·TEMP 가 있어야 cc1/as 를 찾는다.
    env = {"PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}
    if os.name == "nt":
        for k in ("PATH", "SystemRoot", "SYSTEMROOT", "windir", "TEMP", "TMP", "COMSPEC", "PATHEXT"):
            if os.environ.get(k): env[k] = os.environ[k]
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


_NETNS = None                         # 확인 결과 캐시: ["unshare","-rn","--"] 또는 [] (쓸 수 없음)
_STRICT_NET = os.name == "posix"      # 리눅스 서버에서는 네트워크를 끊을 수 없으면 실행하지 않는다 (개발용 윈도우만 예외)
_NO_NET_MSG = "실행 환경 없음 (네트워크 차단 불가: unshare 를 쓸 수 없음. 컨테이너가 네트워크를 막는다면 INTAKE_EXEC_NO_NET=off)"
# 컴파일러가 서버 파일을 읽어 오류 메시지로 내보내는 것을 막는다: 따옴표 include, 절대·상위 경로 include, #embed, .incbin
_C_FILE_READ_RE = re.compile(r'#\s*(?:include|include_next|import)\s*(?:"|<\s*(?:/|\.\.|~))|#\s*embed\b|__has_embed|\.incbin\b|__has_include')


def _net_prefix():
    """실행 명령 앞에 붙일 '네트워크 차단' 접두어. 차단이 필요한데 할 수 없으면 None (실행 금지)."""
    global _NETNS
    try:
        from .. import config
        if not config.exec_block_network(): return []
    except ImportError:
        pass
    if _NETNS is None:
        _NETNS = []
        if os.name == "posix" and shutil.which("unshare"):
            try:
                if subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0:
                    _NETNS = ["unshare", "-rn", "--"]
            except Exception:
                pass
        if not _NETNS:
            logger.warning("네트워크를 끊는 unshare 를 쓸 수 없습니다. %s", "정답 코드 실행 검증을 건너뜁니다." if _STRICT_NET else "개발 환경이라 차단 없이 실행합니다.")
    return None if (not _NETNS and _STRICT_NET) else _NETNS


def _kill_tree(p):
    """시간 초과한 프로세스와 그 자식까지 모두 끝낸다. (java.exe 같은 실행 껍데기만 죽이면 실제 프로그램이 남아 출력 통로를 잡고 있다)"""
    try:
        if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)               # _limits 가 setsid 로 새 프로세스 그룹을 만들었다
    except Exception:
        pass
    try: p.kill()
    except Exception: pass


def _run_killing_tree(cmd, stdin_bytes, timeout, **kw):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    try:
        out, err = p.communicate(stdin_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try: p.communicate(timeout=5)
        except Exception: pass
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def run_code(language, code, stdin, timeout=5):
    """(결과, 메시지, 경고). 결과: 'ok' | 'skip' | 'error'"""
    posix = os.name == "posix"
    kw = dict(preexec_fn=_limits) if posix else {}
    net = _net_prefix()
    if net is None: return "skip", f"{language} {_NO_NET_MSG}", None
    if language == "python" and _PY_DANGER_RE.search(code or ""):
        return "error", "허용되지 않는 API(프로세스·네트워크·파일 쓰기·동적 실행)가 있어 실행하지 않음", None
    if language in ("c", "cpp") and _C_DANGER_RE.search(code or ""):
        return "error", "허용되지 않는 API(프로세스·네트워크·파일 쓰기)가 있어 컴파일하지 않음", None
    if language in ("c", "cpp") and _C_FILE_READ_RE.search(code or ""):
        return "error", "허용되지 않는 지시(따옴표·절대경로 include, #embed 등)가 있어 컴파일하지 않음", None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # Windows 는 실행 직후 exe 가 잠겨 있을 수 있음
        if language == "python":
            path = os.path.join(d, "main.py"); open(path, "w", encoding="utf-8").write(code)
            cmd = [sys.executable, "-I", "-X", "utf8", path]
        elif language in ("c", "cpp") and shutil.which("gcc" if language == "c" else "g++"):
            src = os.path.join(d, "main." + ("c" if language == "c" else "cpp")); exe = os.path.join(d, "a.out")
            open(src, "w", encoding="utf-8").write(code)
            try:
                comp = subprocess.run([("gcc" if language == "c" else "g++"), src, "-o", exe], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, cwd=d, env=_safe_env())
            except subprocess.TimeoutExpired:
                return "error", "컴파일 시간 초과", None
            if comp.returncode:
                return "error", "컴파일 실패: " + comp.stderr[:200], None
            cmd = [exe]
        elif language == "java" and shutil.which("javac") and shutil.which("java"):
            if _JAVA_DANGER_RE.search(code or ""):
                return "error", "허용되지 않는 API(파일·네트워크·프로세스·리플렉션)가 있어 실행하지 않음", None
            fname, run_cls = _java_names(code)
            open(os.path.join(d, fname + ".java"), "w", encoding="utf-8").write(code)
            try:
                comp = subprocess.run(["javac", "-encoding", "UTF-8", "-proc:none", "-d", d, os.path.join(d, fname + ".java")], capture_output=True, timeout=60, cwd=d, env=_safe_env())
            except subprocess.TimeoutExpired:
                return "error", "컴파일 시간 초과", None
            if comp.returncode:
                return "error", "컴파일 실패: " + (comp.stderr or b"").decode("utf-8", "replace").replace("\r\n", "\n").replace(d + os.sep, "").strip()[:300], None      # 서버의 임시 경로는 메시지에서 뺀다
            cmd = ["java", "-Xmx256m", "-XX:+UseSerialGC", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-cp", d, run_cls]
            timeout = max(timeout, 10); kw = dict(preexec_fn=lambda: _limits(True)) if posix else {}
        elif language == "javascript" and shutil.which("node"):
            if _JS_DANGER_RE.search(code or ""):
                return "error", "허용되지 않는 API(파일·네트워크·프로세스)가 있어 실행하지 않음", None
            path = os.path.join(d, "main.js"); open(path, "w", encoding="utf-8").write(code)
            cmd = ["node", "--max-old-space-size=256", path]
            timeout = max(timeout, 10); kw = dict(preexec_fn=lambda: _limits(True)) if posix else {}
        else:
            return "skip", f"{language} 실행 환경 없음", None
        try:
            r = _run_killing_tree(net + cmd, (stdin or "").encode("utf-8"), timeout, cwd=d, env=_safe_env(), **kw)
            # 바이트로 받아 직접 해석한다: Windows 의 기본 인코딩(cp949)·줄바꿈(\r\n) 영향을 받지 않게
            r.stdout = (r.stdout or b"").decode("utf-8", "replace").replace("\r\n", "\n"); r.stderr = (r.stderr or b"").decode("utf-8", "replace").replace("\r\n", "\n")
        except subprocess.TimeoutExpired:
            return "error", "시간 초과", None
        if len(r.stdout) > 200_000:
            return "error", "출력이 너무 김", None
        if r.returncode and not r.stdout.strip():
            msg = r.stderr.strip().splitlines()[-1][:200] if r.stderr.strip() else "출력 없음 (시간 제한 초과이거나 비정상 종료)"
            return "error", "실행 오류: " + msg, None
        warn = f"종료 코드 {r.returncode} (main 이 int 를 반환하는지 확인)" if r.returncode and not re.search(r"\bvoid\s+main\b", code) else None   # void main 은 종료 코드가 의미 없음
        return "ok", r.stdout, warn


def answer_leak_reason(payload):
    """설명에 정답이 그대로 들어 있을 수 있으면 승인 이유 문장을, 아니면 None. 학생에게 정답이 보이면 안 되므로 사람이 확인하게 한다."""
    p = payload or {}
    desc = str(p.get("description") or "")
    if not desc: return None
    t = p.get("problemType")
    key = lambda l: re.sub(r"\s+", "", re.sub(r"//.*$", "", str(l).replace("std::", ""))).rstrip(";")
    if t in ("코딩", "디버깅"):
        base = {key(l) for bc in (p.get("base_code") or []) for l in str(bc.get("code") or "").split("\n") if key(l)}
        ref = {key(l) for rc in (p.get("reference_codes") or []) for l in str(rc.get("code") or "").split("\n") if key(l)} - base
        dk = {key(l) for l in desc.split("\n") if key(l)}
        n = len(ref & dk)
        if n >= 3: return f"설명에 정답 코드와 같은 줄이 {n}줄 있습니다. 정답이 학생에게 보이지 않는지 확인하세요."
    elif t in ("단답형", "주관식"):
        at = p.get("answer_text")
        vals = [v for x in (at.values() if isinstance(at, dict) else [at] if isinstance(at, str) else (at or [])) for v in (x if isinstance(x, list) else [x])]
        for v in vals:
            if isinstance(v, str) and len(v.strip()) >= 4 and v.strip() in desc: return "설명에 정답 글이 그대로 들어 있습니다. 정답이 학생에게 보이지 않는지 확인하세요."
    return None


def dup_option_reason(payload):
    """객관식 보기가 서로 같으면 승인 이유 문장을, 아니면 None (스키마는 통과시키지만 정답이 둘로 갈린다)."""
    opts = (payload or {}).get("options")
    if (payload or {}).get("problemType") != "객관식" or not isinstance(opts, list): return None
    keys = [_nz(str(o)) for o in opts]
    return "객관식 보기 중 같은 내용이 있습니다. 정답이 둘로 갈릴 수 있으니 확인하세요." if len(set(keys)) < len(keys) else None


def check_case(case, seen_hashes, skip_exec):
    fails, warns = [], []
    payload, review = case.get("payload"), case.get("review") or {}
    expect = case.get("expect") or {}

    # hold: 보류 문제는 보내지 않는다
    if review.get("상태") == "보류":
        if payload is not None: fails.append("hold: 보류 문제인데 payload 가 있음")
        if not review.get("보류사유"): fails.append("hold: 보류사유가 비어 있음")
        return fails, warns
    if payload is None:
        return ["schema: 등록가능 문제인데 payload 가 없음"], warns

    # schema
    to_check = payload
    if fix.needs_input(payload):          # 서술형 모범 답안은 사람이 입력하므로 비어 있는 것 자체는 오류가 아니다 (나머지 항목만 검사)
        to_check = {**payload, "answer_text": fix.PLACEHOLDER}
        warns.append("input: " + fix.REASON)
    try:
        parsed = problem_adapter.validate_python(to_check)
    except ValidationError as e:
        errs = format_validation_errors(e)
        return [f"schema: {x['field']} - {x['message']}" for x in errs], warns

    # md: 엑셀에서 딸려온 마크다운 기호
    texts = [("description", payload.get("description"))] + [("problem_condition", c) for c in payload.get("problem_condition", [])]
    for label, t in texts:
        if t and has_markdown_bold(t): fails.append(f"md: {label} 에 마크다운 기호(**)가 남아 있음")

    # src: 원본조각이 함께 있으면 설명이 원본 문장 그대로인지 확인 (원본만 받는 경로)
    src = case.get("원본조각")
    if src:
        src_n = _nz(src)
        dl = _src_lines(payload.get("description"))
        miss = [l for l in dl if _nz(l) not in src_n]
        ratio = 1 - len(miss) / len(dl) if dl else 1
        floor = 0.3 if case.get("그림있음") else 0.7                 # 그림 속 설명을 글로 옮긴 문제는 원본 글에 없는 줄이 많을 수 있다
        if ratio < floor and len(miss) >= 2: fails.append(f"src: 설명이 원본과 크게 다름 ({ratio:.0%} 일치): {miss[0][:30]!r}")
        elif miss: warns.append(f"src: 설명 {len(miss)}줄이 원본에 그대로는 없음(표 형식 변환 등일 수 있음): {miss[0][:30]!r}")

    # ref: 디버깅·빈칸 완성 문제의 정답 코드는 제공 코드를 고치고 채운 '전체' 코드여야 한다 (제공 코드 줄의 절반 이상이 들어 있어야 함)
    if payload.get("problemType") == "디버깅" and payload.get("base_code") and payload.get("reference_codes"):
        key = lambda l: re.sub(r"\s+", "", re.sub(r"//.*$", "", str(l).replace("std::", ""))).rstrip(";")
        base = {key(l) for bc in payload["base_code"] for l in str(bc.get("code") or "").split("\n") if key(l)}
        ref = {key(l) for rc in payload["reference_codes"] for l in str(rc.get("code") or "").split("\n") if key(l)}
        if len(base) >= 3 and len(base & ref) < 0.5 * len(base):
            warns.append(f"ref: 디버깅의 정답 코드는 제공 코드까지 포함한 전체 실행 가능한 코드여야 합니다 (제공 코드 {len(base)}줄 중 {len(base & ref)}줄만 들어 있음)")

    # cond
    for c in payload.get("problem_condition", []):
        if not COND_RE.match(c):
            fails.append(f"cond: 형식 오류 → {c!r}")

    # dup
    h = compute_content_hash(parsed.problemType, parsed.title, parsed.description)
    if h in seen_hashes: fails.append(f"dup: {seen_hashes[h]} 와 같은 문제")
    else: seen_hashes[h] = payload.get("title")

    # exec
    ptype = parsed.problemType.value if hasattr(parsed.problemType, "value") else parsed.problemType
    if ptype in ("코딩", "디버깅"):
        warns += echo_warnings(parsed.test_cases)
        if not parsed.test_cases:
            warns.append("exec: 테스트 케이스 없음 → 실행 검증 불가(조건 기반 채점)")
        elif skip_exec:
            warns.append("exec: --skip-exec 로 건너뜀")
        else:
            for ref in parsed.reference_codes:
                for i, tc in enumerate(parsed.test_cases, 1):
                    status, out, warn = run_code(ref.language, ref.code, tc.input)
                    if warn and f"exec: {warn}" not in warns: warns.append(f"exec: {warn}")
                    if status == "skip": warns.append(f"exec: {out}"); break
                    if status == "error": fails.append(f"exec: 케이스 {i} {out}"); continue
                    if norm_out(out) != norm_out(tc.expected_output):
                        ws = " (공백·줄바꿈만 다름: 엑셀/원본 옮기기 중 줄바꿈이 바뀌었을 수 있음)" if _nz(out) == _nz(tc.expected_output) else ""
                        fails.append(f"exec: 케이스 {i} 출력 불일치{ws} → 기대 {tc.expected_output!r} / 실제 {norm_out(out)!r}")
    if ptype == "단답형" and isinstance(payload.get("answer_text"), dict):
        warns.append("short: answer_text 가 dict — 번호별 답으로 해석되는지 미확정")

    # snippets (원문 보존)
    desc = collapse(payload.get("description"))
    for s in expect.get("snippets", []):
        if collapse(s) not in desc: fails.append(f"snippets: 원문 조각이 description 에 없음 → {s[:40]!r}")

    # flags (함정 문제 대응)
    flags_text = " ".join(review.get("확인필요") or [])
    for f in expect.get("flags", []):
        if f not in flags_text: fails.append(f"flags: 확인필요에 '{f}' 관련 내용이 없음")
    if "확인필요" not in review: fails.append("flags: review 에 확인필요 키가 없음")
    return fails, warns


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    skip_exec = "--skip-exec" in sys.argv
    if not args:
        print(__doc__); sys.exit(2)
    cases = [json.loads(l) for l in open(args[0], encoding="utf-8") if l.strip()]
    seen, mismatch, tot = {}, 0, {"PASS": 0, "WARN": 0, "FAIL": 0}
    for case in cases:
        fails, warns = check_case(case, seen, skip_exec)
        result = "FAIL" if fails else ("WARN" if warns else "PASS")
        tot[result] += 1
        want = (case.get("expect") or {}).get("status")
        mark = ""
        if want:
            ok = (result == want) or (want == "WARN" and result == "WARN")
            mark = "  (예상대로)" if ok else f"  ✗ 예상은 {want}"
            mismatch += 0 if ok else 1
        print(f"[{result}] {case.get('id')}{mark}")
        for m in fails: print(f"     ✗ {m}")
        for m in warns: print(f"     △ {m}")
    print(f"\n합계: PASS {tot['PASS']} · WARN {tot['WARN']} · FAIL {tot['FAIL']}" + (f" · 예상과 다른 결과 {mismatch}" if mismatch else ""))
    has_expect = any((c.get("expect") or {}).get("status") for c in cases)
    sys.exit(1 if (mismatch if has_expect else tot["FAIL"]) else 0)


if __name__ == "__main__":
    main()
