"""엑셀로 정리된 문제를 읽어 문제(행) 하나씩의 레코드로 만들고, 등록 필수 항목이 비어 있는지 점검한다."""
import json, re


class _LazyOpenpyxl:
    """openpyxl 은 엑셀을 실제로 읽을 때만 불러온다. 서버에 이 패키지가 없어도 서버(와 문서·한글·PDF 처리)는 정상으로 뜨고, 엑셀을 올렸을 때만 안내가 나간다."""
    def __getattr__(self, name):
        try:
            import openpyxl as _m
        except ImportError:
            raise SystemExit("엑셀을 읽으려면 서버에 openpyxl 패키지가 필요합니다 (pip install openpyxl). 서버 관리자에게 문의하세요.")
        return getattr(_m, name)


openpyxl = _LazyOpenpyxl()

from . import images as safety      # 업로드 파일 안전 점검(images.py 안)

SYN = {
    "이름": ["이름", "문제 이름", "문제이름", "제목", "문제 제목"],
    "유형": ["유형", "문제 유형"], "난이도": ["난이도", "문제 난이도"],
    "조건": ["조건", "문제 조건"], "설명": ["설명", "문제 설명"],
    "부제목": ["부제목"], "문제의도": ["문제의도", "출제의도", "출제 의도"],
    "제공코드": ["제공코드", "제공 코드", "문제 제공코드", "문제 제공 코드"], "정답코드": ["정답코드", "정답 코드", "전체 코드", "전체코드", "문제 정답코드"],
    "입력": ["입력", "입력1"], "출력": ["출력", "예상 출력", "출력1"], "언어": ["언어"], "이미지": ["이미지"],
    "입력2": ["입력2"], "출력2": ["출력2"], "입력3": ["입력3"], "출력3": ["출력3"],
    "보기": ["보기", "객관식 보기"], "정답": ["정답", "단답형 정답", "주관식 정답"], "채점기준": ["채점기준", "채점 기준"],
    "비고": ["비고"],
    "태그": ["태그", "태그들", "키워드"],
}
TYPES = {"코딩", "디버깅", "객관식", "주관식", "단답형"}
# DB 열 이름은 영어인 경우가 많다 (예: 이 서비스의 problem 표: title, description, difficulty, problem_type …)
for _k, _names in {"이름": ["title", "name", "problem_title"], "설명": ["description", "desc", "problem_description", "content"], "난이도": ["difficulty", "level"],
                   "유형": ["problem_type", "problemtype", "type", "kind"], "조건": ["condition", "conditions", "problem_condition"],
                   "제공코드": ["base_code", "starter_code", "provided_code"], "정답코드": ["reference_code", "reference_codes", "answer_code", "solution", "solution_code"],
                   "입력": ["input", "test_input"], "출력": ["expected_output", "output", "test_output"], "보기": ["options", "choices"],
                   "정답": ["answer", "answers", "correct_answers", "answer_text"], "언어": ["language", "lang"], "부제목": ["subtitle"], "문제의도": ["intent"],
                   "채점기준": ["grading_criteria"], "태그": ["tags", "tag"], "비고": ["note", "notes"]}.items():
    SYN[_k] = SYN.get(_k, []) + _names

UNKNOWN_COLS_MEMO = "인식하지 못해 무시한 열: "      # 이 열의 값은 AI 에게 전달되지 않는다. 열 이름을 SYN 에 있는 이름으로 바꾸거나 SYN 에 추가해야 한다
REQUIRED = {                      # 유형별 필수 (사용자가 정한 기준)
    "코딩": ["이름", "유형", "설명", "정답코드", "테스트결과"],
    "디버깅": ["이름", "유형", "설명", "정답코드", "제공코드", "테스트결과"],
    "객관식": ["이름", "유형", "설명", "보기"],
    "주관식": ["이름", "유형", "설명", "정답"],
    "단답형": ["이름", "유형", "설명", "정답"],
}


def canon(header):
    h = re.sub(r"\s+", " ", str(header or "")).strip()
    for k, names in SYN.items():
        if h.lower() in [n.lower() for n in names]: return k
    m = re.match(r"^학생 실행 (코드|결과) (\d+)$", h)
    if m: return ("실행코드" if m.group(1) == "코드" else "실행결과") + m.group(2)
    return None


def find_header(ws, scan=12):
    for r in range(1, scan + 1):
        mapped = {c.column: canon(c.value) for c in ws[r] if canon(c.value)}
        if "설명" in mapped.values() and "이름" in mapped.values():
            return r, mapped
    raise SystemExit(f"{ws.title}: 이름/설명 머리글을 찾지 못했습니다.")


