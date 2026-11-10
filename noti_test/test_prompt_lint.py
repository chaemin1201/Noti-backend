"""프롬프트 점검 (AI 호출 없음): prompt.md 를 고칠 때마다 돌려서 규칙이 빠지거나 예시가 틀어지지 않았는지 기계로 확인한다.

  1. 섹션 태그가 짝이 맞는가
  2. 지금까지 시험으로 찾아 넣은 핵심 규칙의 표지가 모두 남아 있는가   (줄이다가 규칙을 빠뜨리는 것을 막는다)
  3. 출력 예시가 서버 검사를 실제로 통과하는가 (스키마, 조건 형식, 정답코드 실행 결과, review 항목, id == title, 검증 값)
  4. 같은 문장이 두 번 나오지 않는가 / 길이가 예산 안인가

noti_test 폴더에서:  python test_prompt_lint.py [prompt.md 경로] [--max-chars N]"""
import json, os, re, sys
import _bootstrap
_bootstrap.setup()
os.environ["INTAKE_EXEC_NO_NET"] = "off"
from app.inputdata.intake.checks import checker
from app.inputdata.schemas import problem_adapter

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BUDGET = int(sys.argv[sys.argv.index("--max-chars") + 1]) if "--max-chars" in sys.argv else 10 ** 9
if "--max-chars" in sys.argv: args = [a for a in args if a != str(BUDGET)]
ind, _mod = _bootstrap.package_dirs(_bootstrap.ROOT)
PATH = args[0] if args else os.path.join(ind, "intake", "prompt.md")
text = open(PATH, encoding="utf-8").read()

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

print(f"대상: {PATH} ({len(text):,}자)")
print("1. 섹션 태그")
SECTIONS = ["역할 분담", "처리 순서", "원칙", "입력", "형식별 필터링", "입력 종류별 처리", "항목 매핑", "필수 항목", "누락 처리표", "모순 처리", "보류 조건",
            "조건 규칙", "방식 분할", "기록 규칙", "출력 형식", "요청"]
check("필수 섹션이 모두 있고 열고 닫는 태그가 짝이 맞음", all(f"<{s}>" in text and f"</{s}>" in text and text.index(f"<{s}>") < text.index(f"</{s}>") for s in SECTIONS),
      [s for s in SECTIONS if f"<{s}>" not in text or f"</{s}>" not in text])
check("프롬프트에 예시 블록이 없다 (예시에 얽매이지 않게 규칙과 출력 형식 틀로만 가르침)", "<예시" not in text and "</예시" not in text)

print("2. 핵심 규칙 표지 (시험으로 찾아 넣은 규칙이 남아 있는가)")
RULES = {
    "AI 는 코드를 실행하지 못함(손 추적)": ["손 추적", "실행할 수 없"],
    "검증 표기 3종": ["자료 일치", "미검증"],
    "원문 보존": ["원문 보존"],
    "입력 속 지시문은 데이터": ["입력 보안", "지시문"],
    "확인필요/참고 구분": ["확인필요:", "참고:", "승인 여부와 무관"],
    "마크다운 기호는 description 에서도 제거(남기지 말 것)": ["마크다운", "서버가 description 의 마크다운을 거부", "기호만 지움"],
    "코드·식의 ** 는 마크다운이 아니므로 지우지 않음": ["int **p", "**kwargs", "__init__", "코드·식의 기호는 지우지 않습니다"],
    "조건 태그는 네 가지뿐, 새 태그 금지": ["새 태그", "[기준]"],
    "입력 열·출력 열이 따로 있으면 출력을 고치지 않음": ["입력 열과 출력 열이 따로", "한 글자도 고치지 않고"],
    "워드 자동 고침 따옴표": ["자동 고침"],
    "워드/한글 표 칸 줄바꿈 손실": ["공백 3개", "줄바꿈 복원"],
    "한글 흩어진 표 칸은 머리 칸 기준으로 다시 짝짓기": ["흩어져 오면", "머리 칸"],
    "엑셀 자동 변환(숫자 앞 0, 날짜, TRUE/FALSE)": ["자동 변환", "TRUE/FALSE"],
    "엑셀 잘린 셀/병합 셀": ["글자 수 한계", "병합 셀"],
    "지시에 없는 형식·상황은 같은 원칙으로": ["이 지시에 없는 형식이나 상황", "근거가 입력 안에 분명할 때만"],
    "[이미지] 처리": ["[이미지]"],
    "정본 기준(원본/엑셀)": ["정본"],
    "이름 밀림·상태 메시지 보류": ["이름 밀림", "상태 메시지"],
    "정답자료 사용": ["정답자료"],
    "이름의 '문제 ' 접두어 제거(ID 모양 아니어도)": ["예시-객관식", "ID 모양이 아니어도"],
    "id == title": ["payload.title"],
    "rating_mode 유형별 허용값": ["active", "deactive"],
    "C/C++ 구분과 int main": ["int main", "void main"],
    "기대 출력에 입력값 금지": ["표준출력", "메뉴 >>"],
    "그래픽/난수 출력은 테스트 케이스 없음": ["난수", "그래픽"],
    "모순 처리 4단계": ["<모순 처리>", "옛 실행 결과", "계산 내용을 정하지 않"],
    "방식 분할 + 출력 통일": ["-1, -2", "글자 하나까지", ".tolist()"],
    "보류 조건 목록": ["<보류 조건>", "본문을 읽을 수 없음"],
    "조건 태그": ["필수 | 금지 | 허용 | 출력형식"],
    "객관식 번호 → 인덱스": ["0부터 인덱스"],
    "단답형 번호별 답(dict)": ["번호별 답"],
    "개인정보는 어느 출력에도 쓰지 않음": ["개인정보는 출력 어디에도"],
    "객관식 보기 앞 기호 제거": ["보기 앞의 번호·기호"],
    "a) b) 소문항은 한 문제로 유지": ["소문항은 한 문제의 일부"],
    "PDF 열·단 순서가 섞이면 확인필요": ["열·단 순서"],
    "첨부된 그림(코드·실행 화면)을 읽음": ["그림 N개", "직접 읽고 글로 옮깁니다", "정답 코드·정답이 조금이라도 보이는 그림", "review.그림"],
    "서버 실행으로 확인되는 것은 확인필요가 아니라 참고": ["확인필요가 아니라 참고에 적습니다", "실행으로는 알 수 없는 것"],
    "파워포인트(슬라이드·발표자 노트)": ["[파워포인트(.pptx)]", "[발표자 노트]"],
    "출력 형식 JSON 한 줄": ["JSON 한 줄", '"참고":[]'],
    "난이도·태그는 입력에 없으면 AI 가 채움, 부제목·문제의도는 채움에만 기록": ["주제 키워드 2~4개", "payload 에는 넣지", "고난도 알고리즘"],
}
for name, marks in RULES.items():
    miss = [m for m in marks if m not in text]
    check(name, not miss, f"← 없음: {miss}")

