#!/usr/bin/env python3
"""AI 가 프롬프트대로 문제를 옮기는지 테스트한다.

테스트 팩(test_pack.jsonl)의 각 입력을 AI 에게 보내고, 출력을 protocol_check 의 검사와 기대 결과(expect)로 채점한다.
같은 입력을 --runs 번 반복해 결과가 일정한지도 본다.

사용법
  .env 에 GEMINI_API_KEY=키 (또는 ANTHROPIC_API_KEY=키) 와 LLM_MODEL=모델이름 을 적어 둔다 (환경변수도 가능)
  python run_ai_tests.py --api --runs 3 [--provider google|anthropic] [--model 모델이름] [--only T1,T3]
  python run_ai_tests.py --from-file ai_outputs.jsonl      # 채팅에서 직접 얻은 출력을 채점 (줄마다 {"test":"T1","text":"AI 출력 전체"})
  python run_ai_tests.py --mock good|bad                   # 도구 자체 점검용 (AI 를 흉내냄)
expect 항목: ids(출력 id 가 이 값으로 시작해야 함, 개수 일치) / ids_any / status / type / flags_any / snippets /
             answer_contains / correct_answers / no_test_cases / if_single_flags_any
             absent / min_test_cases / outputs_contain / cond_any / input_nonempty / 복구(있음|없음)  (엑셀·원본 충돌 테스트용)
"""
try:
    import sys as _s; _s.stdout.reconfigure(encoding="utf-8", errors="replace")      # Windows 콘솔(cp949)에서도 이모지 출력
except Exception: pass
import argparse, copy, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol_check import check_case, _nz
from app.inputdata.intake.llm import parse_lines            # 서버가 AI 출력을 읽는 방식과 같게 (아래 같은 이름의 옛 함수는 이것으로 덮어쓴다)
from app.inputdata.intake import llm, config


def _parse_lines_old(text):          # 옛 복사본 (더 이상 쓰지 않음). 서버의 ai_output.parse_lines 를 쓴다
    """AI 출력에서 JSON 한 줄씩 읽는다. (rows, 형식 오류 목록)"""
    rows, bad = [], []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("```"): continue
        try:
            d = json.loads(ln)
            if isinstance(d, dict) and "id" in d: rows.append(d); continue
        except ValueError:
            pass
        bad.append(ln[:50])
    return rows, bad


