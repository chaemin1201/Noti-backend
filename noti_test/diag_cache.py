"""AI 서비스의 프롬프트 캐시가 실제로 적중하는지 확인하는 진단 도구 (실제 AI 를 몇 번 부른다).
같은 프롬프트로 (1) 순서대로 3번, (2) 처음 한 번 데운 뒤 동시에 4번 보내고 usage 의 입력·캐시 토큰을 보여 준다. 키는 출력하지 않는다.
noti_test 폴더에서:  python diag_cache.py"""
import json, sys, threading, time
import _bootstrap
_bootstrap.setup(sqlite=True)
from app.inputdata.intake import service, llm

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

provider, model, key = llm.resolve()
PROMPT = llm.trim_prompt(open(service.config.prompt_path(), encoding="utf-8").read(), "입력종류\": \"엑셀")
USER = ('채점 모드: none\n입력: {"입력종류":"엑셀","표형식":"엑셀","fields":{"이름":"D_01","유형":"코딩","설명":"두 수의 합을 출력하시오","정답코드":"print(1)","출력":"1"},"intake":{"유형":"코딩","유형추정":false,"필수누락":[],"메모":[]}}')
rows = []

def one(tag, salt=""):
    info = {}
    t0 = time.time()
    try: llm.call_llm(provider, model, key, salt + PROMPT, USER, 300, info=info)
    except Exception as e:
        rows.append((tag, "오류 " + str(e)[:80])); return
    u = info.get("usage") or {}
    i, o, th, ca = service._tokens(info)
    rows.append((tag, f"{time.time() - t0:4.1f}초 입력 {i} 캐시 {ca} 출력 {o}   (usage 키: {sorted(u)[:8]})"))

print("모델:", model)
print("1) 같은 요청을 순서대로 3번")
for k in range(3):
    one(f"순차{k + 1}"); print("  ", *rows[-1])
print("2) 데운 뒤 동시에 4번 (이미 캐시가 있으면 모두 적중해야 함)")
ts = [threading.Thread(target=one, args=(f"동시{k + 1}",)) for k in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
for r in rows[3:]: print("  ", *r)
print("3) 캐시가 비어 있는 상태에서 동시에 4번 (프롬프트 맨 앞을 바꿔 새 캐시로 만듦)")
n0 = len(rows)
fresh = ("신선 %f\n" % time.time()) + USER
ts = [threading.Thread(target=one, args=(f"처음동시{k + 1}", fresh)) for k in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
for r in rows[n0:]: print("  ", *r)