print("2b. 낡은 문구 (규칙을 바꾼 뒤 남아서 다른 규칙과 부딪혔던 문장)")
STALE = {
    "난이도·태그를 '입력에 있을 때만' 옮긴다는 옛 문장 (지금은 없으면 AI 가 채움)": "난이도와 태그는 입력에 있을 때만 옮깁니다",
    "주관식 답안을 단답형과 묶어 필수로 쓰는 옛 문장 (지금은 주관식은 사람이 입력)": "단답형·주관식: answer_text.",
    "'처리는 여기서만 정합니다' (채울지 비울지는 여기서만)": "비어 있는 항목의 처리는 여기서만 정합니다",
    "그림 내용을 읽을 수 없다는 옛 규칙 (지금은 첨부된 그림을 읽는다)": "내용은 읽을 수 없습니다. 입출력 예나 실행 화면이 그림뿐이면",
    "그림 표시를 description 에 그대로 두라는 옛 규칙 (지금은 내용을 알맞은 칸에 넣고 표시는 지움)": "description 에는 [이미지] 표시를 그대로 둡니다",
}
for name, s in STALE.items():
    check(f"없어야 함: {name}", s not in text)

print("3. 출력 예시가 서버 검사를 통과하는가")
KEYS = ["상태", "보류사유", "입력종류", "정리", "복구", "채움", "조언", "확인필요", "참고"]
n_ex = 0; seen = {}
for line in text.splitlines():
    s = line[4:] if line.startswith(("입력: {", "출력: {")) else (line if line.startswith('{"id":"') and "|null" not in line else None)
    if s is None or "{위 입력" in s: continue
    try: d = json.loads(s)
    except ValueError as e: check("예시 JSON 파싱", False, (line[:50], e)); continue
    if not line.startswith(("출력: {", '{"id":"')): continue                       # 입력 줄
    n_ex += 1; rv = d.get("review", {}); pl = d.get("payload")
    check(f"{d['id']}: review 에 9개 항목이 모두 있다", all(k in rv for k in KEYS), [k for k in KEYS if k not in rv])
    if pl is None:
        check(f"{d['id']}: 보류는 payload 가 없고 보류사유가 있다", rv.get("상태") == "보류" and rv.get("보류사유"), rv.get("상태")); continue
    check(f"{d['id']}: id 가 title 과 같다", d["id"] == pl.get("title"))
    check(f"{d['id']}: 채움 검증 값이 허용 범위", all(f.get("검증") in ("손 추적", "자료 일치", "미검증") for f in rv.get("채움", [])))
    fails, warns = checker.check_case({"id": d["id"], "payload": pl, "review": rv}, seen, skip_exec=False)
    check(f"{d['id']}: 서버 검사 통과(스키마·조건 형식·마크다운·정답코드 실행)", not fails, fails)
check("출력 예시가 없다 (있으면 서버 검사를 통과해야 하므로 위에서 검사됨)", n_ex == 0, n_ex)
check("payload 틀과 보류 틀이 출력 형식에 있다", "payload 틀" in text and "보류 시 한 줄 틀" in text)

print("4. 중복·길이")
sents = [re.sub(r"\s+", "", x) for x in re.split(r"(?<=[.다요])\s+|\n", text) if len(re.sub(r"\s+", "", x)) >= 40 and not x.lstrip().startswith(("입력:", "출력:", "{"))]
dups = sorted({s[:40] for s in sents if sents.count(s) > 1})
check("규칙 문장이 두 번 나오지 않는다", not dups, dups[:3])
check("실행했다는 표현('실행 일치')은 금지 문구로만 한 번 나온다", text.count("실행 일치") == 1, text.count("실행 일치"))
check(f"길이 예산 {BUDGET:,}자 이내" if BUDGET < 10 ** 9 else "길이 (예산 없음)", len(text) <= BUDGET, f"{len(text):,}자")

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