def evaluate(test, text, mode_skip_exec=False):
    exp, fails = test["expect"], []
    rows, bad = parse_lines(text)
    if bad: fails.append(f"형식: JSON 한 줄이 아닌 출력 {len(bad)}줄 (예: {bad[0]!r})")
    if not rows: return fails + ["형식: 읽을 수 있는 결과가 없음"]
    ids = [r["id"] for r in rows]
    # ids
    cands = exp.get("ids_any") or [exp.get("ids")]
    ok_ids = any(c and len(c) == len(ids) and all(any(i.startswith(e) for i in ids) for e in c) for c in cands)
    single = ids and len(ids) == 1 and exp.get("ids_any") and len(exp["ids_any"][-1]) == 1
    if not ok_ids: fails.append(f"ids: 기대 {cands} / 실제 {ids}")
    # 상태
    want = exp.get("status")
    if want:
        got = {r.get("review", {}).get("상태") for r in rows}
        if got != {want}: fails.append(f"상태: 기대 {want} / 실제 {sorted(map(str, got))}")
    # 공통 검사 (스키마·조건 형식·정답코드 실행·원본 보존 …)
    seen, src = {}, test["input"].get("원본조각")
    for r in rows:
        c = {"id": r["id"], "payload": r.get("payload"), "review": r.get("review") or {}}
        if src: c["원본조각"] = src
        f, _ = check_case(c, seen, mode_skip_exec)
        fails += [f"{r['id']} {m}" for m in f]
    pls = [r["payload"] for r in rows if r.get("payload")]
    notes = " ".join(" ".join(r.get("review", {}).get("확인필요") or []) + " " + json.dumps(r.get("review", {}).get("조언") or [], ensure_ascii=False) + " " + " ".join(r.get("review", {}).get("참고") or []) for r in rows)
    def flags(groups, label):
        for g in groups:
            if not any(k in notes for k in g): fails.append(f"{label}: 확인필요/조언에 {g} 중 어느 것도 없음")
    for r in rows:                            # 모든 시험 공통: AI 는 실행할 수 없으므로 '실행 일치' 같은 검증 표기를 쓰면 안 됨
        for f in (r.get("review") or {}).get("채움") or []:
            if isinstance(f, dict) and f.get("검증") not in ("손 추적", "자료 일치", "미검증"): fails.append(f"검증값: {r['id']} 채움 '{f.get('항목')}' 의 검증이 {f.get('검증')!r} (손 추적 | 자료 일치 | 미검증 만 가능)")
    for ch in exp.get("code_absent", []):     # 코드·입출력에 남으면 안 되는 문자 (워드 자동 고침 따옴표 등)
        for p in pls:
            blob = json.dumps([p.get("base_code"), p.get("reference_codes"), p.get("test_cases")], ensure_ascii=False)
            if ch in blob: fails.append(f"code_absent: 코드·입출력에 {ch!r} 가 남아 있음 (원래 문자로 되돌려야 함)"); break
    flags(exp.get("flags_any", []), "flags")
    if single: flags(exp.get("if_single_flags_any", []), "flags(분할 안 한 경우)")
    if exp.get("type") and any(p.get("problemType") != exp["type"] for p in pls): fails.append(f"type: 기대 {exp['type']} / 실제 {[p.get('problemType') for p in pls]}")
    for s in exp.get("snippets", []):
        if not any(_nz(s) in _nz(p.get("description")) for p in pls): fails.append(f"snippets: 설명에 {s!r} 없음")
    if exp.get("answer_contains"):
        blob = json.dumps([p.get("answer_text") for p in pls], ensure_ascii=False)
        for a in exp["answer_contains"]:
            if a not in blob: fails.append(f"answer: 정답에 {a!r} 없음")
    if "correct_answers" in exp and not any(p.get("correct_answers") == exp["correct_answers"] for p in pls):
        fails.append(f"correct_answers: 기대 {exp['correct_answers']} / 실제 {[p.get('correct_answers') for p in pls]}")
    # 엑셀과 원본이 충돌하는 경우를 보는 항목
    for s in exp.get("absent", []):          # 설명에 있으면 안 되는 문구 (엑셀 쪽 요약본이 남았는지)
        if any(_nz(s) in _nz(p.get("description")) for p in pls): fails.append(f"absent: 설명에 {s!r} 가 남아 있음 (원본이 아니라 엑셀 값을 씀)")
    if exp.get("min_test_cases") and not any(len(p.get("test_cases") or []) >= exp["min_test_cases"] for p in pls):
        fails.append(f"min_test_cases: 테스트 케이스가 {exp['min_test_cases']}개 이상이어야 함 (실제 {[len(p.get('test_cases') or []) for p in pls]})")
    for s in exp.get("outputs_contain", []):  # 기대 출력에 들어 있어야 하는 값 (줄바꿈 포함 그대로)
        outs = [tc.get("expected_output", "") for p in pls for tc in (p.get("test_cases") or [])]
        if not any(s in o.replace("\r\n", "\n") for o in outs): fails.append(f"outputs_contain: 테스트 케이스 출력에 {s!r} 없음")
    for g in exp.get("cond_any", []):         # 조건에 들어 있어야 하는 키워드 묶음 (분할된 문제 전체에서 각각)
        conds = [" ".join(p.get("problem_condition") or []) for p in pls]
        if not any(any(k in c for k in g) for c in conds): fails.append(f"cond_any: problem_condition 에 {g} 중 어느 것도 없음")
    if exp.get("복구") in ("있음", "없음"):
        rec = [r.get("review", {}).get("복구") for r in rows]
        if exp["복구"] == "있음" and not any(rec): fails.append("복구: 원본으로 바꾼 내용이 복구에 기록되어야 함")
        if exp["복구"] == "없음" and any(rec): fails.append(f"복구: 일치하는 입력인데 복구가 기록됨 {rec}")
    if exp.get("input_nonempty") and not any((tc.get("input") or "").strip() for p in pls for tc in (p.get("test_cases") or [])):
        fails.append("input_nonempty: 입력이 필요한 프로그램인데 test_cases 의 input 이 모두 비어 있음")
    if exp.get("no_test_cases") and not all(p.get("test_cases") == [] and p.get("problem_condition") for p in pls):
        fails.append("no_test_cases: test_cases 는 [] 이고 problem_condition 이 1개 이상이어야 함")
    return fails