def infer_type(f):
    """유형 열이 비어 있을 때의 단순 추정 (보고용). 의미 판단은 AI 가 다시 한다."""
    d = f.get("설명", "")
    if f.get("보기"): return "객관식"
    if f.get("제공코드"): return "디버깅"
    if re.search(r"(출력\s*)?결과를?\s*작성", d): return "단답형"
    if re.search(r"(기술|설명)\s*(을\s*)?(하|해)\s*(시오|보)", d) and "프로그램" not in d: return "주관식"
    if f.get("정답코드") or f.get("입력") or f.get("출력") or any(f.get(f"실행결과{i}") for i in (1, 2, 3)): return "코딩"
    return None                                  # 코드 단서가 없으면 코딩으로 단정하지 않고 AI 가 본문을 보고 판단한다 (O/X·연결하기 같은 문제를 코딩으로 오해하지 않게)


def intake_row(f, source):
    notes = []
    given = f.get("유형", "")
    ptype = given if given in TYPES else infer_type(f)
    if given and given not in TYPES: notes.append(f"알 수 없는 유형 값: {given!r}")
    inferred = given not in TYPES

    has_test = bool(f.get("출력")) or any(f.get(f"실행결과{i}") for i in (1, 2, 3))
    present = {"이름": bool(f.get("이름")), "유형": not inferred, "설명": bool(f.get("설명")),
               "정답코드": bool(f.get("정답코드")), "제공코드": bool(f.get("제공코드")),
               "테스트결과": has_test, "보기": bool(f.get("보기")),
               "정답": bool(f.get("정답") or f.get("출력"))}      # 예전 엑셀은 정답을 출력 열에 적었음
    missing = [x for x in REQUIRED[ptype] if not present[x]] if ptype else []
    if not ptype: notes.append("유형 열이 비어 있고 코드 단서도 없음 → 본문을 보고 유형을 판단(코딩으로 단정하지 말 것)")

    d = f.get("설명", "")
    hold = bool(re.search(r"실행 테스트 불가|테스트 불가", d)) and len(d) < 120
    if hold: notes.append("설명이 상태 메시지뿐 → 보류 후보")
    if re.search(r"방법\s*\d|풀이\s*\d", d + f.get("조건", "")): notes.append("풀이 방식이 여러 개 → 문제 분할 후보")
    if f.get("이미지") not in (None, "", "X"): notes.append(f"이미지 있음: {f['이미지']}")
    if re.search(r"터틀|turtle|\.mp4|그림과 같이", d, re.I): notes.append("그래픽 출력 가능성 → 테스트 케이스 없음 예상")
    if "입력" in f and f.get("입력") == "" and has_test and ptype in ("코딩", "디버깅"):
        pass
    return {"유형": ptype, "유형추정": inferred, "필수누락": missing, "보류후보": hold, "메모": notes}


SKIP_SHEETS = {"안내", "예시", "설명"}      # 템플릿의 안내·예시 시트는 문제로 읽지 않는다 (--include-examples 로 포함 가능)


def _csv_rows(path):
    """CSV/TSV 를 읽어 (머리글 행 번호, 열 매핑, 행 목록) 형태로 돌려준다."""
    import csv
    delim = "\t" if path.lower().endswith((".tsv", ".tab")) else ","
    import io
    return list(csv.reader(io.StringIO(safety.read_text_file(path), newline=""), delimiter=delim))      # UTF-8·UTF-16·CP949 모두 읽는다


DUP_NAME_MEMO = "같은 이름이 여러 번 나옴 "      # 프롬프트의 보류 조건("같은 이름이 중복됨")이 이 메모를 보고 판단한다. AI 는 문제를 하나씩만 보므로 서버가 알려 줘야 한다


def mark_duplicate_names(rows):
    """같은 이름(이름 열)이 둘 이상이면 해당 행 모두의 메모에 알린다. 이름이 같아도 설명이 다르면 서버 중복 검사는 통과하므로 여기서 잡는다."""
    where = {}
    for r in rows:
        name = (r["fields"].get("이름") or "").strip()
        if name: where.setdefault(name, []).append(r["row"])
    for r in rows:
        name = (r["fields"].get("이름") or "").strip()
        if name and len(where[name]) > 1:
            r["intake"]["메모"].append(f"{DUP_NAME_MEMO}({len(where[name])}번, 행 {', '.join(str(x) for x in where[name])})")
    return rows


DB_EXT = (".db", ".sqlite", ".sqlite3")
SQLITE_MAGIC = b"SQLite format 3\x00"
MAX_DB_ROWS = 1000                  # 표 하나에서 읽는 최대 행 수 (작업 전체 한도는 INTAKE_MAX_PROBLEMS 가 따로 제한한다)
MAX_DB_CELL = 200_000               # 칸 하나의 최대 글자 수


