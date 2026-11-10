"""업로드·코드 실행 보안 시험: 압축 폭탄, 위험한 호출이 든 정답 코드, 그림 폭탄·그림 용량, 그림 속 지시문.
noti_test 폴더에서:  python test_security.py        (python-docx, Pillow 필요)"""
import io, os, shutil, sys, tempfile, zipfile, zlib
import _bootstrap
_bootstrap.setup()
os.environ["INTAKE_EXEC_NO_NET"] = "off"
try:
    import docx
    from PIL import Image
except ImportError as e:
    print(f"⏭ 건너뜀: {e.name} 가 필요합니다"); sys.exit(2)
from app.inputdata.intake import parsing
from app.inputdata.intake.checks import checker
from app.inputdata.intake.readers import images
from app.inputdata.intake.readers import pdf_intake
from app.inputdata.intake.readers import images as safety

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

def raises(fn, exc=Exception):
    try: fn(); return None
    except exc as e: return e

os.environ["INTAKE_MAX_UNZIPPED_MB"] = "10"            # 시험에서는 한도를 10MB 로 낮춰 작은 폭탄으로 확인한다
ZEROS = b"\0" * (30 * 1024 * 1024)

print("1. 압축 폭탄")
with tempfile.TemporaryDirectory() as d:
    bomb = os.path.join(d, "bomb.zip")
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z: z.writestr("a.bin", ZEROS)
    check("풀면 한도를 넘는 zip 은 열기 전에 거절한다", isinstance(raises(lambda: safety.check_zip(bomb), safety.UnsafeFile), safety.UnsafeFile) and os.path.getsize(bomb) < 200_000, os.path.getsize(bomb))
    ok = os.path.join(d, "ok.zip")
    with zipfile.ZipFile(ok, "w", zipfile.ZIP_DEFLATED) as z: z.writestr("a.txt", "안녕" * 1000)
    check("보통 zip 은 통과한다", raises(lambda: safety.check_zip(ok)) is None)
    many = os.path.join(d, "many.zip")
    with zipfile.ZipFile(many, "w") as z:
        for i in range(5100): z.writestr(f"f{i}", b"x")
    check("항목이 5000개를 넘는 zip 은 거절한다", isinstance(raises(lambda: safety.check_zip(many), safety.UnsafeFile), safety.UnsafeFile))
    notzip = os.path.join(d, "x.zip"); open(notzip, "wb").write(b"not a zip")
    e = raises(lambda: safety.check_zip(notzip), safety.UnsafeFile); check("zip 이 아니면 손상 안내", e is not None and "손상" in str(e))
    # 실제 읽기 경로에 걸려 있는가
    wd = os.path.join(d, "b.docx"); doc = docx.Document(); doc.add_paragraph("실습 1. 가"); doc.add_paragraph("실습 2. 나"); doc.save(wd)
    with zipfile.ZipFile(wd, "a", zipfile.ZIP_DEFLATED) as z: z.writestr("word/media/bomb.bin", ZEROS)
    check("docx 읽기가 폭탄을 거절한다", isinstance(raises(lambda: pdf_intake.docx_text(wd), safety.UnsafeFile), safety.UnsafeFile))
    e = raises(lambda: parsing.build_records(None, [wd], labels=["b.docx"]), parsing.IntakeInputError)
    check("업로드 처리에서는 사용자에게 보이는 안내(IntakeInputError)로 바뀐다", e is not None and "넘" in str(e), e)
    hx = os.path.join(d, "b.hwpx")
    with zipfile.ZipFile(hx, "w", zipfile.ZIP_DEFLATED) as z: z.writestr("Contents/section0.xml", "<sec/>"); z.writestr("BinData/bomb.bin", ZEROS)
    from app.inputdata.intake.readers import hwp_text
    check("hwpx 읽기가 폭탄을 거절한다", isinstance(raises(lambda: hwp_text.hwpx_text(hx), safety.UnsafeFile), safety.UnsafeFile))
    px = os.path.join(d, "b.pptx")
    with zipfile.ZipFile(px, "w", zipfile.ZIP_DEFLATED) as z: z.writestr("ppt/presentation.xml", "<p/>"); z.writestr("ppt/media/bomb.bin", ZEROS)
    check("pptx 읽기가 폭탄을 거절한다", isinstance(raises(lambda: pdf_intake.pptx_text(px), safety.UnsafeFile), safety.UnsafeFile))
    import openpyxl
    from app.inputdata.intake.readers import xlsx_intake
    xl = os.path.join(d, "b.xlsx"); wb = openpyxl.Workbook(); wb.active.append(["이름", "설명"]); wb.save(xl)
    with zipfile.ZipFile(xl, "a", zipfile.ZIP_DEFLATED) as z: z.writestr("xl/media/bomb.bin", ZEROS)
    check("xlsx 읽기가 폭탄을 거절한다", isinstance(raises(lambda: xlsx_intake.read(xl), safety.UnsafeFile), safety.UnsafeFile))
