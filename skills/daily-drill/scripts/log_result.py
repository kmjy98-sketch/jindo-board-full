# -*- coding: utf-8 -*-
"""daily-drill 결과 기록 + (선택) 약점 SRS 등록/리뷰 채점.
기록은 .agent/state/drill_log.jsonl (세션 단위) + drill_items.jsonl (문항 단위, 2026-07-07).

사용:
  python .agent/skills/daily-drill/scripts/log_result.py \
    --units "민법|민법총설|신의칙,민법|물권관계|점유권" \
    --mc "9/12" --case "0.7" --weak "권리남용 요건;!사정변경 요건" --subject 민법 --srs \
    --srs-scores "1:5,3:2"   # SRS due 항목 채점(id:score 0~5) → SM-2 간격 갱신·졸업 판정(2026-07-07 결선)
    --items '[{"unit":"민법|채권법|경개","q":"세트-성립요건","ok":1,"sub":"3/3","conf":"!","phase":"블록"},...]'
    --pass "선택"   # 그 단원 전체를 기준충족 인출한 '한 바퀴' 완료 시에만 보드 +1(세션당 자동증가 폐지)

--items 스키마(P0-3, 2026-07-14 확장):
  conf:  확신도 1비트 마커 — "!"=확신, "?"=불확신, ""/생략=중립 (답안 표기에서 그대로 옮김)
  phase: "블록" | "혼합" — 세션 구조 3스텝(#52-B-0-2)의 성취 게이트 판정 근거
--weak 항목 접두 "!" = 고확신 오답('!'+오답) → SRS 등록 시 priority high(P0-3 규칙).
"""
import json, os, sys, subprocess
from datetime import datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_p = os.path.abspath(__file__)
while os.path.basename(_p) != '.agent' and os.path.dirname(_p) != _p:
    _p = os.path.dirname(_p)
sys.path.insert(0, os.path.join(_p, 'scripts'))
from _vault import VAULT_ROOT, vp  # noqa: E402