def _db_value(v):
    """DB 값을 글로. JSON 목록(보기·조건이 ["가","나"] 로 저장된 경우)은 줄로 풀고, 바이트·빈 값은 건너뛴다."""
    if v is None or isinstance(v, (bytes, bytearray, memoryview)): return ""
    s = str(v).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            arr = json.loads(s)
            if isinstance(arr, list) and all(isinstance(x, (str, int, float)) for x in arr): s = "\n".join(str(x) for x in arr)
        except ValueError:
            pass
    return s[:MAX_DB_CELL]


def _worksheet_rows(conn, path, names):
    """학습지를 문제(problems: 문제 번호·구분·문장)와 줄(problem_lines: 요구사항·제공 코드·정답 코드·실행 결과를 한 줄씩), 그림(problem_images)으로 나눠 담은 DB 를 읽는다."""
    from pathlib import Path
    if not {"problems", "problem_lines"} <= set(names): return []
    cols = lambda tb: [r[1] for r in conn.execute(f"PRAGMA table_info({tb})")]
    pc, lc = cols("problems"), cols("problem_lines")
    if not ({"id", "statement"} <= set(pc) and {"problem_id", "kind", "content"} <= set(lc)): return []
    titles = {}
    if "documents" in names and {"id", "title"} <= set(cols("documents")):
        titles = {r[0]: str(r[1] or "") for r in conn.execute("SELECT id, title FROM documents LIMIT 1000")}
    kind_field = {"requirement": "조건", "given_code": "제공코드", "solution_code": "정답코드", "result": "출력"}
    lines = {}
    for pid, kind, content in conn.execute("SELECT problem_id, kind, content FROM problem_lines ORDER BY problem_id, line_no LIMIT 300000"):
        if kind in kind_field: lines.setdefault(pid, {}).setdefault(kind_field[kind], []).append(str(content or ""))
    pics = {}
    if "problem_images" in names and {"problem_id", "data"} <= set(cols("problem_images")):
        for pid, data in conn.execute("SELECT problem_id, data FROM problem_images ORDER BY problem_id, seq LIMIT 2000"):
            if isinstance(data, (bytes, bytearray, memoryview)): pics.setdefault(pid, []).append(bytes(data))
    keys = [c for c in ("id", "document_id", "problem_no", "section", "statement") if c in pc]
    order = ("document_id, " if "document_id" in pc else "") + ("problem_no" if "problem_no" in pc else "id")
    out = []
    for row in conn.execute(f"SELECT {', '.join(keys)} FROM problems ORDER BY {order} LIMIT {MAX_DB_ROWS}"):
        r = dict(zip(keys, row))
        title, no = titles.get(r.get("document_id"), ""), r.get("problem_no") or len(out) + 1
        m = re.match(r"^\s*([A-Za-z+#]{1,6})[ \t]+(\d{1,2})\b", title)
        f = {"이름": f"{m.group(1)}_{m.group(2)}_{int(no):02d}" if m else f"{title} {no}".strip(), "설명": str(r.get("statement") or "").strip()}
        for k, v in lines.get(r["id"], {}).items():
            s = "\n".join(v).strip()
            if s: f[k] = s[:MAX_DB_CELL]
        if r.get("section"): f["비고"] = str(r["section"]).strip()
        if not f["설명"] and len(f) <= 2: continue
        out.append({"source": f"{Path(path).name}:problems", "row": len(out) + 1, "fields": f, "intake": intake_row(f, path), "blobs": pics.get(r["id"], [])})
    return out


