"""OpenAI 호환 방식(LLM_PROVIDER=openai) 호출 시험 (가짜 서버): 요청 모양, 그림 첨부, 응답·사용량 읽기, 키·주소 선택.
noti_test 폴더에서:  python test_llm_openai.py"""
import os, sys
os.environ["LLM_DOTENV_CWD_ONLY"] = "1"
import _bootstrap
_bootstrap.setup()
from app.inputdata.intake import llm

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

for v in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "LLM_MODEL", "LLM_MAX_TOKENS_PARAM", "LLM_TEMPERATURE"):
    os.environ.pop(v, None)

print("1. 요청")
sent = {}
real = llm._post
def fake(url, headers, body, timeout, waits, on_retry=None, stream=False, first_sec=None):
    sent.update(url=url, headers=headers, body=body)
    return {"choices": [{"message": {"content": '{"ok":1}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1200, "completion_tokens": 80}}
llm._post = fake
try:
    os.environ["LLM_BASE_URL"] = "https://api.example.com/v1/"
    out = llm.call_llm("openai", "m-1", "SECRET", "시스템", "사용자", 777, retries=0, images=[{"mime": "image/png", "b64": "AAAA"}])
    check("주소는 {LLM_BASE_URL}/chat/completions (끝 / 정리)", sent["url"] == "https://api.example.com/v1/chat/completions", sent["url"])
    check("인증은 Bearer 헤더", sent["headers"]["authorization"] == "Bearer SECRET")
    b = sent["body"]
    check("system / user 메시지와 max_tokens, 기본은 temperature 를 보내지 않는다", b["messages"][0] == {"role": "system", "content": "시스템"} and b["max_tokens"] == 777 and "temperature" not in b, b)
    c = b["messages"][1]["content"]
    check("그림은 data URL 로 붙는다", c[0] == {"type": "text", "text": "사용자"} and c[1]["image_url"]["url"] == "data:image/png;base64,AAAA", c)
    check("응답 글을 돌려준다", out == '{"ok":1}')
    llm.call_llm("openai", "m-1", "K", "s", "u", 10, retries=0)
    check("그림이 없으면 user 내용은 글 그대로", sent["body"]["messages"][1]["content"] == "u")
    os.environ["LLM_MAX_TOKENS_PARAM"] = "max_completion_tokens"; os.environ["LLM_TEMPERATURE"] = "0"
    llm.call_llm("openai", "m-1", "K", "s", "u", 10, retries=0)
    check("max_completion_tokens·temperature 는 .env 로 지정했을 때만", sent["body"].get("max_completion_tokens") == 10 and "max_tokens" not in sent["body"] and sent["body"]["temperature"] == 0.0, sent["body"])
    info = {}
    llm.call_llm("openai", "m-1", "K", "s", "u", 10, retries=0, info=info)
    check("사용량이 토큰 수로 읽힌다", info["usage"]["promptTokenCount"] == 1200 and info["usage"]["candidatesTokenCount"] == 80 and "입력 1,200" in llm.format_usage(info), llm.format_usage(info))
    llm._post = lambda *a, **k: {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 7554, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 7424}}}
    info2 = {}
    llm.call_llm("openai", "m-1", "K", "s", "u", 10, retries=0, info=info2)
    from app.inputdata.intake import service as _svc
    check("OpenAI 의 캐시된 입력 토큰(prompt_tokens_details.cached_tokens)을 버리지 않고 로그에 넘긴다 (예전에는 항상 0 으로 보였음)", _svc._tokens(info2) == (7554, 200, 0, 7424), _svc._tokens(info2))
    llm._post = fake
    llm._post = lambda *a, **k: {"choices": [{"message": {"content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}}]}
    check("내용이 조각 목록으로 와도 이어 붙인다", llm.call_llm("openai", "m", "K", "s", "u", 10, retries=0) == "AB")
    llm._post = lambda *a, **k: {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    try: llm.call_llm("openai", "m", "K", "s", "u", 10, retries=0); ok = False
    except RuntimeError as e: ok = "length" in str(e)
    check("빈 응답은 이유(finish_reason)와 함께 오류", ok)
finally:
    llm._post = real

print("2. 키·주소 선택")
os.environ.pop("LLM_BASE_URL", None); os.environ["LLM_PROVIDER"] = "openai"; os.environ["GEMINI_API_KEY"] = "KEY-IN-OLD-NAME"; os.environ["LLM_MODEL"] = "m-1"
p, m, k = llm.resolve()
check("LLM_PROVIDER=openai 이면 이름을 못 바꾼 GEMINI_API_KEY 의 키도 쓴다", (p, m, k) == ("openai", "m-1", "KEY-IN-OLD-NAME"))
os.environ["LLM_API_KEY"] = "NEW"
check("LLM_API_KEY 가 있으면 그것이 우선", llm.resolve()[2] == "NEW")
del os.environ["LLM_PROVIDER"]; os.environ["GEMINI_API_KEY"] = "G"
check("LLM_PROVIDER 가 없으면 기존처럼 Gemini", llm.resolve()[0] == "google")
os.environ["LLM_PROVIDER"] = "openai"; del os.environ["LLM_MODEL"]
check("모델 이름이 없어도 OpenAI(주소 지정 없음)는 기본 모델을 쓴다", llm.resolve()[1] == llm.DEFAULT_MODELS["openai"])

print("3. 스트리밍 · 끊긴 응답 재시도 · 추가 요청 값")
import email.message, io, urllib.error
def sse(*chunks, finish="stop", usage=None):
    out = []
    for c in chunks: out.append(b"data: " + json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False).encode() + b"\n"); out.append(b"\n")
    out.append(b"data: " + json.dumps({"choices": [{"delta": {"content": None}, "finish_reason": finish}], **({"usage": usage} if usage else {})}).encode() + b"\n")
    out.append(b"data: [DONE]\n"); return out
class Resp:
    def __init__(self, lines): self.lines = lines
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(self.lines)
def http_err(code):
    h = email.message.Message()
    return urllib.error.HTTPError("http://x", code, "err", h, io.BytesIO(f"error code: {code}".encode()))
import json
real_open = llm.urllib.request.urlopen
def run_with(responses, **kw):
    seq = list(responses); seen = []
    def fake_open(req, timeout=None):
        seen.append(json.loads(req.data.decode("utf-8")))
        r = seq.pop(0)
        if isinstance(r, Exception): raise r
        return Resp(r)
    llm.urllib.request.urlopen = fake_open
    try: return seen, llm.call_llm("openai", "m", "K", "s", "u", 50, **kw)
    finally: llm.urllib.request.urlopen = real_open
os.environ["LLM_BASE_URL"] = "https://api.example.com/v1"
seen, out = run_with([sse("안", "녕", usage={"prompt_tokens": 5, "completion_tokens": 2})], retries=0, info=(info := {}))
check("기본은 스트리밍으로 요청하고 조각을 이어 붙인다", seen[0].get("stream") is True and out == "안녕", (seen[0].get("stream"), out))
check("마지막 이벤트의 사용량을 읽는다", (info["usage"]["promptTokenCount"], info["usage"]["candidatesTokenCount"]) == (5, 2), info.get("usage"))
retries = []
seen, out = run_with([sse(finish=None)[:0] or [b"data: [DONE]\n"], http_err(524), sse("끝")], waits=[0, 0, 0], on_retry=lambda i, n, w, why: retries.append(why))
check("내용 없이 끊긴 응답과 524 는 다시 시도해서 성공한다", out == "끝" and retries == ["응답 끊김", "HTTP 524"], (out, retries))
try: run_with([[b"data: [DONE]\n"]] * 3, waits=[0, 0]); ok = False
except RuntimeError as e: ok = "끊겼" in str(e)
check("계속 끊기면 일시 오류로 알린다 (설정 오류로 작업을 멈추지 않음)", ok)
seen, out = run_with([sse("a")], retries=0)
check("LLM_EXTRA_BODY 가 없으면 추가 값이 없다", "reasoning_effort" not in seen[0])
os.environ["LLM_EXTRA_BODY"] = '{"reasoning_effort": "low", "x": 1}'
seen, out = run_with([sse("a")], retries=0)
check("LLM_EXTRA_BODY(JSON) 를 요청에 합친다", seen[0]["reasoning_effort"] == "low" and seen[0]["x"] == 1, seen[0])
os.environ["LLM_EXTRA_BODY"] = "{깨진"
try: run_with([sse("a")], retries=0); ok = False
except RuntimeError as e: ok = "LLM_EXTRA_BODY" in str(e)
check("LLM_EXTRA_BODY 가 JSON 이 아니면 안내한다", ok)
del os.environ["LLM_EXTRA_BODY"]
os.environ["LLM_STREAM"] = "off"
seen = []
llm.urllib.request.urlopen = lambda req, timeout=None: (seen.append(json.loads(req.data.decode())), type("R", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False, "read": lambda s: json.dumps({"choices": [{"message": {"content": "일반"}, "finish_reason": "stop"}]}).encode()})())[1]
try: out = llm.call_llm("openai", "m", "K", "s", "u", 50, retries=0)
finally: llm.urllib.request.urlopen = real_open; del os.environ["LLM_STREAM"]
check("LLM_STREAM=off 이면 한 번에 받는다", "stream" not in seen[0] and out == "일반")
print("프롬프트 캐시 표시 (같은 프롬프트를 문제마다 보내는 입력 토큰을 줄이기 위해)")
_seen = {}
_orig_post = llm._post
def _fake_post(u, headers, body, timeout, waits, on_retry, stream=False):
    _seen["body"] = body
    if "anthropic" in u: return {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": 3}}
    return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
llm._post = _fake_post
try:
    llm.call_llm("anthropic", "m", "k", "SYS", "USR", 100, url="https://x/anthropic", retries=0)
    s = _seen["body"]["system"]
    check("Anthropic: 시스템 프롬프트를 캐시 대상(cache_control)으로 보낸다", isinstance(s, list) and s[0]["text"] == "SYS" and s[0]["cache_control"] == {"type": "ephemeral"}, s)
    os.environ.pop("LLM_CACHE_CONTROL", None)
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    check("OpenAI 호환: 기본은 시스템 프롬프트를 글자 그대로 보낸다 (받지 못하는 서비스에서 오류가 나지 않게)", _seen["body"]["messages"][0]["content"] == "SYS", _seen["body"]["messages"][0])
    os.environ["LLM_CACHE_CONTROL"] = "on"
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    m0 = _seen["body"]["messages"][0]["content"]
    check("OpenAI 호환: LLM_CACHE_CONTROL=on 이면 캐시 대상으로 표시한다", isinstance(m0, list) and m0[0]["cache_control"] == {"type": "ephemeral"}, m0)
    os.environ.pop("LLM_BASE_URL", None); os.environ.pop("LLM_STREAM_USAGE", None)
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    check("실제 OpenAI 주소(LLM_BASE_URL 없음)는 스트리밍에서 사용량을 요청한다", _seen["body"].get("stream_options") == {"include_usage": True}, _seen["body"].get("stream_options"))
    os.environ["LLM_BASE_URL"] = "https://gateway.example/v1"
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    check("다른 게이트웨이는 기본으로 요청하지 않는다 (모르는 항목을 거절할 수 있어서)", "stream_options" not in _seen["body"])
    os.environ["LLM_STREAM_USAGE"] = "on"
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    check("LLM_STREAM_USAGE=on 이면 게이트웨이에도 요청한다", _seen["body"].get("stream_options") == {"include_usage": True})
    os.environ.pop("LLM_BASE_URL", None); os.environ.pop("LLM_STREAM_USAGE", None)
    os.environ.pop("LLM_BASE_URL", None)
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0); k1 = _seen["body"].get("prompt_cache_key")
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0); k2 = _seen["body"].get("prompt_cache_key")
    llm.call_llm("openai", "m", "k", "OTHER", "USR", 100, url="https://x/v1/chat", retries=0); k3 = _seen["body"].get("prompt_cache_key")
    check("실제 OpenAI 주소는 같은 프롬프트에 같은 캐시 키(prompt_cache_key)를, 다른 프롬프트에 다른 키를 보낸다", k1 and k1 == k2 and k1 != k3, (k1, k2, k3))
    os.environ["LLM_BASE_URL"] = "https://gateway.example/v1"
    llm.call_llm("openai", "m", "k", "SYS", "USR", 100, url="https://x/v1/chat", retries=0)
    check("다른 게이트웨이에는 캐시 키를 보내지 않는다 (모르는 항목을 거절할 수 있어서)", "prompt_cache_key" not in _seen["body"])
    os.environ.pop("LLM_BASE_URL", None)
finally:
    llm._post = _orig_post; os.environ.pop("LLM_CACHE_CONTROL", None)
print("키만 있으면 동작 (제공자·모델은 자동)")
_saved = {k: os.environ.pop(k, None) for k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")}
_orig_dot = llm.load_dotenv; llm.load_dotenv = lambda *a, **k: None
try:
    os.environ["GEMINI_API_KEY"] = "k"
    check("GEMINI_API_KEY 만 있으면 제공자는 google, 모델은 기본 모델", llm.resolve()[:2] == ("google", llm.DEFAULT_MODELS["google"]), llm.resolve()[:2])
    os.environ["LLM_MODEL"] = "my-model"
    check("LLM_MODEL 을 적으면 그 모델을 쓴다", llm.resolve()[1] == "my-model")
    os.environ.pop("LLM_MODEL"); os.environ.pop("GEMINI_API_KEY"); os.environ["LLM_PROVIDER"] = "openai"; os.environ["LLM_API_KEY"] = "k"
    check("제공자를 openai 로 적고 모델을 안 적으면 OpenAI 기본 모델", llm.resolve()[1] == llm.DEFAULT_MODELS["openai"])
    os.environ.pop("LLM_PROVIDER", None); os.environ.pop("LLM_API_KEY", None)
    for var, key, want in (("LLM_API_KEY", "sk-proj-abc", "openai"), ("GEMINI_API_KEY", "sk-proj-abc", "openai"), ("OPENAI_API_KEY", "sk-ant-abc", "anthropic"),
                           ("LLM_API_KEY", "AQ.Ab8Rxyz", "google"), ("ANTHROPIC_API_KEY", "AIzaSyXYZ", "google"), ("GEMINI_API_KEY", "AIzaSyXYZ", "google")):
        os.environ[var] = key
        got = llm.resolve()
        check(f"{var} 에 {key[:8]}… 키만 있어도 제공자는 {want}, 모델은 기본 모델", got[0] == want and got[1] == llm.DEFAULT_MODELS[want] and got[2] == key, got[:2])
        os.environ.pop(var)
    os.environ["LLM_API_KEY"] = "sk-proj-abc"; os.environ["LLM_BASE_URL"] = "https://gateway.example/v1"
    try: llm.resolve(); err = ""
    except SystemExit as e: err = str(e)
    check("게이트웨이 주소(LLM_BASE_URL)를 쓰는 OpenAI 호환은 기본 모델을 쓰지 않고 모델 이름을 요구한다", "모델 이름" in err, err)
    os.environ.pop("LLM_BASE_URL"); os.environ.pop("LLM_API_KEY")
finally:
    llm.load_dotenv = _orig_dot
    for k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"): os.environ.pop(k, None)
    for k, v in _saved.items():
        if v is not None: os.environ[k] = v

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