ROOT = VAULT_ROOT
STATE = vp(".agent", "state")
LOG = os.path.join(STATE, "drill_log.jsonl")
SRS = vp(".agent", "skills", "spaced-repetition", "scripts", "srs_scheduler.py")


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def board_bump(units, kind):
    """드릴 채점을 진도 보드 카운트에 반영. 선택형→'선택', 사례형→'사례' (별개)."""
    if not units:
        return
    import urllib.request
    import urllib.error
    body = json.dumps({"keys": units, "kind": kind, "delta": 1}).encode("utf-8")
    try:  # 1) 서버가 떠 있으면 즉시 반영(느린 드라이브 쓰기 대비 넉넉한 타임아웃)
        req = urllib.request.Request("http://localhost:8770/api/bump", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        print(f"  보드 {kind} +1: {len(units)}단원 (서버)" if r.get("ok")
              else f"  보드 {kind} 반영 실패(서버): {r}")
        return
    except urllib.error.URLError as e:
        # 연결 거부(서버 미가동)일 때만 자동기동 폴백. 타임아웃 등은 서버가 이미 썼을 수 있어 중복쓰기 금지.
        if not isinstance(getattr(e, "reason", None), ConnectionRefusedError):
            print(f"  보드 {kind} 반영 보류(서버 지연/오류): {e}")
            return
    except Exception as e:
        print(f"  보드 {kind} 반영 오류: {e}")
        return
    # 2) 서버 미가동 → 자동기동 후 1회 재시도(2026-07-05). v1 board_server.py 폐지(#49·#19-B).
    try:
        import time
        srv = vp("6.진도관리", "board_server_v2.py")
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, srv, "--no-browser"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        time.sleep(3)
        req = urllib.request.Request("http://localhost:8770/api/bump", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        print(f"  보드 {kind} +1: {len(units)}단원 (서버 자동기동)" if r.get("ok")
              else f"  보드 {kind} 반영 실패(자동기동 후): {r}")
    except Exception as e:
        print(f"  보드 {kind} 반영 보류 — 서버 자동기동 실패({e}). 6.진도관리/보드열기.bat 실행 후 재시도.")


def main():
    units = [u.strip() for u in (arg("--units", "") or "").split(",") if u.strip()]
    weak_raw = [w.strip() for w in (arg("--weak", "") or "").split(";") if w.strip()]
    # P0-3(2026-07-14): 접두 '!' = 고확신 오답 → SRS priority high. 기록에는 정규화 이름.
    weak = [w.lstrip("!").strip() for w in weak_raw]
    weak_hi = {w.lstrip("!").strip() for w in weak_raw if w.startswith("!")}
    subj = arg("--subject", "")
    rec = {"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "단원": units,
           "객관식": arg("--mc", ""), "사례": arg("--case", ""),
           "약점": weak, "메모": arg("--note", "")}
    if weak_hi:
        rec["고확신오답"] = sorted(weak_hi)
    os.makedirs(STATE, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"기록: {rec['날짜']} · 단원{len(units)} · 객관식 {rec['객관식']} · 사례 {rec['사례']} · 약점{len(weak)}")

    # ── 보드 역연동(근거 2026-06-22): 세션당 자동 +1 = 과다카운트(연구로 확인).
    #    '1패스'는 그 단원 '전체 집합'을 '기준충족 인출'한 한 바퀴. → --pass 로 확정할 때만 +1.
    #    --pass "선택" 또는 "사례"(쉼표 다중). 읽기(회독)는 별개·낮은 가중이라 여기서 안 올림(보드에서 수동).
    passes = [p.strip() for p in (arg("--pass", "") or "").split(",") if p.strip()]
    if units and "선택" in passes:
        board_bump(units, "선택")
    if units and "사례" in passes:
        board_bump(units, "사례")
    if units and not passes and (rec["객관식"] or rec["사례"]):
        print("  (보드 카운트 보류 — 세션당 자동증가 폐지. '한 바퀴 기준충족 완료' 시 --pass 선택/사례 로 +1)")

    # 문항 단위 로그(2026-07-07 감사 P0: 세션 집계만으론 재출제 정답률 산출 불가)
    items_raw = arg("--items", "")
    if items_raw:
        try:
            items = json.loads(items_raw)
            # P0-3(2026-07-14): conf("!"/"?"/""=중립)·phase("블록"|"혼합") 필드 검증(비표준은 경고 후 보존)
            _conf_ok, _phase_ok = {"!", "?", "", None}, {"블록", "혼합", None}
            with open(os.path.join(STATE, "drill_items.jsonl"), "a", encoding="utf-8") as f:
                for it in items:
                    it["날짜"] = rec["날짜"]
                    if it.get("conf") not in _conf_ok:
                        print(f'  [경고] conf 비표준값 "{it.get("conf")}" (허용: !/?/빈값) — 그대로 기록')
                    if it.get("phase") not in _phase_ok:
                        print(f'  [경고] phase 비표준값 "{it.get("phase")}" (허용: 블록/혼합) — 그대로 기록')
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            print(f"  문항로그 {len(items)}건 (drill_items.jsonl)")
        except Exception as e:
            print(f"  문항로그 실패: {e}")

    # SRS 리뷰 채점(2026-07-07 결선: 등록만 되고 간격이 안 돌던 P0 수리) — id:score 쌍
    srs_scores = [s for s in (arg("--srs-scores", "") or "").split(",") if s.strip()]
    if srs_scores and os.path.exists(SRS):
        for pair in srs_scores:
            try:
                iid, sc = pair.split(":")
                r = subprocess.run([sys.executable, SRS, "--review", iid.strip(), "--score", sc.strip()],
                                   capture_output=True, text=True, encoding="utf-8", timeout=20)
                print(f"  SRS 리뷰 [{iid}]={sc}: {(r.stdout or '').strip().splitlines()[-1] if r.stdout else 'ok'}")
            except Exception as e:
                print(f"  SRS 리뷰 실패 {pair}: {e}")

    if "--srs" in sys.argv and weak and os.path.exists(SRS):
        for w in weak:
            cmd = [sys.executable, SRS, "--add", w]
            if w in weak_hi:  # P0-3: 고확신 오답('!'+오답) → priority high
                cmd += ["--priority", "high"]
            if subj:
                cmd += ["--topic", subj]
            try:
                subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
                print(f"  SRS 등록: {w}{' [high·고확신오답]' if w in weak_hi else ''}"
                      f"{' ('+subj+')' if subj else ''}")
            except Exception as e:
                print(f"  SRS 실패: {w} — {e}")
    elif "--srs" in sys.argv and not os.path.exists(SRS):
        print("  (srs_scheduler.py 없음 — SRS 등록 생략)")


if __name__ == "__main__":
    main()
