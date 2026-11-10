"""객관식·단답형·주관식 테스트 문제지를 만든다 (noti_test/문제지_샘플/).
  python make_type_samples.py          파일 4개를 만들고, AI 를 부르지 않고 문제로 잘 나뉘는지만 확인한다.
실제 AI 로 처리해 보려면:  python run_real_e2e.py --rows 0 --upload 문제지_샘플/객관식_테스트.docx 문제지_샘플/단답형_테스트.md 문제지_샘플/주관식_테스트.docx 문제지_샘플/유형별_문제표.xlsx
"""
import os, sys
import _bootstrap
_bootstrap.setup()
import docx, openpyxl
from app.inputdata.intake import parsing

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "문제지_샘플")
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------ 객관식 (워드)
OB = [
    ("문제 OB11-0001", ["스택(Stack)의 특징으로 옳은 것은?", "① FIFO 구조이다", "② LIFO 구조이다", "③ 양쪽 끝에서 삽입한다", "④ 인덱스로 접근한다", "정답: ②"]),
    ("문제 OB11-0002", ["파이썬에서 리스트의 길이를 구하는 내장 함수는?", "1) size()", "2) length()", "3) len()", "4) count()", "정답 3번"]),
    ("문제 OB11-0003", ["객체지향의 특징이 아닌 것을 모두 고르시오. (정답 2개)", "A. 상속", "B. 캡슐화", "C. 컴파일", "D. 링크", "정답: C, D"]),
    ("문제 OB11-0004", ["다음 코드를 실행했을 때 출력 결과는?", "x = [1, 2, 3]", "y = x", "y.append(4)", "print(len(x))", "① 3", "② 4", "③ 오류가 난다", "④ 아무것도 출력되지 않는다", "정답: ②"]),
    ("문제 OB11-0005", ["HTTP 의 기본 포트 번호는? (정답 표시가 없는 문제: AI 가 풀면 반드시 사람이 확인해야 함)", "① 21", "② 22", "③ 80", "④ 443"]),
    ("문제 OB11-0006", ["다음 중 정렬 알고리즘이 아닌 것은?", "① 퀵 정렬", "② 병합 정렬", "③ 이진 탐색", "④ 버블 정렬", "정답: ③"]),
]
d = docx.Document(); d.add_heading("자료구조·파이썬 객관식 점검", 1)
for head, lines in OB:
    d.add_paragraph(head)
    for l in lines: d.add_paragraph(l)
d.save(os.path.join(OUT, "객관식_테스트.docx"))

# ------------------------------------------------------------------ 단답형 (마크다운)
SA = """# 자료구조 단답형 점검

문제 SA11-0001
후입선출(LIFO) 구조를 가지는 자료구조의 이름을 쓰시오.
정답: 스택

문제 SA11-0002
이진 탐색의 시간 복잡도를 빅오 표기로 쓰시오.
정답: O(log n)

문제 SA11-0003
다음 물음에 답하시오.
a) 큐에서 데이터를 넣는 연산의 이름은?
b) 큐에서 데이터를 꺼내는 연산의 이름은?
c) 큐는 FIFO 인가 LIFO 인가?
- 정답
a) enqueue
b) dequeue
c) FIFO

문제 SA11-0004
다음 코드의 출력 결과를 쓰시오.

```python
s = "hello"
print(s[1:4])
```
정답: ell

문제 SA11-0005
파이썬에서 딕셔너리의 키 목록을 돌려주는 메서드 이름을 쓰시오. (정답 표시가 없는 문제: AI 가 풀면 사람이 확인해야 함)

문제 SA11-0006
2 의 10 제곱 값을 쓰시오.
정답: 1024
"""
open(os.path.join(OUT, "단답형_테스트.md"), "w", encoding="utf-8").write(SA)

