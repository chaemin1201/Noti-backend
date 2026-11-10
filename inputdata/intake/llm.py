"""AI 호출 공통 모듈 (Anthropic / Google Gemini) 과 .env 읽기.

- 키는 환경변수 또는 .env 파일에서 읽는다. (키 값은 화면에 출력하지 않는다)
    Google :  GEMINI_API_KEY  (또는 GOOGLE_API_KEY)
    Anthropic: ANTHROPIC_API_KEY
    기타    :  LLM_PROVIDER=google|anthropic , LLM_MODEL=모델이름 , NOTI_TOKEN=서버 로그인 토큰
- .env 는 현재 폴더, 이 파일이 있는 폴더, 그 상위 폴더 2단계까지 순서대로 찾는다. 이미 설정된 환경변수는 덮어쓰지 않는다.
"""
from functools import lru_cache
import http.client, json, os, re, time, urllib.error, urllib.request

GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODELS = {"google": "gemini-2.5-flash", "anthropic": "claude-sonnet-5-5", "openai": "gpt-4.1-mini"}       # LLM_MODEL 이 없을 때. 모델 이름이 바뀌면 .env 의 LLM_MODEL 로 지정한다 (OpenAI 호환은 서비스마다 달라 기본값 없음)
OPENAI_BASE_URL = "https://api.openai.com/v1"
UA = "Mozilla/5.0 (compatible; NotiIntake/1.0)"      # 파이썬 기본 접속 표시(Python-urllib)는 Cloudflare 앞의 서비스가 403(error code 1010)으로 막는다
KEY_VARS = {"google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "anthropic": ("ANTHROPIC_API_KEY",),
            "openai": ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")}      # openai(호환) 는 LLM_PROVIDER=openai 로 고른 경우에만 쓰이므로, 키 변수 이름을 못 바꾼 .env 도 읽는다
HERE = os.path.dirname(os.path.abspath(__file__))


def parse_dotenv(text):
    out = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln: continue
        if ln.startswith("export "): ln = ln[7:].strip()
        k, v = ln.split("=", 1); k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'": v = v[1:-1]
        elif " #" in v: v = v.split(" #", 1)[0].strip()          # 값 뒤의 주석
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k): out[k] = v
    return out


def load_dotenv(extra_dirs=()):
    """.env 를 찾아 환경변수로 올린다. (읽은 파일 경로 목록, 새로 설정한 변수 이름 목록)을 돌려준다."""
    dirs = [os.getcwd(), HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE)), *extra_dirs]
    if os.environ.get("LLM_DOTENV_CWD_ONLY") == "1": dirs = [os.getcwd(), *extra_dirs]       # 시험용: 실제 서버의 .env 가 시험에 섞이지 않게 현재 폴더만 본다
    seen, files, names = set(), [], []
    for d in dirs:
        p = os.path.join(d, ".env")
        if p in seen or not os.path.isfile(p): continue
        seen.add(p); files.append(p)
        for k, v in parse_dotenv(open(p, encoding="utf-8-sig").read()).items():
            if k not in os.environ and v != "": os.environ[k] = v; names.append(k)
    return files, names


