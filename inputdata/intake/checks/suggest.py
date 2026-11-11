# app/inputdata/intake/checks/suggest.py
"""조건 예시: 정답 코드가 '무엇을 쓰는지' 읽어서, 그것을 사용해 작성해야 한다는 조건 하나를 만들어 준다 (승인 화면의 조건 칸에 바로 보여 줄 예시)."""
import re

TAGS = ("필수", "금지", "허용", "출력형식")
COND_RE = re.compile(r"^\[(%s)\]\s*\S" % "|".join(TAGS))
_ORD = {1: "첫째", 2: "둘째", 3: "셋째", 4: "넷째"}
_COMMON = ("array", "asarray", "print")
_BUILTINS = ("sorted", "sort", "sum", "max", "min", "enumerate", "zip", "map", "filter", "reduce", "join", "split", "format", "round", "pow")      # for 와 늘 같이 나오는 range·len 은 예시로 쓸모가 없어 뺀다


def _code(payload):
    return "\n".join(str(c.get("code") or "") for c in ((payload or {}).get("reference_codes") or []) if isinstance(c, dict))


def _strip(code):
    """글자 값과 주석을 지워서 '코드가 실제로 쓰는 것'만 남긴다."""
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', '""', code)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', code)
    return re.sub(r"(?m)(#|//).*$", " ", code)


def _bodies(code):
    """(함수 이름, 본문 글) 목록. 파이썬은 들여쓰기, C·C++·Java 는 중괄호로 본문을 자른다."""
    out, lines = [], code.split("\n")
    for k, ln in enumerate(lines):
        m = re.match(r"(\s*)def\s+(\w+)\s*\(", ln)
        if not m: continue
        base, body = len(m.group(1)), []
        for nx in lines[k + 1:]:
            if nx.strip() and len(nx) - len(nx.lstrip()) <= base: break
            body.append(nx)
        out.append((m.group(2), "\n".join(body)))
    for m in re.finditer(r"\b(?:int|void|double|long|float|String|boolean|char|auto|bool)\s+(\w+)\s*\([^)]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{", code):
        depth, pos = 1, m.end()
        while pos < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[pos], 0); pos += 1
        out.append((m.group(1), code[m.end():pos]))
    return out


def _recursive(code):
    """자기 자신을 부르는 함수 이름 (자기 본문 안에서 자기 이름을 부를 때만). main 은 제외."""
    return next((n for n, body in _bodies(code) if n != "main" and re.search(r"\b" + re.escape(n) + r"\s*\(", body)), None)


