# app/inputdata/intake/config.py
"""환경변수로 정하는 설정. 값이 없으면 기본값을 쓴다."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def prompt_path():
    return os.environ.get("INTAKE_PROMPT_PATH") or os.path.join(HERE, "prompt.md")


def _flag(name, default="off"):
    return os.environ.get(name, default).strip().lower() in ("on", "1", "true", "yes")


def exec_enabled():
    """정답 코드를 서버에서 실행해 검증할지. AI 가 쓴 코드를 실행하므로 기본은 끔(off).
    INTAKE_EXEC=on 만으로는 켜지지 않는다. 격리된 컨테이너(네트워크 차단, 읽기 전용 파일시스템, 비루트)에서
    돌리고 있음을 운영자가 INTAKE_EXEC_ISOLATED=on 으로 함께 확인해야 한다. 한쪽만 켜면 실행 검증은 꺼진 채로 둔다."""
    return _flag("INTAKE_EXEC") and _flag("INTAKE_EXEC_ISOLATED")


def exec_misconfigured():
    """INTAKE_EXEC 만 켜고 격리 확인을 빠뜨린 경우 (시작 로그 경고용)."""
    return _flag("INTAKE_EXEC") and not _flag("INTAKE_EXEC_ISOLATED")


def exec_block_network():
    """실행 시 네트워크를 끊는다(unshare -n 이 있을 때). 기본 on."""
    return _flag("INTAKE_EXEC_NO_NET", "on")


def heartbeat_seconds():
    """작업이 이 시간(초) 안에 신호를 남겼으면 다른 워커에서 처리 중인 것으로 본다."""
    return max(30, _int("INTAKE_HEARTBEAT_SEC", 120))


def max_file_bytes():
    return _int("INTAKE_MAX_FILE_MB", 20) * 1024 * 1024


def max_files():
    return _int("INTAKE_MAX_FILES", 5)


def max_problems():
    return _int("INTAKE_MAX_PROBLEMS", 200)


def max_tokens():
    return _int("INTAKE_MAX_TOKENS", 20000)


def max_consecutive_ai_failures():
    return _int("INTAKE_MAX_CONSEC_FAIL", 3)


def concurrency():
    """AI 를 동시에 부르는 문제 수. 서비스의 동시 호출 한도(429)에 걸리면 1~2로 낮춘다."""
    return _int("INTAKE_CONCURRENCY", 20)


def repair_rounds():
    """서버 검사에서 막힐 AI 결과를 이유와 함께 돌려보내 다시 쓰게 하는 횟수(0 이면 끔). 호출이 늘어나므로 막힐 때만 쓴다."""
    return max(0, _int("INTAKE_REPAIR_ROUNDS", 1))


def call_deadline():
    """AI 호출 하나를 기다리는 시간(초). 정상 호출은 25초 안에 끝나는데 가끔 한 호출이 몇 분씩 멈춘다(작업 전체가 그 호출을 기다림).
    넘으면 그 요청은 버리고 같은 요청을 한 번 더 보낸다(헤징). 0 이면 끔."""
    return max(0, _int("INTAKE_CALL_DEADLINE", 40))


def call_hard_limit():
    """다시 보낸 요청까지 이 시간(초) 안에 답이 없으면 그 문제를 '보류'(AI 응답 지연)로 돌리고 다음으로 넘어간다. 보류 문제는 재시도로 다시 처리할 수 있다."""
    return max(5, _int("INTAKE_CALL_HARD_LIMIT", 40))


def ai_item_timeout():
    """문제 한 개의 AI 호출(재시도 포함)에 줄 수 있는 최대 시간(초). 넘으면 실패로 처리하고 다음 문제로 간다."""
    return _int("INTAKE_AI_ITEM_TIMEOUT", 900)             # 게이트웨이가 120초쯤에 끊는 호출을 몇 번 다시 시도할 수 있는 시간


def capture():
    """원본 캡처(올린 문서를 쪽 이미지로 만들어 승인 화면 왼쪽에 보여 줌). 기본 켬. 변환 도구가 없으면 알아서 건너뛴다."""
    return _flag("INTAKE_CAPTURE", "on")


def capture_pages():
    return max(1, _int("INTAKE_CAPTURE_PAGES", 40))             # 파일 하나당 캡처할 최대 쪽 수


def capture_dpi():
    return max(50, _int("INTAKE_CAPTURE_DPI", 100))


def capture_days():
    """캡처 이미지를 보관하는 날 수 (개인정보가 이미지에 그대로 남으므로 지나면 지운다). 0 이면 지우지 않음."""
    return max(0, _int("INTAKE_CAPTURE_DAYS", 30))


def job_days():
    """업로드 작업 데이터(작업·항목·캡처)를 보관하는 날 수. 이 데이터는 처리 중에만 필요한 임시 작업 데이터이고 등록된 문제는 따로 저장되므로 지나면 지운다. 0 이면 지우지 않음."""
    return max(0, _int("INTAKE_JOB_DAYS", 30))


def concurrent_jobs():
    return max(1, _int("INTAKE_CONCURRENT_JOBS", 2))


def light_rows():
    """이름·설명·정답 코드·출력이 다 있는 엑셀·DB 행은 서버가 직접 구성하고 AI 에는 비어 있는 메타 정보만 짧게 묻는다 (토큰 절약). INTAKE_LIGHT_ROWS=off 로 끈다."""
    return _flag("INTAKE_LIGHT_ROWS", "on")


def batch_size():
    """같은 종류의 짧은 문제를 이 개수씩 한 번의 AI 호출로 묶는다 (같은 프롬프트를 되풀이해 보내는 입력 토큰이 줄어든다). 1 이면 묶지 않는다(기본).
    묶으면 앞 문제 내용이 섞일 수 있어 실제 AI 로 결과를 비교한 뒤 켠다. 예: INTAKE_BATCH=3"""
    return max(1, min(8, _int("INTAKE_BATCH", 1)))


def whole_doc():
    """문제 번호·제목을 찾지 못한 문서(번호가 글에 없는 한글 .hwpx 등)를 거절하지 않고, 문서 전체를 한 번에 보내 AI 가 문제 단위로 나누게 한다. 기본은 끔
    (긴 문서는 출력이 길어지고 나누기가 틀릴 수 있어 사람이 결과를 확인해야 한다). INTAKE_WHOLE_DOC=on 으로 켠다."""
    return _flag("INTAKE_WHOLE_DOC", "off")


def whole_doc_chars():
    return _int("INTAKE_WHOLE_DOC_CHARS", 24000)


def scan_pages():
    """스캔 PDF 한 파일에서 읽을 최대 쪽 수 (그림 한 장마다 AI 입력 토큰이 크게 든다). INTAKE_SCAN_PAGES, 기본 40."""
    return _int("INTAKE_SCAN_PAGES", 40)


def scan_chunk():
    """스캔 PDF 를 몇 쪽씩 묶어 AI 에 보낼지. 한 번에 보내는 그림이 많으면 느리고 끊기기 쉽다. INTAKE_SCAN_CHUNK, 기본 4 (최대 8)."""
    return max(1, min(8, _int("INTAKE_SCAN_CHUNK", 4)))


def warmup():
    """같은 프롬프트로 처리할 문제가 4개 이상이면 첫 문제를 혼자 먼저 처리해 AI 서비스의 프롬프트 캐시를 데운 뒤 나머지를 동시에 처리한다.
    동시에 시작하면 모두 캐시 없이 전체 입력 요금이 든다(측정: 캐시가 없을 때 동시 4건 중 대부분이 0 적중, 데운 뒤에는 입력의 98% 적중). INTAKE_WARMUP=off 로 끈다."""
    return _flag("INTAKE_WARMUP", "on")


def ai_answer_review():
    """AI 가 직접 푼 객관식·단답형 정답(손으로 따라간 값이라 실행으로 확인할 수 없고 틀릴 수 있음)을 승인 대기로 보낼지. 기본 켬.
    승인할 문제가 너무 많아지면 INTAKE_AI_ANSWER_REVIEW=off 로 끄면 예전처럼 자동 등록하고 사후 점검 표시(ai_filled)만 남긴다."""
    return _flag("INTAKE_AI_ANSWER_REVIEW", "on")


def daily_problems():
    """한 사용자가 하루(서버 시간 0시 기준)에 올릴 수 있는 문제 수. AI 호출 비용과 남용을 막는다. 0 이면 제한 없음. INTAKE_DAILY_PROBLEMS, 기본 500."""
    return max(0, _int("INTAKE_DAILY_PROBLEMS", 500))


def daily_jobs():
    """한 사용자가 하루에 만들 수 있는 업로드 작업 수. 0 이면 제한 없음. INTAKE_DAILY_JOBS, 기본 30."""
    return max(0, _int("INTAKE_DAILY_JOBS", 30))


def redact_pii():
    """AI 서비스로 보내기 전에 개인정보(학번·이름 칸, 전화번호, 이메일, 주민등록번호)를 지울지. 기본 켬. INTAKE_REDACT_PII=off 로 끈다."""
    return _flag("INTAKE_REDACT_PII", "on")


def fill_meta():
    """부제목·문제의도가 없는 문제는 짧은 메타 호출(약 300 토큰)로 AI 가 문제를 보고 채우게 한다. 큰 호출은 이 항목을 자주 빠뜨린다. 기본 켬. INTAKE_FILL_META=off 로 끈다."""
    return _flag("INTAKE_FILL_META", "on")


def fill_code():
    """다시 쓰기로도 비어 있는 코딩·디버깅의 제공 코드(설명의 코드 블록에서)와 정답 코드(전용 짧은 호출로)를 서버가 채울지. 기본 켬. INTAKE_FILL_CODE=off 로 끈다."""
    return _flag("INTAKE_FILL_CODE", "on")