# ------------------------------------------------------------------ 주관식 (워드)
SJ = [
    ("문제 SJ11-0001", ["프로세스와 스레드의 차이를 설명하시오.", "모범 답안: 프로세스는 독립된 메모리 공간을 가진 실행 단위이고, 스레드는 프로세스 안에서 메모리를 공유하며 실행되는 흐름이다."]),
    ("문제 SJ11-0002", ["재귀 호출이 무엇인지 자신의 말로 설명하고 예를 하나 들어 3문장 이내로 서술하시오. (모범 답안이 없는 문제: 사람이 직접 입력해야 함)"]),
    ("문제 SJ11-0003", ["배열과 연결 리스트의 장단점을 비교하여 서술하시오.", "채점 기준", "- 접근 속도 비교", "- 삽입·삭제 비용 비교", "- 메모리 사용 방식"]),
    ("문제 SJ11-0004", ["반복문을 이용해 1부터 10까지의 합을 구하는 프로그램을 작성하고, 실행 결과를 캡처하여 제출하시오. (그림은 올릴 수 없으므로 글로 쓰도록 바뀌어야 함)"]),
    ("문제 SJ11-0005", ["다음 코드가 하는 일을 설명하시오.", "def f(n):", "    return 1 if n <= 1 else n * f(n - 1)", "모범 답안: 정수 n 의 팩토리얼을 재귀로 계산해 돌려준다."]),
]
d = docx.Document(); d.add_heading("자료구조 서술형 점검", 1)
for head, lines in SJ:
    d.add_paragraph(head)
    for l in lines: d.add_paragraph(l)
d.save(os.path.join(OUT, "주관식_테스트.docx"))

# ------------------------------------------------------------------ 유형별 표 (엑셀)
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "문제"
ws.append(["이름", "유형", "난이도", "설명", "보기", "정답", "부제목", "문제의도"])
ws.append(["XL11-0001", "객관식", "EASY", "SQL 에서 중복을 제거하는 키워드는?", "SELECT\nDISTINCT\nUNIQUE\nONLY", "DISTINCT", "SQL 기초", "중복 제거 문법 이해"])
ws.append(["XL11-0002", "객관식", "MEDIUM", "다음 중 시간 복잡도가 O(n log n) 인 정렬은? (정답 2개)", "버블 정렬\n병합 정렬\n힙 정렬\n선택 정렬", "병합 정렬, 힙 정렬", "", ""])
ws.append(["XL11-0003", "객관식", "EASY", "보기가 비어 있는 객관식입니다 (보기 누락: 입력 필요 또는 보류가 되어야 함)", "", "", "", ""])
ws.append(["XL11-0004", "단답형", "EASY", "HTTP 의 기본 포트 번호를 쓰시오.", "", "80", "네트워크", "기본 포트 암기"])
ws.append(["XL11-0005", "단답형", "MEDIUM", "리눅스에서 현재 디렉터리의 파일 목록을 보는 명령어를 쓰시오.", "", "ls", "", ""])
ws.append(["XL11-0006", "주관식", "MEDIUM", "TCP 와 UDP 의 차이를 설명하시오.", "", "TCP 는 연결 지향이고 신뢰성을 보장하며, UDP 는 비연결 지향이라 빠르지만 신뢰성을 보장하지 않는다.", "", ""])
ws.append(["XL11-0007", "주관식", "HARD", "정규화(Normalization)의 목적을 서술하시오. (모범 답안 칸이 빈 문제)", "", "", "", ""])
wb.save(os.path.join(OUT, "유형별_문제표.xlsx"))

# ------------------------------------------------------------------ AI 없이 문제로 잘 나뉘는지만 확인
print("만든 파일:", *sorted(os.listdir(OUT)), sep="\n  ")
for name in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, name)
    try:
        if name.endswith(".xlsx"): kind, recs = parsing.build_records([p], [], None, [], table_labels=[name])
        else: kind, recs = parsing.build_records([], [p], None, [name], table_labels=[])
    except Exception as e:
        print(f"[{name}] 읽기 실패: {e}"); continue
    print(f"[{name}] 문제 {len(recs)}개 ({kind})")
    for r in recs:
        hint = (r.get("intake") or {}).get("유형힌트") or (r.get("intake") or {}).get("유형") or "-"
        print(f"   {r['key']:<12} 유형힌트={hint}")
