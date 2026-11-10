"""멈춘 AI 호출 하나가 작업 전체를 붙잡지 않는다: 기한을 넘기면 같은 요청을 한 번 더 보낸다."""
import asyncio, os, sys, time, threading
import _bootstrap
_bootstrap.setup(sqlite=True)
os.environ["INTAKE_CALL_DEADLINE"] = "1"
from app.inputdata.intake import service

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

calls = []
def flaky(x):
    calls.append(x)
    if len(calls) == 1: time.sleep(4)          # 첫 호출은 멈춘다
    return "답:" + x

async def _run(fn, *a):
    t = time.time(); r = await service._timed(fn, *a); return r, time.time() - t
out, dt = asyncio.run(_run(flaky, "q"))
check("멈춘 첫 호출은 버리고 같은 요청을 다시 보내 결과를 받는다", out == "답:q" and len(calls) == 2, (out, calls))
check("기한(1초) + 재요청 시간만 걸린다 (멈춘 4초를 기다리지 않음)", dt < 3, dt)

calls.clear()
out = asyncio.run(service._timed(lambda: (calls.append(1), "빠름")[1]))
check("정상 호출은 한 번만 보낸다", out == "빠름" and len(calls) == 1)

os.environ["INTAKE_CALL_DEADLINE"] = "0"
calls.clear()
check("0 이면 헤징을 끄고 그대로 기다린다", asyncio.run(service._timed(lambda: (calls.append(1), "ok")[1])) == "ok" and len(calls) == 1)

os.environ["INTAKE_CALL_DEADLINE"] = "1"; os.environ["INTAKE_CALL_HARD_LIMIT"] = "5"
def stuck(): time.sleep(12)
try:
    asyncio.run(service._timed(stuck)); raised = False
except service.SlowCall:
    raised = True
check("다시 보낸 요청도 제한시간 안에 답이 없으면 SlowCall (그 문제는 보류로)", raised)
print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