co = zlib.compressobj(wbits=-15); raw = co.compress(ZEROS) + co.flush()
check("한글(.hwp)의 압축 조각도 풀린 크기를 제한한다", isinstance(raises(lambda: safety.inflate(raw), safety.UnsafeFile), safety.UnsafeFile))
co = zlib.compressobj(wbits=-15); small = co.compress(b"hello" * 100) + co.flush()
check("작은 조각은 그대로 풀린다", safety.inflate(small) == b"hello" * 100)

print("2. 위험한 호출이 든 정답 코드는 실행하지 않는다")
def blocked(lang, code): r = checker.run_code(lang, code, ""); return r[0] == "error" and "허용되지 않는" in r[1]
for name, code in [("subprocess", "import subprocess\nsubprocess.run(['ls'])"), ("os.system", "import os\nos.system('echo hi')"), ("socket", "import socket\nsocket.socket()"),
                   ("open(읽기도)", "print(open('/etc/passwd').read())"), ("open(쓰기)", "open('x.txt','w').write('1')"), ("eval", "print(eval('1+1'))"),
                   ("__import__", "__import__('os').system('id')"), ("os.environ", "import os\nprint(os.environ)"), ("pickle", "import pickle")]:
    check(f"Python {name} 은 막는다", blocked("python", code))
check("평범한 Python 은 실행한다", checker.run_code("python", "import math\nprint(math.sqrt(16))", "") [:2] == ("ok", "4.0\n"))
check("os 를 쓰지 않는 입출력 코드도 그대로 실행한다", checker.run_code("python", "n = int(input())\nprint(n * 2)", "21")[:2] == ("ok", "42\n"))
if shutil.which("gcc") and shutil.which("g++"):
    check("C system() 은 막는다", blocked("c", '#include <stdlib.h>\nint main(){ system("ls"); return 0; }'))
    check("C fopen 쓰기는 막는다", blocked("c", '#include <stdio.h>\nint main(){ FILE *f = fopen("a","w"); return 0; }'))
    check("C++ <unistd.h> 는 막는다", blocked("cpp", "#include <unistd.h>\nint main(){ return 0; }"))
    ok = checker.run_code("cpp", "#include <vector>\n#include <algorithm>\n#include <functional>\n#include <iostream>\nint main(){ std::vector<int> v{1,2,3}; v.erase(std::remove(v.begin(), v.end(), 2), v.end()); auto f = std::bind([](int a){return a;}, 5); std::cout << v.size() << f(); return 0; }", "")
    check("STL 의 std::remove·std::bind 같은 정상 코드는 막지 않는다 (오탐 없음)", ok[:2] == ("ok", "25"), ok)
check("Java 의 파일·프로세스 API 는 계속 막는다", shutil.which("javac") is None or blocked("java", 'public class Main{ public static void main(String[] a) throws Exception { new ProcessBuilder("ls").start(); } }'))

print("3. 그림 폭탄·그림 용량")
images.MAX_PIXELS = 1_000_000
b = io.BytesIO(); Image.new("L", (2000, 2000), 0).save(b, "PNG")
check("픽셀 수가 한도를 넘는 그림은 열지 않는다 (그림 폭탄)", images.prepare(b.getvalue()) is None and len(b.getvalue()) < 100_000, len(b.getvalue()))
images.MAX_PIXELS = 50_000_000
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "f0.docx"); doc = docx.Document()
    for i in (1, 2, 3):
        doc.add_paragraph(f"실습 {i}. 문제")
        buf = io.BytesIO(); Image.effect_noise((300, 300), 80).save(buf, "PNG"); doc.add_paragraph("그림").add_run().add_picture(io.BytesIO(buf.getvalue()))
    doc.save(p)
    os.environ["INTAKE_MAX_JOB_IMAGE_MB"] = "0.12"                       # 작업 전체 그림 한도를 아주 작게
    recs = parsing.build_records(None, [p], labels=["j_문제.docx"])[1]
    n_img = [len(r.get("이미지") or []) for r in recs]
    check("작업 전체 그림 용량이 한도를 넘으면 뒤 문제의 그림은 붙이지 않고 알린다", n_img[0] == 1 and n_img[-1] == 0 and any("한도" in " ".join(r["intake"]["메모"]) for r in recs[1:]), (n_img, [r["intake"]["메모"] for r in recs]))
    del os.environ["INTAKE_MAX_JOB_IMAGE_MB"]
    check("한도가 넉넉하면 모두 붙는다", [len(r.get("이미지") or []) for r in parsing.build_records(None, [p], labels=["j_문제.docx"])[1]] == [1, 1, 1])

print("4. 지시문 방어")
check("AI 에게 가는 안내에 '그림 속 글'도 데이터라는 말이 들어간다", "그림 속 글" in parsing._GUARD)
check("프롬프트 원칙에도 그림 속 글이 데이터라고 적혀 있다", "첨부된 그림 속 글" in open(os.path.join(os.path.dirname(os.path.dirname(pdf_intake.__file__)), "prompt.md"), encoding="utf-8").read())
check("pdftotext 호출에 시간 제한이 있다", "timeout=120" in open(pdf_intake.__file__, encoding="utf-8").read().split('"-layout"')[1][:300])

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