def read_sqlite(path):
    """SQLite 파일(.db/.sqlite/.sqlite3)의 표를 엑셀처럼 읽는다. 이름·설명에 해당하는 열이 있는 표만 문제 표로 본다 (뷰는 같은 데이터가 중복되고 무거운 계산이 숨을 수 있어 읽지 않는다)."""
    import sqlite3, time
    from pathlib import Path
    with open(path, "rb") as fh:
        if fh.read(16) != SQLITE_MAGIC: raise SystemExit("SQLite 데이터베이스 파일이 아닙니다. (.db 는 SQLite 만 지원합니다)")
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise SystemExit(f"데이터베이스를 열 수 없습니다: {type(e).__name__}")
    t0 = time.time()
    conn.set_progress_handler(lambda: 1 if time.time() - t0 > 15 else 0, 100000)       # 15초를 넘으면 중단
    try:
        conn.execute("PRAGMA query_only = ON")
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out, seen_cols = [], []
        for tb in names:
            q = '"' + tb.replace('"', '""') + '"'
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({q})")]
            keymap = {c: canon(c) for c in cols if canon(c)}
            seen_cols.append(f"{tb}({', '.join(cols[:8])})")
            if "이름" not in keymap.values() or "설명" not in keymap.values(): continue
            unknown = [c for c in cols if c not in keymap]
            sel = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
            for n, row in enumerate(conn.execute(f"SELECT {sel} FROM {q} LIMIT {MAX_DB_ROWS}"), 1):
                f = {}
                for c, v in zip(cols, row):
                    if c in keymap:
                        s = _db_value(v)
                        if s: f[keymap[c]] = s
                if not f.get("이름") and not f.get("설명"): continue
                it = intake_row(f, path)
                if unknown: it["메모"].append(UNKNOWN_COLS_MEMO + ", ".join(unknown))
                out.append({"source": f"{Path(path).name}:{tb}", "row": n, "fields": f, "intake": it})
        if not out: out = _worksheet_rows(conn, path, names)           # 이름·설명 열이 없으면 학습지 DB(문제 표 + 줄 표 + 그림 표) 모양인지 본다
        if not out and not any(True for _ in names):
            raise SystemExit("데이터베이스에 표가 없습니다.")
        if not out:
            raise SystemExit("문제 표를 찾지 못했습니다. 이름(title)·설명(description) 열이 있는 표가 필요합니다. 있는 표: " + "; ".join(seen_cols[:6]))
    except sqlite3.Error as e:
        raise SystemExit(f"데이터베이스를 읽는 중 오류가 났습니다: {type(e).__name__}")
    finally:
        conn.close()
    return mark_duplicate_names(out)


def read_csv(path):
    rows = _csv_rows(path)
    hr = next((i for i, r in enumerate(rows[:12]) if "설명" in [canon(c) for c in r] and "이름" in [canon(c) for c in r]), None)
    if hr is None: raise SystemExit(f"{path}: 이름/설명 머리글을 찾지 못했습니다.")
    cols = {i: canon(c) for i, c in enumerate(rows[hr]) if canon(c)}
    unknown = [c.strip() for i, c in enumerate(rows[hr]) if c.strip() and i not in cols]       # 모르는 열은 버리지 말고 알린다
    out = []
    for n, r in enumerate(rows[hr + 1:], hr + 2):
        f = {key: r[i].strip() for i, key in cols.items() if i < len(r) and r[i].strip()}
        if not f.get("이름") and not f.get("설명"): continue
        it = intake_row(f, path)
        if unknown: it["메모"].append(UNKNOWN_COLS_MEMO + ", ".join(unknown))
        out.append({"source": path.split("/")[-1], "row": n, "fields": f, "intake": it})
    return mark_duplicate_names(out)


def sheet_text(path, limit=300_000):
    """머리글(이름·설명 열)이 없는 자유 형식 엑셀·CSV 의 모든 칸을 문서처럼 읽는다. 행마다 한 줄이고 칸 사이는 공백 3개이다 (워드 표와 같은 약속)."""
    lines = []
    if str(path).lower().endswith((".csv", ".tsv", ".tab")):
        for r in _csv_rows(path):
            cells = [str(c).strip() for c in r if str(c).strip()]
            if cells: lines.append("   ".join(cells))
    else:
        if str(path).lower().endswith((".xlsx", ".xlsm")): safety.check_zip(path)
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws in wb:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells: rows.append("   ".join(cells))
            if rows:
                if len(wb.sheetnames) > 1: lines.append(ws.title)
                lines += rows
            if sum(len(x) + 1 for x in lines) > limit: break
    text = "\n".join(lines)
    return text[:limit]


def read(path, include_examples=False):
    if path.lower().endswith((".csv", ".tsv", ".tab")): return read_csv(path)
    if str(path).lower().endswith(DB_EXT): return read_sqlite(path)
    if str(path).lower().endswith((".xlsx", ".xlsm")): safety.check_zip(path)        # 압축 폭탄 점검
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for ws in wb:
        if ws.title in SKIP_SHEETS and not include_examples: continue
        try:
            hr, cols = find_header(ws)
        except SystemExit:
            if len(wb.sheetnames) == 1: raise
            continue
        unknown = [str(c.value).strip() for c in ws[hr] if c.value not in (None, "") and str(c.value).strip() and c.column not in cols]   # 모르는 열은 버리지 말고 알린다
        for r in range(hr + 1, ws.max_row + 1):
            f = {}
            for col, key in cols.items():
                v = ws.cell(r, col).value
                if v is not None and str(v).strip() != "": f[key] = str(v).strip()
            if not f.get("이름") and not f.get("설명"): continue           # 서식만 있는 빈 행
            it = intake_row(f, path)
            if unknown: it["메모"].append(UNKNOWN_COLS_MEMO + ", ".join(unknown))
            out.append({"source": f"{path.split('/')[-1]}:{ws.title}", "row": r, "fields": f, "intake": it})
    return mark_duplicate_names(out)
