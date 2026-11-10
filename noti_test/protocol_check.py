#!/usr/bin/env python3
"""프로토콜 출력 검사기.

사용법:  python protocol_check.py <결과.jsonl> [--skip-exec]
입력(JSONL, 한 줄에 문제 하나):
  {"id": "PY11-0004",
   "payload": {...API 로 보낼 문제...},          # 보류 문제는 null
   "review":  {"상태": "등록가능", "보류사유": null, "생성내역": {...}, "확인필요": [...]},
   "expect":  {"snippets": [...], "flags": [...], "status": "PASS"}}   # expect 는 선택
검사 항목:
  schema   payload 가 API 스키마(schemas.py)를 통과하는가
  cond     조건이 "[필수]/[금지]/[허용]/[출력형식] 내용" 형식의 문자열인가
  exec     정답 코드를 테스트 케이스 입력으로 실행했을 때 예상 출력과 같은가 (python, gcc/g++ 있으면 c/cpp)
  snippets 원문에서 가져와야 하는 조각이 description 에 그대로 있는가 (원문 보존)
  flags    확인필요에 반드시 올라와야 하는 항목이 있는가 (함정 문제 대응)
  hold     보류 문제는 payload 가 없고 사유가 있는가
  md       description/조건에 마크다운 기호(**)가 남아 있지 않은가
  src      (원본조각이 있을 때) 설명이 원본 문장 그대로인가
  dup      같은 배치 안에 중복 문제가 없는가
결과: PASS / WARN(사람이 볼 것) / FAIL.  expect.status 가 있으면 그 결과와 일치하는지도 확인한다.
"""
import json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hashlib, unicodedata
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.checks.fix import has_markdown_bold      # 서버 검사기와 같은 판정 (이 파일은 서버 checker.py 의 옛 복사본이라 따로 두면 어긋난다)
from pydantic import ValidationError
from app.inputdata.schemas import problem_adapter, format_validation_errors     # 프로젝트의 실제 스키마로 검사한다


def compute_content_hash(problem_type, title, description):
    """dedupe.py 와 같은 규칙(유형·제목·설명 기준)의 내장 복사본. 같은 배치 안 중복 검사에 쓴다."""
    types = {"coding": "코딩", "debugging": "디버깅", "multiple_choice": "객관식", "short_answer": "단답형", "subjective": "주관식"}
    def n(t, cf=False):
        x = re.sub(r"\s+", " ", unicodedata.normalize("NFC", "" if t is None else str(t)).replace("\r\n", "\n").replace("\r", "\n")).strip()
        return x.casefold() if cf else x
    key = "\x1f".join([types.get(str(problem_type), str(problem_type)), n(title, True), n(description)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

TAGS = ("필수", "금지", "허용", "출력형식")
COND_RE = re.compile(r"^\[(%s)\]\s*\S" % "|".join(TAGS))


def collapse(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _nz(s):
    s = str(s or "")
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u02bc", "'")):
        s = s.replace(a, b)
    return re.sub(r"[\s.,\u3002]+", "", s)          # 공백과 마침표·쉼표 차이는 무시 (엑셀이 문장 끝에 마침표를 붙이는 경우 등. source_compare 와 같은 기준)


def _src_lines(text):
    out = []
    for l in str(text or "").splitlines():
        l = re.sub(r"^[\s\-\u2022\u00b7*]+", "", l.strip())
        if len(_nz(l)) >= 3: out.append(l)
    return out


def norm_out(s):
    return "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").split("\n")).rstrip("\n")


def _limits():
    """자식 프로세스 제한 (POSIX). 시간 5초, 메모리 512MB, 파일 쓰기 1MB, 프로세스 새로 만들기 금지."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        os.setsid()
    except Exception:
        pass


def _safe_env():
    # API 키 등 서버 환경변수는 넘기지 않는다. Windows 의 gcc/g++ 는 PATH(자기 bin 폴더)·SystemRoot·TEMP 가 있어야 cc1/as 를 찾는다.
    env = {"PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}
    if os.name == "nt":
        for k in ("PATH", "SystemRoot", "SYSTEMROOT", "windir", "TEMP", "TMP", "COMSPEC", "PATHEXT"):
            if os.environ.get(k): env[k] = os.environ[k]
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def run_code(language, code, stdin, timeout=5):
    """(결과, 메시지, 경고). 결과: 'ok' | 'skip' | 'error'
    주의: AI 가 쓴 코드를 실제로 실행한다. 서버에서는 INTAKE_EXEC=on 일 때만 호출하고, 가능하면 격리된 작업 서버/컨테이너에서 켠다."""
    posix = os.name == "posix"
    kw = dict(preexec_fn=_limits) if posix else {}
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
        else:
            return "skip", f"{language} 실행 환경 없음", None
        try:
            r = subprocess.run(cmd, input=(stdin or "").encode("utf-8"), capture_output=True, timeout=timeout, cwd=d, env=_safe_env(), **kw)
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
    try:
        parsed = problem_adapter.validate_python(payload)
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
        if ratio < 0.7: fails.append(f"src: 설명이 원본과 크게 다름 ({ratio:.0%} 일치): {miss[0][:30]!r}")
        elif miss: warns.append(f"src: 설명 {len(miss)}줄이 원본에 그대로는 없음(표 형식 변환 등일 수 있음): {miss[0][:30]!r}")

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