def _rules(code, tcs):
    """(조건 글, 근거, 이미 있는지 알아볼 말) 후보를 눈에 띄는 순서로 만든다."""
    libs = list(re.finditer(r"\b(np|numpy|math|random|itertools|collections|re)\.(\w+(?:\.\w+)?)\s*\(", code))
    m = next((x for x in libs if x.group(2) not in _COMMON), None)            # array 처럼 어디에나 나오는 것은 뒤로
    if m:
        name = f"{m.group(1)}.{m.group(2)}"
        yield f"[필수] {name}() 함수를 사용한다", f"정답 코드가 {name}() 를 씁니다", re.escape(m.group(2).split(".")[-1])
    m = re.search(r"\bstd::(\w+)", code)
    if m: yield f"[필수] std::{m.group(1)} 를 사용한다", f"정답 코드가 std::{m.group(1)} 를 씁니다", re.escape(m.group(1))
    m = re.search(r"\b(ArrayList|HashMap|HashSet|LinkedList|TreeMap|Stack|Queue|StringBuilder|Optional)\b", code)
    if m: yield f"[필수] {m.group(1)} 클래스를 사용한다", f"정답 코드가 {m.group(1)} 를 씁니다", re.escape(m.group(1))
    if re.search(r"\babstract\s+class\b", code): yield "[필수] 추상 클래스를 사용한다", "정답 코드가 abstract class 를 씁니다", r"추상"
    if re.search(r"\bextends\s+\w+", code): yield "[필수] 상속(extends)을 사용한다", "정답 코드가 extends 를 씁니다", r"상속|extends"
    if re.search(r"\bimplements\s+\w+|\binterface\s+\w+", code): yield "[필수] 인터페이스를 사용한다", "정답 코드가 interface/implements 를 씁니다", r"인터페이스|interface"
    m = re.search(r"\b(\w+)\s*\(\s*(?:const\s+)?\1\s*&&\s*\w*\s*\)", code)
    if m: yield "[필수] 이동 생성자를 구현한다", "정답 코드가 이동 생성자(X&&)를 구현합니다", r"이동 ?생성자"
    m = re.search(r"\b(\w+)\s*\(\s*const\s+\1\s*&\s*\w*\s*\)", code)
    if m: yield "[필수] 복사 생성자를 구현한다", "정답 코드가 복사 생성자(const X&)를 구현합니다", r"복사 ?생성자"
    if re.search(r"\bsuper\s*[(.]", code): yield "[필수] super 로 부모를 호출한다", "정답 코드가 super 를 씁니다", r"super"
    rec = _recursive(code)
    if rec: yield "[필수] 재귀 호출을 사용한다", f"정답 코드의 {rec}() 가 자기 자신을 부릅니다", r"재귀"
    if re.search(r"\blambda\b|->\s*[\w(]", code): yield "[필수] 람다식을 사용한다", "정답 코드가 람다식을 씁니다", r"람다|lambda"
    if re.search(r"\[[^\]\n]*\bfor\b[^\]\n]*\bin\b", code): yield "[필수] 리스트 컴프리헨션을 사용한다", "정답 코드가 리스트 컴프리헨션을 씁니다", r"컴프리헨션"
    if re.search(r"\btry\s*[:{]|\bexcept\b|\bcatch\s*\(", code): yield "[필수] 예외 처리(try)를 사용한다", "정답 코드가 try 로 예외를 처리합니다", r"예외|try"
    if re.search(r"\bfor\s*[\(\w]", code): yield "[필수] for 반복문을 사용한다", "정답 코드가 for 반복문을 씁니다", r"\bfor\b|for ?(반복|문)"
    if re.search(r"\bwhile\s*[\(\w]", code): yield "[필수] while 반복문을 사용한다", "정답 코드가 while 반복문을 씁니다", r"\bwhile\b|while ?(반복|문)"
    for fn in _BUILTINS:
        if re.search(r"(?<![\w.])" + fn + r"\s*\(", code) or re.search(r"\." + fn + r"\s*\(", code):
            yield f"[필수] {fn}() 함수를 사용한다", f"정답 코드가 {fn}() 를 씁니다", re.escape(fn)
            break
    m = next((x for x in libs if x.group(2) in _COMMON), None)
    if m:
        name = f"{m.group(1)}.{m.group(2)}"
        yield f"[필수] {name}() 함수를 사용한다", f"정답 코드가 {name}() 를 씁니다", re.escape(m.group(2).split(".")[-1])
    digs = {len(x) for t in tcs for x in re.findall(r"\d+\.(\d+)", str(t.get("expected_output") or "")) if isinstance(t, dict)}
    if len(digs) == 1 and next(iter(digs)) in _ORD:
        n = next(iter(digs)); yield f"[출력형식] 소수점 {_ORD[n]} 자리까지 출력한다", f"기대 출력이 모두 소수점 {n}자리입니다", r"소수점"


def example_condition(payload, current=None):
    """코딩·디버깅 문제의 조건 예시 하나: {"text": "[필수] …", "reason": "정답 코드가 … 를 씁니다"}. 쓸 만한 것이 없으면 None."""
    p = payload or {}
    if p.get("problemType") not in ("코딩", "디버깅"): return None
    code = _strip(_code(p))
    if not code.strip(): return None
    have = " ".join(str(c) for c in (current if current is not None else p.get("problem_condition") or []))
    for text, reason, covers in _rules(code, [t for t in (p.get("test_cases") or []) if isinstance(t, dict)]):
        if re.search(covers, have, re.I): continue
        return {"text": text, "reason": reason}
    return None


# ----------------------------------------------------------------------------------------------------
# 조건 자동 추가: AI 가 제안한 조건(사용해야 할 기능 · 출력 형식)을 정답 코드·기대 출력과 맞는지 서버가 확인하고 problem_condition 에 넣는다.
# ----------------------------------------------------------------------------------------------------

