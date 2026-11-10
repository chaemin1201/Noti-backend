# app/inputdata/intake/checks/suggest.py
"""조건 예시: 정답 코드가 '무엇을 쓰는지' 읽어서, 그것을 사용해 작성해야 한다는 조건 하나를 만들어 준다 (승인 화면의 조건 칸에 바로 보여 줄 예시).
AI 를 부르지 않는다: 정답 코드를 규칙으로 읽으므로 즉시 나오고 비용이 없다. 정답 코드가 실제로 쓰는 것만 말하므로 정답 코드와 모순되지 않는다.
  예) np.random.random() 을 쓰는 코드 → "[필수] np.random.random() 함수를 사용한다"
      for 반복문만 쓰는 코드          → "[필수] for 반복문을 사용한다"
이미 같은 내용의 조건이 있으면 건너뛰고 그 다음으로 눈에 띄는 것을 고른다."""
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
    """코딩·디버깅 문제의 조건 예시 하나: {"text": "[필수] …", "reason": "정답 코드가 … 를 씁니다"}. 쓸 만한 것이 없으면 None.
    current: 화면의 지금 조건 목록. 이미 같은 내용이 있으면 건너뛴다."""
    p = payload or {}
    if p.get("problemType") not in ("코딩", "디버깅"): return None
    code = _strip(_code(p))
    if not code.strip(): return None
    have = " ".join(str(c) for c in (current if current is not None else p.get("problem_condition") or []))
    for text, reason, covers in _rules(code, [t for t in (p.get("test_cases") or []) if isinstance(t, dict)]):
        if re.search(covers, have, re.I): continue
        return {"text": text, "reason": reason}
    return None