ALL_KEY_VARS = ("LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def provider_of_key(key):
    """키의 앞부분으로 제공자를 추정한다 (sk-ant- → Claude, sk- / sk-proj- → OpenAI, AIza / AQ. → 구글). 모르는 모양이면 None."""
    k = (key or "").strip()
    if k.startswith("sk-ant-"): return "anthropic"
    if k.startswith("sk-"): return "openai"
    if k.startswith(("AIza", "AQ.")): return "google"
    return None


def detect_provider(explicit=None):
    p = (explicit or os.environ.get("LLM_PROVIDER") or "").lower()
    if p in ("google", "gemini"): return "google"
    if p == "anthropic": return "anthropic"
    if p in ("openai", "openai-compatible", "compatible"): return "openai"
    for v in ALL_KEY_VARS:                                 # 제공자를 적지 않았으면 키 모양으로 정한다 (어느 변수에 넣었는지는 상관없음)
        k = os.environ.get(v)
        if k and provider_of_key(k): return provider_of_key(k)
    for name in ("google", "anthropic"):                   # 모양을 모르는 키(게이트웨이 키 등)는 변수 이름으로 정한다
        if any(os.environ.get(v) for v in KEY_VARS[name] if v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")): return name
    if any(os.environ.get(v) for v in ("LLM_API_KEY", "OPENAI_API_KEY")): return "openai"
    return None


def get_key(provider):
    for v in KEY_VARS[provider]:
        k = os.environ.get(v)
        if k and (provider_of_key(k) in (None, provider)): return k
    for v in ALL_KEY_VARS:                                 # 다른 변수에 넣은 키도 모양이 맞으면 쓴다 (예: LLM_API_KEY 에 구글 키)
        k = os.environ.get(v)
        if k and provider_of_key(k) == provider: return k
    return None


def key_help(provider):
    names = " 또는 ".join(KEY_VARS[provider])
    return f"{names} 가 필요합니다. 환경변수로 설정하거나 .env 파일에 `{KEY_VARS[provider][0]}=키` 한 줄을 적으세요."


RETRY_WAITS = [3, 8, 20, 45]                          # 혼잡·한도 오류 때 기다릴 시간(초). 총 76초까지 기다린다
RETRYABLE = (429, 500, 502, 503, 504, 520, 522, 524, 529)      # 520·522·524: 앞단 게이트웨이(Cloudflare)가 서버 응답을 기다리다 끊은 경우 (설정 오류가 아님)


class TransientLLMError(RuntimeError):
    """혼잡·한도·연결 오류처럼 시간이 지나면 풀릴 수 있는 오류 (재시도를 모두 써도 안 된 경우)."""


class FatalLLMError(RuntimeError):
    """다시 시도해도 소용없는 설정 오류(키·모델·요청 형식). 테스트나 파이프라인은 이 오류가 나면 바로 중단한다."""
    fatal = True
    model_issue = False        # True 이면 이 '모델'이 문제라서 대체 모델로 바꿔 보는 것이 의미 있다


def thinking_config(v):
    """'low' → {"thinkingLevel": "low"} (Gemini 3 계열), '0' / '1024' / '-1' → {"thinkingBudget": 숫자} (Gemini 2.5 계열).
    두 가지를 같은 요청에 함께 보내면 400 오류이므로 하나만 만든다."""
    v = str(v).strip().lower()
    if v in ("minimal", "low", "medium", "high"): return {"thinkingLevel": v}
    if re.fullmatch(r"-?\d+", v): return {"thinkingBudget": int(v)}
    raise ValueError(f"thinking 값이 올바르지 않습니다: {v!r} (minimal/low/medium/high 또는 숫자)")


def _usage(resp, provider):
    """응답의 사용량 원본. Gemini: usageMetadata(promptTokenCount, thoughtsTokenCount, candidatesTokenCount), Anthropic: usage, OpenAI 호환: usage(prompt_tokens, completion_tokens)."""
    if provider == "openai":
        u = resp.get("usage") or {}
        det = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
        return {"promptTokenCount": u.get("prompt_tokens"), "candidatesTokenCount": u.get("completion_tokens"), "prompt_tokens_details": det,
                "completion_tokens_details": u.get("completion_tokens_details") if isinstance(u.get("completion_tokens_details"), dict) else {}}      # 캐시·생각 토큰 수를 로그에서 볼 수 있게 함께 넘긴다
    return (resp.get("usageMetadata") if provider == "google" else resp.get("usage")) or {}


def format_usage(info):
    """info(call_llm 이 채워 준 값)를 한 줄로: 걸린 시간과 토큰 수."""
    if not info or "elapsed" not in info: return ""
    s = f"⏱ {info['elapsed']:.1f}초"
    if info.get("waited"): s += f" (재시도 대기 {info['waited']:g}초 포함)"
    u = info.get("usage") or {}
    vals = (("입력", u.get("promptTokenCount") or u.get("input_tokens")), ("출력", u.get("candidatesTokenCount") or u.get("output_tokens")), ("생각", u.get("thoughtsTokenCount")))
    parts = [f"{n} {v:,}" for n, v in vals if v]
    return s + (" · 토큰 " + " / ".join(parts) if parts else "")


def _explain(code, raw, provider_hint):
    """HTTP 오류 본문에서 사람이 읽을 메시지를 꺼내고, 원인별 안내를 붙인다."""
    msg = raw
    try:
        d = json.loads(raw); msg = (d.get("error") or {}).get("message") or raw
    except ValueError:
        pass
    msg = " ".join(str(msg).split())[:400]
    if code == 404 and provider_hint == "google":
        hint = "→ 이 모델은 이 프로젝트에서 쓸 수 없습니다. 서비스에서 쓸 수 있는 모델 이름으로 .env 의 LLM_MODEL 을 바꾸세요."
    elif code in (401, 403) or (code == 400 and "api key" in msg.lower()):
        hint = "→ 키가 올바르지 않거나 권한이 없습니다. .env 의 키가 이 서비스(LLM_PROVIDER, LLM_BASE_URL)의 것인지, 서비스 화면에서 다시 복사해 확인하세요."
    elif code == 400 and "thinking" in msg.lower():
        hint = "→ 이 모델은 thinking 설정(LLM_THINKING)을 지원하지 않거나 값이 맞지 않습니다. 설정을 빼고 다시 하세요. (Gemini 3 계열은 low 등 단계, 2.5 계열은 숫자)"
    elif code == 429 and re.search(r"limit:\s*0\b", msg + raw):
        hint = "→ 이 모델의 무료 사용 한도가 0입니다. 다른 모델로 바꾸세요."
    elif code == 429:
        hint = "→ 호출 한도(속도 제한)에 걸렸습니다. 잠시 뒤 다시 하거나 --runs 1, --only 로 호출 수를 줄이세요."
    elif code in (520, 522, 524):
        hint = "→ 앞단 게이트웨이가 AI 서버의 응답을 기다리다 끊었습니다(보통 100초 제한). 스트리밍(LLM_STREAM=on, 기본)으로 받고 있는지, 출력이 너무 길지 않은지(INTAKE_MAX_TOKENS) 확인하세요."
    elif code in (500, 502, 503, 504, 529):
        hint = "→ AI 서버가 일시적으로 혼잡하거나 오류 상태입니다(코드 문제가 아닙니다). 잠시 뒤 다시 시도하세요."
    elif code == 404:
        hint = "→ 모델 이름이나 주소가 맞는지 확인하세요."
    else:
        hint = "→ 요청 내용이나 설정을 확인하세요."
    return f"HTTP {code}: {msg}\n   {hint}"


def _retry_delay(headers, raw):
    """서버가 알려 준 대기 시간(Retry-After 헤더, 또는 본문의 retryDelay)을 초 단위로 돌려준다. 없으면 None."""
    try:
        v = headers.get("Retry-After") if headers else None
        if v and re.match(r"^\d+(\.\d+)?$", v.strip()): return float(v)
    except Exception:
        pass
    try:
        for dt in (json.loads(raw).get("error") or {}).get("details", []):
            m = re.match(r"^(\d+(?:\.\d+)?)s$", str(dt.get("retryDelay", "")))
            if m: return float(m.group(1))
    except Exception:
        pass
    return None


def _read_sse(r):
    """스트리밍 응답(data: {...} 줄들)을 한 번에 받은 응답(choices[0].message.content)과 같은 모양으로 모은다. OpenAI 호환 서비스용."""
    text, finish, usage = [], None, None
    for raw in r:
        ln = raw.decode("utf-8", "replace").strip()
        if not ln.startswith("data:"): continue
        data = ln[5:].strip()
        if data == "[DONE]": break
        try: ev = json.loads(data)
        except ValueError: continue
        if not isinstance(ev, dict): continue                     # null·숫자 같은 이벤트는 건너뛴다
        if ev.get("usage"): usage = ev["usage"]
        for ch in ev.get("choices") or []:
            if not isinstance(ch, dict): continue
            c = (ch.get("delta") or {}).get("content")
            if isinstance(c, list): c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
            if c: text.append(c)
            if ch.get("finish_reason"): finish = ch["finish_reason"]
    return {"choices": [{"message": {"content": "".join(text)}, "finish_reason": finish}], "usage": usage or {}}


def _post(url, headers, body, timeout, waits, on_retry=None, stream=False):
    """stream=True: 응답을 조금씩 받는다. 앞단 게이트웨이(Cloudflare 등)는 첫 응답이 100초 넘게 없으면 524 로 끊기 때문에 출력이 긴 요청에 필요하다."""
    n = len(waits)
    if stream: body = {**body, "stream": True}
    for attempt in range(n + 1):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={"user-agent": UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = _read_sse(r) if stream else json.loads(r.read().decode("utf-8"))
            ch = (resp.get("choices") or [{}])[0] if stream else {}
            if not (stream and not (ch.get("message") or {}).get("content") and not ch.get("finish_reason")):
                return resp
            err = TransientLLMError("응답이 아무 내용 없이 중간에 끊겼습니다(앞단 게이트웨이의 시간 제한일 수 있음)")     # 모델이 오래 생각하다 연결이 끊긴 경우: 다시 시도하면 되는 일이 많다
            if attempt >= min(n, 1): raise err                  # 같은 요청은 한 번만 다시 시도한다 (매번 2분씩 걸리고 결과도 같다).
            wait = waits[attempt]; why = "응답 끊김"
        except (TimeoutError, ConnectionError, http.client.HTTPException) as e:                     # 받는 도중 시간 초과·연결 끊김
            err = TransientLLMError(f"연결이 끊겼거나 응답이 늦습니다: {type(e).__name__}")
            if attempt == n: raise err
            wait = waits[attempt]; why = "연결 끊김"
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            hint = "google" if ("googleapis" in url or "/v1beta/" in url) else ""
            zero = e.code == 429 and re.search(r"limit:\s*0\b", raw)
            if e.code not in RETRYABLE or zero:
                err = FatalLLMError(_explain(e.code, raw, hint))
                err.model_issue = bool(zero or (e.code == 404 and hint == "google")); raise err
            err = TransientLLMError(_explain(e.code, raw, hint))
            if attempt == n: raise err
            wait = min(max(waits[attempt], _retry_delay(e.headers, raw) or 0), 120); why = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            err = TransientLLMError(f"연결 실패: {e.reason}")
            if attempt == n: raise err
            wait = waits[attempt]; why = "연결 실패"
        if on_retry: on_retry(attempt + 1, n, wait, why)
        time.sleep(wait)


def _call_one(provider, model, key, system, user, max_tokens, url, timeout, waits, on_retry, thinking=None, images=None):
    u = url(model) if callable(url) else (url.replace("{model}", model) if isinstance(url, str) else url)
    if provider == "anthropic":
        content = user if not images else [{"type": "text", "text": user}] + [{"type": "image", "source": {"type": "base64", "media_type": im["mime"], "data": im["b64"]}} for im in images]
        body = {"model": model, "max_tokens": max_tokens, "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}], "messages": [{"role": "user", "content": content}]}
        resp = _post(u or ANTHROPIC_URL, {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}, body, timeout, waits, on_retry)
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"), _usage(resp, "anthropic")
    if provider == "google":
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}] + [{"inline_data": {"mime_type": im["mime"], "data": im["b64"]}} for im in (images or [])]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0}}
        if thinking is not None and str(thinking) != "":   # 생각(thinking) 정도 조절 (선택). 숫자면 thinkingBudget(2.5 계열), 글자면 thinkingLevel(3 계열)
            try: body["generationConfig"]["thinkingConfig"] = thinking_config(thinking)
            except ValueError as e: raise FatalLLMError(str(e))
        resp = _post(u or GOOGLE_URL.format(model=model), {"content-type": "application/json", "x-goog-api-key": key}, body, timeout, waits, on_retry)
        cands = resp.get("candidates") or []
        if not cands:
            why = (resp.get("promptFeedback") or {}).get("blockReason") or "응답 후보 없음"
            raise RuntimeError(f"Gemini 가 응답하지 않음: {why}")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise RuntimeError(f"Gemini 응답이 비어 있음 (finishReason={cands[0].get('finishReason')}). max_tokens 를 늘려 보세요. (생각 토큰이 출력 한도를 쓰는 경우가 많습니다: --thinking low)")
        return text, _usage(resp, "google")
    if provider == "openai":                                  # OpenAI 호환 (OpenAI, Groq, OpenRouter, Together, DeepSeek, Mistral, Azure 호환 주소 등)
        content = user if not images else [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": f"data:{im['mime']};base64,{im['b64']}"}} for im in images]
        sysmsg = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if os.environ.get("LLM_CACHE_CONTROL", "").strip().lower() in ("on", "1", "true") else system
        body = {"model": model, "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": content}]}
        body[os.environ.get("LLM_MAX_TOKENS_PARAM") or "max_tokens"] = max_tokens          # 새 OpenAI 모델은 max_completion_tokens 를 요구한다
        if os.environ.get("LLM_TEMPERATURE"): body["temperature"] = float(os.environ["LLM_TEMPERATURE"])      # 일부 모델은 temperature 를 받지 않으므로 지정했을 때만 보낸다
        if thinking: body["reasoning_effort"] = str(thinking)
        if os.environ.get("LLM_EXTRA_BODY"):                    # 서비스마다 다른 추가 요청 값(생각 줄이기 등)을 코드 수정 없이 .env 로 넣는다. 예: LLM_EXTRA_BODY={"reasoning_effort":"low"}
            try: body.update(json.loads(os.environ["LLM_EXTRA_BODY"]))
            except ValueError: raise FatalLLMError("LLM_EXTRA_BODY 는 JSON 객체여야 합니다. 예: {\"reasoning_effort\":\"low\"}")
        base = (os.environ.get("LLM_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
        stream = os.environ.get("LLM_STREAM", "on").strip().lower() not in ("off", "0", "false", "no")      # 기본은 스트리밍 (게이트웨이의 100초 제한 때문)
        if not os.environ.get("LLM_BASE_URL"):
            import hashlib
            body["prompt_cache_key"] = "noti-intake-" + hashlib.sha1(system.encode("utf-8")).hexdigest()[:16]      # 같은 프롬프트의 요청이 같은 캐시로 가도록 (OpenAI 자동 캐시)
        if stream and (not os.environ.get("LLM_BASE_URL") or os.environ.get("LLM_STREAM_USAGE", "").strip().lower() in ("on", "1", "true")):
            body["stream_options"] = {"include_usage": True}                # 스트리밍 응답에도 토큰 사용량을 받는다 (로그의 입력·캐시·출력·생각 토큰)
        resp = _post(u or base + "/chat/completions", {"content-type": "application/json", "authorization": "Bearer " + key}, body, timeout, waits, on_retry, stream=stream)
        ch = (resp.get("choices") or [{}])[0]
        msg = (ch.get("message") or {}).get("content")
        text = "".join(x.get("text", "") for x in msg if isinstance(x, dict)) if isinstance(msg, list) else (msg or "")
        if not text.strip():
            raise RuntimeError(f"응답이 비어 있음 (finish_reason={ch.get('finish_reason')}). max_tokens 를 늘려 보세요.")
        return text, _usage(resp, "openai")
    raise ValueError(f"알 수 없는 provider: {provider}")


def call_llm(provider, model, key, system, user, max_tokens=12000, url=None, timeout=300, retries=None, waits=None, on_retry=None, fallbacks=None, on_fallback=None, info=None, thinking=None, images=None):
    """system 지시와 user 입력을 보내고 응답 텍스트를 돌려준다. (모델은 하나만 쓴다. 모델 대체는 하지 않는다)

    waits: 혼잡·한도 오류 때 기다릴 시간 목록(초). 기본 RETRY_WAITS. retries=0 이면 재시도하지 않는다.
    on_retry(회차, 전체, 대기초, 이유): 재시도 전에 호출된다. (진행 상황 표시용)
    url: 문자열 또는 함수(model -> url). 테스트용.
    info: dict 를 주면 응답한 모델(model), 걸린 시간(elapsed, 초), 재시도 대기(waited, 초), 사용량(usage), 생각 설정(thinking)을 넣어 준다.
    thinking: Google 모델의 생각 정도. "minimal"/"low"/"medium"/"high" 또는 숫자(thinkingBudget). 기본은 .env 의 LLM_THINKING, 없으면 지정 안 함.
    images: [{"mime": "image/png", "b64": base64 글자}, …] 를 주면 글 뒤에 그림으로 함께 보낸다 (코드·실행 화면 스크린샷 등)."""
    if waits is None: waits = [] if retries == 0 else (RETRY_WAITS[:retries] if retries else RETRY_WAITS)
    th = thinking if thinking is not None else os.environ.get("LLM_THINKING") or None      # 생각 정도: 인자 > .env(LLM_THINKING) > 모델 기본값
    t0, waited = time.time(), [0.0]
    def _retry(i, n, wait, why):
        waited[0] += wait
        if on_retry: on_retry(i, n, wait, why)
    out, usage = _call_one(provider, model, key, system, user, max_tokens, url, timeout, waits, _retry, th, images)
    if info is not None: info.update(model=model, elapsed=time.time() - t0, waited=waited[0], usage=usage, thinking=th)
    return out


def _get(url, headers, timeout=60):
    req = urllib.request.Request(url, headers={"user-agent": UA, **headers}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        if e.code in (400, 401, 403): raise RuntimeError(f"키가 올바르지 않거나 권한이 없습니다 (HTTP {e.code}): {msg}")
        raise RuntimeError(f"HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"연결 실패: {e.reason}")


def list_google_models(key, url=None):
    """내 키로 조회되는 모델 중 generateContent 를 지원하는 것: [(모델 id, 표시 이름)]"""
    base, out, token = url or GOOGLE_MODELS_URL, [], None
    for _ in range(20):                                         # 페이지가 여러 개일 수 있다
        u = f"{base}?pageSize=1000" + (f"&pageToken={token}" if token else "")
        d = _get(u, {"x-goog-api-key": key})
        for m in d.get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append((m["name"].split("/", 1)[-1], m.get("displayName", "")))
        token = d.get("nextPageToken")
        if not token: break
    return out


def list_openai_models(key, base=None):
    """OpenAI 호환 서비스에서 내 키로 보이는 모델 id 목록 (GET {주소}/models). 서비스에 따라 지원하지 않을 수 있다."""
    b = (base or os.environ.get("LLM_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
    d = _get(b + "/models", {"authorization": "Bearer " + key})
    return sorted(m.get("id", "") for m in (d.get("data") or d.get("models") or []) if isinstance(m, dict) and m.get("id"))


_SKIP = ("image", "tts", "live", "audio", "embedding", "vision", "robotics", "computer", "imagen", "veo", "aqa", "gemma", "learnlm", "research", "customtools", "native", "latest")


def save_model_to_env(model, path=None, var="LLM_MODEL"):
    """.env 의 LLM_MODEL(또는 var) 을 갱신한다 (없으면 추가). 저장한 파일 경로를 돌려준다."""
    path = path or next((os.path.join(d, ".env") for d in (os.getcwd(), HERE) if os.path.isfile(os.path.join(d, ".env"))), os.path.join(HERE, ".env"))
    lines = open(path, encoding="utf-8-sig").read().splitlines() if os.path.isfile(path) else []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(export\s+)?" + re.escape(var) + r"\s*=", ln): lines[i] = f"{var}={model}"; break
    else: lines.append(f"{var}={model}")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return path


def resolve(provider=None, model=None):
    """(provider, model, key) 를 정한다. 없으면 SystemExit 로 안내."""
    load_dotenv()
    p = detect_provider(provider)
    if not p: raise SystemExit("AI 키를 찾지 못했습니다. .env 에 키 한 줄(GEMINI_API_KEY= / OPENAI_API_KEY= / ANTHROPIC_API_KEY= / LLM_API_KEY= 중 아무거나)을 적으세요. 키의 앞부분(AIza·AQ. → 구글, sk- → OpenAI, sk-ant- → Claude)으로 제공자를 자동으로 정하고 모델은 기본 모델을 씁니다.")
    key = get_key(p)
    if not key: raise SystemExit(key_help(p))
    m = model or os.environ.get("LLM_MODEL") or (None if (p == "openai" and os.environ.get("LLM_BASE_URL")) else DEFAULT_MODELS.get(p))             # 모델을 적지 않으면 제공자별 기본 모델을 쓴다 (키만 있으면 동작)
    if p == "openai" and not os.environ.get("LLM_BASE_URL"): print("안내: LLM_BASE_URL 이 없어 OpenAI 주소를 씁니다. 다른 서비스면 .env 에 LLM_BASE_URL=서비스 주소 를 적으세요.")
    if not m: raise SystemExit("모델 이름이 필요합니다. .env 에 LLM_MODEL=모델이름 을 적으세요.")
    return p, m, key


# ====================================================================================================
# AI 출력 읽기
# AI 출력(한 줄에 JSON 하나)을 읽는다.
# ====================================================================================================
def parse_lines(text):
    """(결과 목록, 형식 오류 줄 목록)"""
    rows, bad = [], []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("```"): continue
        d = _load(ln)
        if isinstance(d, dict) and "id" in d: rows.append(_clean_row(d)); continue
        bad.append(ln[:50])
    return rows, bad


_REVIEW_LISTS = ("정리", "복구", "채움", "조언", "확인필요", "참고")


def _clean_row(d):
    """모델이 틀린 모양(review 가 null·글, payload 가 글, 제목이 숫자 등)으로 내도 뒤 단계가 죽지 않게 모양만 바로잡는다. 내용은 건드리지 않는다."""
    d["id"] = str(d.get("id"))
    rv = d.get("review")
    if not isinstance(rv, dict): rv = {}
    for k in _REVIEW_LISTS:
        if not isinstance(rv.get(k), list): rv[k] = [] if rv.get(k) in (None, "") else [rv[k]]
    d["review"] = rv
    p = d.get("payload")
    if p is not None and not isinstance(p, dict):
        d["payload"] = None
        rv["상태"] = "보류"; rv["보류사유"] = rv.get("보류사유") or "AI 출력의 payload 모양이 올바르지 않음"
    elif isinstance(p, dict):
        for k in ("title", "problemType", "description"):
            if k in p and p[k] is not None and not isinstance(p[k], str): p[k] = str(p[k])
    return d


def _load(ln):
    """JSON 한 줄을 읽는다. 모델이 마지막 닫는 괄호 }를 한두 개 빠뜨린 경우(긴 출력에서 가끔 생김)만 보태서 다시 읽는다.
    복구한 결과도 스키마·검사를 그대로 거치므로, 내용이 모자라면 그 단계에서 막힌다."""
    for extra in ("", "}", "}}"):
        try: return json.loads(ln + extra)
        except ValueError: continue
    return None


# ====================================================================================================
# 입력에 맞춰 프롬프트 줄이기
# 입력에 맞춰 프롬프트에서 그 입력에 쓰이지 않는 구간을 뺀다. prompt.md 자체는 바꾸지 않고, AI 를 부를 때만 줄여 보낸다 (입력 토큰 감소).
# 빼는 것: 쓰지 않는 파일 형식 규칙, 입력 종류에 맞지 않는 처리 규칙, 그림이 붙지 않았을 때의 그림 규칙.
# ====================================================================================================

_KIND_RE = re.compile(r'"입력종류":\s*"([^"]*)"')
_FMT_RE = re.compile(r'"(원본형식|표형식)":\s*"([^"]*)"')
_IMG_RE = re.compile(r"그림 \d+개|쪽 \d+장|그림이 있는 쪽")      # intake.메모에 서버가 적는 그림 첨부 안내

# 형식별 필터링 안의 블록 머리. 원본 문서 형식 → 그 형식에 필요한 블록들
_DOC_BLOCKS = {"PDF": ("[PDF]",), "워드": ("[워드",), "한글": ("[한글", "[워드"), "파워포인트": ("[파워포인트",),
               "텍스트": ("[텍스트·마크다운",), "마크다운": ("[텍스트·마크다운",)}
_ALL_DOC_HEADS = ("[PDF]", "[워드", "[파워포인트", "[한글", "[텍스트·마크다운")
_TABLE_BLOCKS = {"DB": ("[DB(SQLite)]",), "엑셀": ("[엑셀·CSV]",), "CSV": ("[엑셀·CSV]",)}
_ALL_TABLE_HEADS = ("[DB(SQLite)]", "[엑셀·CSV]")
_IMAGE_HEAD = "[그림 첨부]"


def _section(text, tag):
    return re.search(rf"<{re.escape(tag)}>\n(.*?)\n</{re.escape(tag)}>", text, re.S)


def _drop_blocks(text, tag, heads):
    """<tag> 구간 안에서 heads 로 시작하는 줄부터 다음 '[' 머리 줄(또는 구간 끝) 앞까지를 지운다."""
    m = _section(text, tag)
    if not m or not heads: return text
    out, skipping = [], False
    for line in m.group(1).split("\n"):
        if line.startswith("["):
            skipping = line.startswith(tuple(heads))
        if not skipping: out.append(line)
    return text[:m.start(1)] + "\n".join(out) + text[m.end(1):]


def kind_of_input(user):
    """user 글에 든 입력 JSON 에서 (입력종류, 원본형식, 표형식). 찾지 못하면 None."""
    k = _KIND_RE.search(user or "")
    if not k: return None, None, None
    fmts = dict(_FMT_RE.findall(user))
    return k.group(1), fmts.get("원본형식"), fmts.get("표형식")


@lru_cache(maxsize=64)
def _trim(prompt, kind, doc_fmt, table_fmt, has_images):
    if kind not in ("엑셀", "원본", "둘 다"): return prompt          # 알 수 없는 입력은 줄이지 않는다
    text = prompt
    if kind in ("원본", "둘 다"):                                    # 쓰는 문서 형식만 남긴다 (형식을 모르면 문서 형식은 모두 남김)
        keep = _DOC_BLOCKS.get(doc_fmt or "PDF")
        text = _drop_blocks(text, "형식별 필터링", tuple(h for h in _ALL_DOC_HEADS if not (keep and h.startswith(keep))) if keep else ())
    else:
        text = _drop_blocks(text, "형식별 필터링", _ALL_DOC_HEADS)
    if kind in ("엑셀", "둘 다"):                                    # 쓰는 표 형식만 남긴다
        keep = _TABLE_BLOCKS.get(table_fmt or "엑셀")
        text = _drop_blocks(text, "형식별 필터링", tuple(h for h in _ALL_TABLE_HEADS if not (keep and h.startswith(keep))) if keep else ())
    else:
        text = _drop_blocks(text, "형식별 필터링", _ALL_TABLE_HEADS)
    if not has_images: text = _drop_blocks(text, "형식별 필터링", (_IMAGE_HEAD,))
    if kind == "엑셀":
        text = _drop_blocks(text, "입력 종류별 처리", ("[원본]", "[둘 다]"))
    elif kind == "원본":
        text = _drop_blocks(text, "입력 종류별 처리", ("[엑셀]", "[둘 다]"))
    return text


def trim_prompt(prompt, user, has_images=None):
    """user 글(채점 모드 + 입력 JSON)에 맞게 줄인 프롬프트. has_images: 그림을 실제로 보내는지(서버가 알고 있으면 넘긴다). 모르면 입력 글의 그림 안내로 판단한다."""
    kind, doc_fmt, table_fmt = kind_of_input(user)
    if has_images is None: has_images = bool(_IMG_RE.search(user or ""))
    return _trim(prompt, kind, doc_fmt, table_fmt, bool(has_images))


# ====================================================================================================
# 옛 이름 호환 (모델 대체 기능은 제거되었다). 옛 코드가 import 하거나 호출해도 오류 없이 지나가도록 남긴 자리이며, 아무 일도 하지 않는다.
# call_llm 의 fallbacks·on_fallback 인자도 같은 이유로 받기만 하고 쓰지 않는다.
# ====================================================================================================
COOLDOWN = 0
_BAD = {}


def reset_cooldowns():
    _BAD.clear()


def _is_bad(provider, model):
    return False


def fallback_models(primary=None):
    return []


def rank_models(models):
    return list(models or [])


def check_google_model(key, model, url=None):
    """작은 요청을 한 번 보내 이 모델이 되는지 확인한다. (성공 여부, 설명)"""
    try:
        text = call_llm("google", model, key, "한 단어로만 답하세요.", "OK 라고만 답하세요.", 256, url, timeout=60, retries=0)
        return True, f"응답 받음: {text.strip()[:20]!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def find_working_models(key, models_url=None, url_for=None, max_try=6, want=1, log=print):
    out = []
    for m in rank_models(list_google_models(key, models_url))[:max_try]:
        ok, why = check_google_model(key, m, url_for(m) if url_for else None)
        log(f"{m}: {why}")
        if ok:
            out.append(m)
            if len(out) >= want: break
    return out


def find_working_model(key, models_url=None, url_for=None, max_try=6, log=print):
    f = find_working_models(key, models_url, url_for, max_try, 1, log)
    return f[0] if f else None


def diagnose(key, models, prompt, sample, url_for=None, thinking=None, max_tokens=12000, log=print):
    return "모델별 진단 기능은 제거되었습니다.", {}