_GENERIC = {"or", "and", "the", "is", "in", "of", "to", "을", "를"}
_KO_FEATURES = [                                     # (조건 속 말, 정답 코드에서 그것을 쓰는지 알아보는 식)
    (r"재귀", lambda c: bool(_recursive(c))),
    (r"람다|lambda", lambda c: bool(re.search(r"\blambda\b|->\s*[\w(]", c))),
    (r"컴프리헨션", lambda c: bool(re.search(r"\[[^\]\n]*\bfor\b[^\]\n]*\bin\b", c))),
    (r"예외|try", lambda c: bool(re.search(r"\btry\s*[:{]|\bexcept\b|\bcatch\s*\(", c))),
    (r"상속|extends", lambda c: bool(re.search(r"\bextends\s+\w+|\bclass\s+\w+\s*\(\s*\w+|\bclass\s+\w+\s*:\s*(?:public|protected|private)\b", c))),
    (r"인터페이스|interface", lambda c: bool(re.search(r"\binterface\s+\w+|\bimplements\s+\w+", c))),
    (r"추상", lambda c: bool(re.search(r"\babstract\b|\bABC\b|abstractmethod|=\s*0\s*;", c))),
    (r"슬라이싱", lambda c: bool(re.search(r"\[[^\]\n]*:[^\]\n]*\]", c))),
    (r"딕셔너리|dict", lambda c: bool(re.search(r"\bdict\s*\(|\{[^{}\n]*:[^{}\n]*\}", c))),
    (r"집합|set", lambda c: bool(re.search(r"\bset\s*\(|\bHashSet\b|\bstd::set\b", c))),
    (r"while", lambda c: bool(re.search(r"\bwhile\s*[\(\w]", c))),
    (r"for|반복", lambda c: bool(re.search(r"\b(?:for|while)\s*[\(\w]", c))),
    (r"조건문|if", lambda c: bool(re.search(r"\bif\s*[\(\w]", c))),
    (r"클래스|class", lambda c: bool(re.search(r"\bclass\s+\w+", c))),
    (r"함수", lambda c: bool(re.search(r"\bdef\s+\w+|\b(?:int|void|double|long|float|String|boolean|char|auto|bool)\s+\w+\s*\(", c))),
    (r"정렬|sort", lambda c: bool(re.search(r"sort", c))),
]


def _feature_ok(body, code):
    """'필수' 조건 글이 정답 코드가 실제로 쓰는 것을 말하는가. 영문 이름(np.sum, ArrayList)이 있으면 모두 코드에 있어야 하고, 한글 말(재귀, 반복문)이면 코드에서 알아봐야 한다."""
    idents = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", body) if len(w) >= 2 and w.lower() not in _GENERIC]
    if idents:
        return all(re.search(r"(?<![\w])" + re.escape(w.split(".")[-1]) + r"(?![\w])", code) for w in idents)
    hits = [test for k, test in _KO_FEATURES if re.search(k, body, re.I)]
    if hits: return any(t(code) for t in hits)                       # 말한 기능을 정답 코드가 실제로 쓰는가
    return True                                                       # 확인할 방법이 없는 표현(위임 생성자, 깊은 복사 …)은 정답 코드와 모순되지 않으면 받아들인다 (사람이 화면에서 지울 수 있음)


def _forbid_ok(body, code):
    """'금지' 조건 글이 정답 코드와 모순되지 않는가: 금지한 것을 정답 코드가 쓰고 있으면 안 된다 (영문 이름이 모두 코드에 없어야 하고, 한글 말이면 코드에서 쓰지 않아야 한다)."""
    idents = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", body) if len(w) >= 2 and w.lower() not in _GENERIC]
    if idents:                                                        # 금지한 이름이 모두 정답 코드에 있으면 모순 (일부만 있으면 문맥에 나온 이름일 수 있어 받아들인다)
        return not all(re.search(r"(?<![\w])" + re.escape(w.split(".")[-1]) + r"(?![\w])", code) for w in idents)
    hit = [test for k, test in _KO_FEATURES if re.search(k, body, re.I)]
    return not any(t(code) for t in hit)                              # 알아볼 수 없는 표현은 모순이 아니므로 받아들인다


