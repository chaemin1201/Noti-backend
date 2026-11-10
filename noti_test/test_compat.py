"""서버를 이 코드로 덮어써도 옛 이름(import 경로·함수·상수)이 오류 없이 이어지는지 시험.
ORIGINAL 은 맨 처음 서버 코드(intake_patch.zip)의 모듈별 최상위 이름이다.
(옛 평면 경로 ai_output·checker·source_compare·xlsx_intake·pdf_intake·hwp_text 의 호환용 껍데기는 지웠다: 실제 서버에는 intake 가 처음부터 없었다. 새 경로는 checks/·readers/ 아래.)
noti_test 폴더에서:  python test_compat.py"""
import importlib, inspect, sys
import _bootstrap
_bootstrap.setup()

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

ORIGINAL = {
    "config": ['HERE', '_flag', '_int', 'concurrent_jobs', 'exec_block_network', 'exec_enabled', 'exec_misconfigured', 'heartbeat_seconds', 'max_consecutive_ai_failures', 'max_file_bytes', 'max_files', 'max_problems', 'max_tokens', 'prompt_path'],
    "llm": ['ANTHROPIC_URL', 'COOLDOWN', 'FatalLLMError', 'GOOGLE_MODELS_URL', 'GOOGLE_URL', 'HERE', 'KEY_VARS', 'RETRYABLE', 'RETRY_WAITS', 'TransientLLMError', '_BAD', '_SKIP', '_call_one', '_explain', '_get', '_is_bad', '_post', '_retry_delay', '_usage', 'call_llm', 'check_google_model', 'detect_provider', 'diagnose', 'fallback_models', 'find_working_model', 'find_working_models', 'format_usage', 'get_key', 'key_help', 'list_google_models', 'load_dotenv', 'parse_dotenv', 'rank_models', 'reset_cooldowns', 'resolve', 'save_model_to_env', 'thinking_config'],
    "models": ['AI_FAILED', 'ALL_STATUS', 'APPROVABLE', 'BLOCKED', 'DUPLICATE', 'EDITABLE', 'HELD', 'IntakeItem', 'IntakeJob', 'JsonType', 'NEEDS_REVIEW', 'PENDING', 'PROCESSING', 'READY', 'REGISTERED', 'REGISTER_FAILED', 'SKIPPED'],
    "parsing": ['IntakeInputError', 'ORIGINAL_EXT', 'SOLUTION_WORDS', 'TABLE_EXT', '_GUARD', '_merge', '_split_roles', 'build_records', 'compile_pattern', 'is_solution', 'kind_of', 'prompt_input', 'user_text'],
    "router": ['ApproveRequest', 'EditRequest', '_item', '_job', '_uid', 'approve', 'create_job', 'edit_item', 'get_job', 'list_items', 'list_jobs', 'reject_item', 'resume', 'router'],
    "service": ['_SEM', '_alive', '_apply_register', '_beat', '_default_ai', '_now', '_process', '_runnable', '_seen_hashes', '_session_factory', '_stop', '_store_rows', 'active_job', 'approve', 'classify', 'create_job', 'edit_payload', 'is_running', 'item_out', 'job_summary', 'logger', 'process_job', 'register_payload', 'reset_failed', 'session_scope', 'set_session_factory'],
}

print("1. 옛 모듈 경로마다 옛 이름이 모두 있다")
for mod, names in ORIGINAL.items():
    try:
        m = importlib.import_module(f"app.inputdata.intake.{mod}")
    except Exception as e:
        check(f"{mod} 를 불러온다", False, e); continue
    miss = [n for n in names if not hasattr(m, n)]
    check(f"{mod}: 옛 이름 {len(names)}개가 모두 있다", not miss, miss)

print("2. 옛 호출 방식")
from app.inputdata.intake import llm
ps = list(inspect.signature(llm.call_llm).parameters)
check("call_llm 에 옛 인자 fallbacks·on_fallback 이 옛 자리(on_retry 뒤, info 앞)에 있다", ps.index("on_retry") < ps.index("fallbacks") < ps.index("on_fallback") < ps.index("info"), ps)
check("옛 위치 인자 info·thinking 의 자리가 그대로다 (옛 순서: … on_fallback, info, thinking)", ps[ps.index("on_fallback") + 1:ps.index("on_fallback") + 3] == ["info", "thinking"], ps)
check("fallback_models 는 빈 목록 (모델을 바꾸지 않음)", llm.fallback_models("a") == [])
print("3. 선택 패키지가 서버에 없어도 서버는 시작된다 (main.py 가 라우터를 불러오는 순간 실패하면 서버 전체가 안 뜬다)")
import os, subprocess
BLOCK = "openpyxl,docx,olefile,PIL,lxml,pptx"
LINES = [
    "import sys, importlib.abc",
    "class B(importlib.abc.MetaPathFinder):",
    "    def find_spec(self, name, path=None, target=None):",
    "        if name.split('.')[0] in set(BLOCK.split(',')): raise ImportError('blocked ' + name)",
    "sys.meta_path.insert(0, B())",
    "import _bootstrap; _bootstrap.setup(sqlite=True)",
    "import app.inputdata.intake.router, app.inputdata.intake.service, app.inputdata.routers.inputdata",
    "from app.inputdata.intake.readers import xlsx_intake",
    "try:",
    "    xlsx_intake.openpyxl.load_workbook",
    "    print('NO-ERROR')",
    "except SystemExit as e:",
    "    print('MSG:' + str(e))",
]
code = "BLOCK = " + repr(BLOCK) + chr(10) + chr(10).join(LINES)
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=os.path.dirname(os.path.abspath(__file__)), env={**os.environ, "PYTHONUTF8": "1"})
check("openpyxl·docx·olefile·PIL·lxml·pptx 가 모두 없어도 라우터·서비스를 불러온다 (서버가 뜬다)", r.returncode == 0 and "MSG:" in r.stdout, (r.returncode, r.stdout[-200:], r.stderr[-300:]))
check("엑셀을 읽을 때만 '서버에 openpyxl 이 필요합니다' 안내가 나온다", "엑셀을 읽으려면 서버에 openpyxl" in r.stdout, r.stdout[-200:])

print(f"{chr(10)}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