def call_api(prompt, user_text, model, key, url=None, provider="anthropic", max_tokens=12000):
    """(호환용) llm.call_llm 으로 보낸다."""
    return llm.call_llm(provider, model, key, prompt, user_text, max_tokens, url)


def degrade(lines):
    """모의 'bad' AI: 확인필요·조언을 비우고, 설명을 자르고, 기대 출력을 망가뜨린다."""
    out = copy.deepcopy(lines)
    for r in out:
        r["review"]["확인필요"], r["review"]["조언"] = [], []
        p = r.get("payload")
        if r["review"].get("상태") == "보류":          # 보류해야 할 문제를 마음대로 지어내 등록하는 AI
            r["review"]["상태"], r["review"]["보류사유"] = "등록가능", None
            r["payload"] = p = {"problemType": "코딩", "title": r["id"], "description": "임의로 만든 설명", "test_cases": [{"input": "", "expected_output": "x"}],
                                "reference_codes": [{"language": "python", "code": "print('x')"}]}
        if p and p.get("correct_answers"): p["correct_answers"] = [c + 1 for c in p["correct_answers"]]
        if p and p.get("problemType") == "주관식": p["answer_text"] = ""
        if p:
            p["description"] = p["description"][: len(p["description"]) // 3]
            for tc in p.get("test_cases", []): tc["expected_output"] = "WRONG"
            if p.get("answer_text"): p["answer_text"] = {"1": ["?"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="test_pack.jsonl"); ap.add_argument("--prompt", default=config.prompt_path(), help="기본: 서버가 쓰는 intake/prompt.md")
    ap.add_argument("--reference", default="test_reference.jsonl"); ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only"); ap.add_argument("--model"); ap.add_argument("--provider", choices=["google", "anthropic"])
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--thinking", help="Google 모델의 생각 정도: minimal/low/medium/high(3 계열) 또는 숫자(2.5 계열). 기본: .env 의 LLM_THINKING, 없으면 모델 기본값")
    ap.add_argument("--max-call-failures", type=int, default=2, help="AI 서버 문제로 연속 이 횟수만큼 호출에 실패하면 중단 (기본 2)")
    ap.add_argument("--retry-waits", default=",".join(str(x) for x in llm.RETRY_WAITS), help="혼잡·한도 오류 때 기다릴 시간(초, 쉼표). 기본 3,8,20,45")
    ap.add_argument("--api", action="store_true"); ap.add_argument("--mock", choices=["good", "bad"]); ap.add_argument("--from-file")
    ap.add_argument("--api-url", help="테스트용으로 호출 주소를 바꿀 때만 사용"); ap.add_argument("--skip-exec", action="store_true")
    ap.add_argument("--mode", default="none", help="요청의 채점 모드 값")
    ap.add_argument("--save", help="AI 출력 원문을 이 파일에 JSONL 로 남긴다 ({test, run, model, text}). 실패 원인을 볼 때 쓴다")
    a = ap.parse_args()
    pack = [json.loads(l) for l in open(a.pack, encoding="utf-8") if l.strip()]
    if a.only: pack = [t for t in pack if t["test"] in a.only.split(",")]
    ref = {r["test"]: r["lines"] for r in (json.loads(l) for l in open(a.reference, encoding="utf-8"))} if a.mock and os.path.exists(a.reference) else {}
    files = {}
    if a.from_file:
        for l in open(a.from_file, encoding="utf-8"):
            if l.strip(): d = json.loads(l); files.setdefault(d["test"], []).append(d["text"])
    prompt = open(a.prompt, encoding="utf-8").read() if a.api else ""
    provider = model = key = None
    thinking = a.thinking or os.environ.get("LLM_THINKING") or None
    waits = [float(x) for x in a.retry_waits.split(",") if x.strip()]
    if a.api:
        provider, model, key = llm.resolve(a.provider, a.model)
    on_retry = lambda i, n, w, why: print(f"  … AI 서버가 응답하지 않습니다 ({why}). {w:g}초 뒤 다시 시도합니다 ({i}/{n})", flush=True)
    if not (a.api or a.mock or a.from_file): raise SystemExit("--api, --mock, --from-file 중 하나를 고르세요.")
    results, consec, stopped_at = [], 0, None
    for idx, t in enumerate(pack):
        if consec >= a.max_call_failures: stopped_at = idx; break
        runs = []
        for k in range(a.runs):
            if a.mock:
                if t["test"] not in ref: runs.append(None); continue
                text = "\n".join(json.dumps(x, ensure_ascii=False) for x in (ref[t["test"]] if a.mock == "good" else degrade(ref[t["test"]])))
            elif a.from_file:
                tl = files.get(t["test"], [])
                if k >= len(tl): runs.append(None); continue
                text = tl[k]
            else:
                try:
                    info = {}
                    user_msg = f"채점 모드: {a.mode}\n입력: " + json.dumps(t["input"], ensure_ascii=False)
                    text = llm.call_llm(provider, model, key, llm.trim_prompt(prompt, user_msg), user_msg, a.max_tokens, a.api_url,
                                        waits=waits, on_retry=on_retry, info=info, thinking=thinking)
                    print(f"  {t['test']} {llm.format_usage(info)}", flush=True)
                except llm.FatalLLMError as e:          # 키·모델 설정 오류: 계속해도 같은 실패라서 바로 멈춘다
                    raise SystemExit(f"AI 호출을 계속할 수 없어 중단합니다.\n  {e}")
                except Exception as e:                   # 혼잡·네트워크 등 일시적 오류: 규칙 위반과 구분해서 기록한다
                    runs.append({"call_error": str(e).splitlines()[0][:160]}); continue
            if a.save:
                with open(a.save, "a", encoding="utf-8") as sf: sf.write(json.dumps({"test": t["test"], "run": k, "model": model, "text": text}, ensure_ascii=False) + chr(10))
            runs.append(evaluate(t, text, a.skip_exec))
        results.append((t, runs))
        calls_only = bool(runs) and all(isinstance(x, dict) for x in runs)
        consec = consec + 1 if calls_only else 0
    tot_pass = tot_run = n_call = 0
    print(f"{'테스트':<5} {'통과':<7} 설명")
    for t, runs in results:
        evals = [x for x in runs if isinstance(x, list)]; calls = [x for x in runs if isinstance(x, dict)]
        if not evals and not calls: print(f"{t['test']:<5} {'건너뜀':<7} {t['desc']}  (참조/출력 없음)"); continue
        n_call += len(calls)
        if not evals:
            print(f"{t['test']:<5} {'호출실패':<6} {t['desc']}"); print(f"        ⚠ AI 서버 문제로 채점하지 못함: {calls[0]['call_error']}"); continue
        ok = sum(1 for x in evals if not x); tot_pass += ok; tot_run += len(evals)
        print(f"{t['test']:<5} {ok}/{len(evals):<5} {t['desc']}" + (f"  (호출 실패 {len(calls)}회 제외)" if calls else ""))
        seen = {}
        for x in evals:
            for m in x: seen[m] = seen.get(m, 0) + 1
        for m, n in sorted(seen.items(), key=lambda x: -x[1])[:4]: print(f"        ✗ ({n}/{len(evals)}회) {m[:150]}")
    if stopped_at is not None:
        for t in pack[stopped_at:]: print(f"{t['test']:<5} {'중단':<7} {t['desc']}")
        print(f"\n⚠ AI 서버 문제로 연속 {a.max_call_failures}개 테스트의 호출이 실패해 나머지 {len(pack) - stopped_at}개를 중단했습니다. 서버가 혼잡한 시간대를 피해 다시 실행하세요.")
    print(f"\n합계: {tot_pass}/{tot_run} 통과" + ("" if tot_run else " (채점된 테스트 없음)"))
    if n_call: print(f"호출 실패 {n_call}건: AI 서버 문제(혼잡·한도)로 채점하지 못했습니다. 프롬프트 규칙 위반이 아니므로 잠시 뒤 다시 실행하세요.")
    sys.exit(0 if tot_pass == tot_run and tot_run and not n_call and stopped_at is None else 1)


if __name__ == "__main__":
    main()