def _allow_ok(body):
    """'허용' 조건 글이 무엇을 허용하는지 알아볼 수 있는가 (허용은 정답 코드에 없어도 되므로 영문 이름이나 아는 한글 말이 하나라도 있으면 된다)."""
    return bool([w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", body) if len(w) >= 2 and w.lower() not in _GENERIC]) or any(re.search(k, body, re.I) for k, _ in _KO_FEATURES)


def _outs(tcs):
    return [str(t.get("expected_output") or "").strip() for t in tcs if isinstance(t, dict) and str(t.get("expected_output") or "").strip()]


def _format_ok(body, tcs):
    """'출력형식' 조건 글이 기대 출력들에서 확인되는가 (확인할 수 없으면 False: 맞지 않는 형식 조건이 학생에게 보이는 것보다 빠지는 것이 낫다)."""
    outs = _outs(tcs)
    if not outs: return True                                          # 기대 출력이 없으면 어긋남을 확인할 수 없으므로 받아들인다
    if re.search(r"리스트|배열|list", body, re.I): return all(o.startswith("[") and o.endswith("]") for o in outs)
    m = re.search(r"소수점\s*(?:아래\s*)?(\d|첫째|둘째|셋째|넷째|한|두|세|네)", body)
    if m:
        n = {"첫째": 1, "둘째": 2, "셋째": 3, "넷째": 4, "한": 1, "두": 2, "세": 3, "네": 4}.get(m.group(1)) or int(m.group(1))
        return all(re.search(r"\d+\.%s(?!\d)" % ("[0-9]" * n), o) for o in outs)
    if re.search(r"한\s*줄에\s*하나|줄마다|각\s*줄|줄바꿈", body): return all("\n" in o for o in outs)
    if re.search(r"한\s*줄", body): return all("\n" not in o for o in outs)
    if re.search(r"쉼표|콤마", body): return all("," in o for o in outs)
    if re.search(r"공백", body): return all(" " in o for o in outs)
    if re.search(r"정수", body): return all(re.fullmatch(r"-?\d+", ln.strip()) for o in outs for ln in o.split("\n") if ln.strip())
    return True                                                       # 알아볼 수 없는 형식 표현은 기대 출력과 어긋남을 확인할 수 없으므로 받아들인다


def _format_rule(tcs):
    """기대 출력에서 읽은 출력형식 조건 하나 (없으면 None): (조건 글, 근거)."""
    outs = _outs(tcs)
    if not outs: return None
    if all(o.startswith("[") and o.endswith("]") for o in outs): return "[출력형식] 리스트 형태로 출력한다", "기대 출력이 모두 리스트 모양입니다"
    digs = {len(x) for o in outs for x in re.findall(r"\d+\.(\d+)", o)}
    if len(digs) == 1 and next(iter(digs)) in _ORD:
        n = next(iter(digs)); return f"[출력형식] 소수점 {_ORD[n]} 자리까지 출력한다", f"기대 출력이 모두 소수점 {n}자리입니다"
    return None


def _words(t):
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|[가-힣]{2,}", re.sub(r"^\[[^\]]+\]", "", str(t))) if w not in _GENERIC}


def _dup(text, have):
    a = _words(text)
    for h in have:
        b = _words(h)
        if a and b and len(a & b) >= max(1, -(-6 * min(len(a), len(b)) // 10)): return True
    return False


_TAG_ONLY = re.compile(r"\[?(필수|금지|허용|출력형식)\]?")


def _flat(x):
    """AI 가 낸 제안의 여러 모양(글, 겹친 목록, {"[태그]": 글}, {"태그","내용"}, {"항목": "[태그] 글"})을 '[태그] 글' 문자열들로 편다."""
    if isinstance(x, (list, tuple)):
        for y in x: yield from _flat(y)
    elif isinstance(x, dict):
        tag = next((str(x[k]).strip("[] ") for k in ("태그", "tag", "종류", "type") if x.get(k)), None)
        txt = next((str(x[k]) for k in ("내용", "조건", "text", "content", "설명") if x.get(k)), None)
        if tag and txt: yield f"[{tag}] {txt}"; return
        for k, v in x.items():
            if _TAG_ONLY.fullmatch(str(k).strip()) and isinstance(v, str): yield f"[{str(k).strip('[] ')}] {v}"
            else: yield from _flat(v)
    elif x is not None: yield str(x)


def _proposals(raw):
    """AI 의 review.조건제안 을 [(태그, 전체 글)] 로 (태그는 필수·금지·허용·출력형식만)."""
    out = []
    for x in _flat(raw):
        m = re.match(r"^\[(필수|금지|허용|출력형식)\]\s*(\S.*)$", x.strip())
        if m: out.append((m.group(1), f"[{m.group(1)}] {m.group(2).strip()}"))
    return out


MIN_KEEP = 2                                          # 문제에 조건이 이미 이만큼 있으면 자동으로 더하지 않는다 (0개·1개일 때만 더함)
MAX_AUTO = 2                                          # 자동으로 더하는 조건은 문제당 최대 2개 (종류는 필수·금지·허용·출력형식 중 서로 다른 것)


def apply_conditions(payload, review):
    """코딩·디버깅 문제에 AI 가 정답 코드를 보고 판단한 조건을 최대 2개 자동으로 더한다 (제자리 수정). 더한 조건 글의 목록을 돌려준다."""
    rv = review if isinstance(review, dict) else {}
    proposed = _proposals(rv.pop("조건제안", None))
    p = payload if isinstance(payload, dict) else {}
    if p.get("problemType") not in ("코딩", "디버깅"): return []
    code = _strip(_code(p))
    if not code.strip(): return []
    tcs = [t for t in (p.get("test_cases") or []) if isinstance(t, dict)]
    cur = [str(c) for c in (p.get("problem_condition") or [])]
    if len(cur) >= MIN_KEEP: return []                              # 이미 조건이 2개 이상이면 더하지 않는다
    added = []                                                      # (태그, 조건 글, 근거)

    def put(tag, text, why):
        if len(added) >= MAX_AUTO or _dup(text, cur + [a[1] for a in added]): return False
        added.append((tag, text, why)); return True

    def verdict(tag, body):
        if tag == "필수": return _feature_ok(body, code), "AI 가 정답 코드를 보고 제안했고, 정답 코드가 그 기능을 쓰는 것을 서버가 확인함"
        if tag == "금지": return _forbid_ok(body, code), "AI 가 제안했고, 정답 코드가 그것을 쓰지 않는 것을 서버가 확인함"
        if tag == "허용": return _allow_ok(body), "AI 가 제안했고, 허용하는 대상을 서버가 알아봄"
        return _format_ok(body, tcs), "AI 가 제안했고, 기대 출력이 그 형식인 것을 서버가 확인함"

    good = []
    for tag, text in proposed:
        ok, why = verdict(tag, re.sub(r"^\[[^\]]+\]\s*", "", text))
        if ok: good.append((tag, text, why))
    kinds = set()
    for tag, text, why in good:                                     # 서로 다른 종류를 먼저
        if tag not in kinds and put(tag, text, why): kinds.add(tag)
    for tag, text, why in good: put(tag, text, why)                 # 모자라면 같은 종류로
    if len(added) < MAX_AUTO and not any(a[0] == "필수" for a in added):
        desc = str(p.get("description") or "")
        for text, reason, covers in _rules(code, tcs):
            if re.search(covers, " ".join(cur), re.I): continue
            if not re.search(covers, desc, re.I): continue          # 문제 설명이 말하지 않은 기능(map·for 같은 풀이 습관)을 규칙이 강제하지 않는다
            if put("필수", text, reason): break
    if len(added) < MAX_AUTO and not any(a[0] == "출력형식" for a in added):
        r = _format_rule(tcs)
        if r: put("출력형식", r[0], r[1])
    if not added: return []
    p["problem_condition"] = cur + [a[1] for a in added]
    if isinstance(review, dict):
        review["AI추가조건"] = [a[1] for a in added]                  # 화면이 어느 조건이 AI 가 추가한 것인지 알 수 있게
        review["채움"] = list(review.get("채움") or []) + [{"항목": "problem_condition", "내용": "; ".join(a[1] for a in added) + " 를 AI 가 정답 코드를 보고 추가함 (화면에서 지우거나 바꿀 수 있음)",
                                                          "근거": "; ".join(a[2] for a in added), "검증": "손 추적"}]
    return [a[1] for a in added]
