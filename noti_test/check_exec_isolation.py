#!/usr/bin/env python3
"""정답 코드 실행 격리 점검. 배포할 리눅스 컨테이너/서버에서 실행해 결과를 확인한다.

    cd noti_test && python check_exec_isolation.py

A. 어디서나 도는 점검 (모의): 네트워크를 끊을 수 없을 때 실행을 거부하는지, C 소스의 파일 읽기 지시를 막는지
B. 리눅스에서만 도는 점검 (실제): unshare 사용 가능 여부, 네트워크 차단(루프백 포함), 프로세스·메모리 제한
결과: PASS / FAIL / SKIP. FAIL 이 있으면 종료 코드 1. 이 스크립트는 AI 를 부르지 않고 키도 읽지 않는다.
"""
import os, shutil, socket, subprocess, sys, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); os.chdir(HERE)
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake.checks import checker

res = []
def report(name, status, note=""):
    res.append(status); print(f"  [{status}] {name}" + (f"  — {note}" if note else ""))

IS_LINUX = sys.platform.startswith("linux")
OLD = dict(env=os.environ.get("INTAKE_EXEC_NO_NET"), netns=checker._NETNS, strict=checker._STRICT_NET)
def restore():
    if OLD["env"] is None: os.environ.pop("INTAKE_EXEC_NO_NET", None)
    else: os.environ["INTAKE_EXEC_NO_NET"] = OLD["env"]
    checker._NETNS, checker._STRICT_NET = OLD["netns"], OLD["strict"]

print("A. 모의 점검 (어느 OS 에서나)")
os.environ["INTAKE_EXEC_NO_NET"] = "on"; checker._NETNS = []            # unshare 를 쓸 수 없는 서버를 흉내
checker._STRICT_NET = True
st, msg, _ = checker.run_code("python", "print('ok')", "")
report("리눅스 서버에서 네트워크를 끊을 수 없으면 실행을 거부한다", "PASS" if st == "skip" and "실행 환경 없음" in msg else "FAIL", f"{st}: {msg[:60]}")
checker._STRICT_NET = False
st, out, _ = checker.run_code("python", "print('ok')", "")
report("개발용(비리눅스)에서는 경고만 하고 실행한다", "PASS" if st == "ok" and out.strip() == "ok" else "FAIL", f"{st}")
checker._STRICT_NET = True; os.environ["INTAKE_EXEC_NO_NET"] = "off"
st, out, _ = checker.run_code("python", "print('ok')", "")
report("INTAKE_EXEC_NO_NET=off 면 (컨테이너가 막았다고 운영자가 확인한 경우) 실행한다", "PASS" if st == "ok" else "FAIL", f"{st}")
bad_lines = ['#include "/etc/passwd"', '#include </etc/shadow>', '#include <../../x>', '#embed "/etc/passwd"', '__asm__(".incbin \\"/etc/passwd\\"");', '#if __has_include("a")']
blocked = [l for l in bad_lines if checker.run_code("c", l + "\nint main(){return 0;}", "")[0] == "error"
           and "허용되지 않는" in checker.run_code("c", l + "\nint main(){return 0;}", "")[1]]
report("C 소스의 서버 파일 읽기 지시 6종을 모두 막는다", "PASS" if len(blocked) == len(bad_lines) else "FAIL", f"{len(blocked)}/{len(bad_lines)}")
ok_inc = all(not checker._C_FILE_READ_RE.search(l) for l in ("#include <stdio.h>", "#include <sys/types.h>", "#include <bits/stdc++.h>"))
report("정상 include 는 막지 않는다", "PASS" if ok_inc else "FAIL")
restore()

print("B. 실제 점검 (리눅스 전용)")
if not IS_LINUX:
    for n in ("unshare 사용 가능", "네트워크(루프백 포함) 차단", "프로세스 생성 제한", "메모리 제한"):
        report(n, "SKIP", f"리눅스가 아님 ({sys.platform})")
else:
    ok_unshare = bool(shutil.which("unshare")) and subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0
    report("unshare -rn 사용 가능", "PASS" if ok_unshare else "FAIL", "" if ok_unshare else "컨테이너에서 user namespace 가 막힘 → 실행 검증은 거부됨(안전). 켜려면 권한을 주거나, 컨테이너가 네트워크를 막았다면 INTAKE_EXEC_NO_NET=off")
    # 부모가 127.0.0.1 에서 기다리고, 자식(격리 실행)이 접속을 시도한다. 격리가 되면 접속할 수 없다.
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5); port = srv.getsockname()[1]
    stop = threading.Event()
    def accept_loop():
        srv.settimeout(0.3)
        while not stop.is_set():
            try: c, _ = srv.accept(); c.close()
            except Exception: pass
    threading.Thread(target=accept_loop, daemon=True).start()
    probe = f"import socket\ntry:\n    socket.create_connection(('127.0.0.1', {port}), timeout=3); print('CONNECTED')\nexcept Exception as e:\n    print('BLOCKED')\n"
    os.environ["INTAKE_EXEC_NO_NET"] = "off"; checker._NETNS = None
    st, out_off, _ = checker.run_code("python", probe, "")
    os.environ["INTAKE_EXEC_NO_NET"] = "on"; checker._NETNS = None; checker._STRICT_NET = True
    st2, out_on, _ = checker.run_code("python", probe, "")
    stop.set(); srv.close()
    if out_off.strip() != "CONNECTED":
        report("네트워크(루프백 포함) 차단", "SKIP", f"비교 기준(차단 해제 상태)에서 접속이 안 돼 판단할 수 없음: {out_off.strip()[:40]}")
    elif st2 == "ok" and out_on.strip() == "BLOCKED":
        report("네트워크(루프백 포함) 차단", "PASS", "차단 해제 시 접속됨 → 차단 시 접속 안 됨")
    elif st2 == "skip":
        report("네트워크(루프백 포함) 차단", "PASS", "차단할 수 없어 실행을 거부함(안전)")
    else:
        report("네트워크(루프백 포함) 차단", "FAIL", f"차단 상태인데 결과 {st2}: {out_on.strip()[:60]}")
    restore(); os.environ["INTAKE_EXEC_NO_NET"] = "off"; checker._NETNS = None
    st, out, _ = checker.run_code("python", "import subprocess\ntry:\n    subprocess.run(['true'], check=True); print('FORKED')\nexcept Exception:\n    print('LIMITED')\n", "")
    report("프로세스 생성 제한(RLIMIT_NPROC=0)", "PASS" if out.strip() == "LIMITED" else "FAIL", f"{out.strip()[:40]} — 환경(UID)에 따라 달라질 수 있어 배포 환경에서 꼭 확인")
    st, out, _ = checker.run_code("python", "try:\n    x = bytearray(900 * 1024 * 1024); print('ALLOCATED')\nexcept MemoryError:\n    print('LIMITED')\n", "")
    report("메모리 제한(512MB)", "PASS" if out.strip() == "LIMITED" else "FAIL", out.strip()[:40])
    restore()

n_fail, n_skip = res.count("FAIL"), res.count("SKIP")
print(f"\n결과: PASS {res.count('PASS')} · FAIL {n_fail} · SKIP {n_skip}")
sys.exit(1 if n_fail else 0)
