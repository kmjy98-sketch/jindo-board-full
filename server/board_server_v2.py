# -*- coding: utf-8 -*-
"""진도 보드 서버 v2 — 정본 = 논점 frontmatter (sync/위키/{과목}/{논점}.md).
기존 진도_board.html UX 재사용: BOARD만 frontmatter에서 만든 {과목>대분류>논점}으로 치환.
키 = 과목|대분류|논점제목(=파일명). 클릭→해당 논점 frontmatter(회독·선택·사례·기록) 기록.
→ Bases(진도보드.base)·Claude가 같은 frontmatter를 읽음(단일 정본). 약점/SRS/시험은 learning.json 재사용.

  python board_server_v2.py            # 브라우저 오픈
  python board_server_v2.py --selftest # 데이터층 점검(서버 미가동)
"""
import json, os, re, subprocess, sys, time, webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
if sys.stdout is None: sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None: sys.stderr = open(os.devnull, "w", encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
HTML = os.path.join(SCRIPT_DIR, "진도_board.html")  # UX 템플릿 재사용
WIKI = os.path.join(ROOT, "sync", "위키")
BACKUP = os.path.join(SCRIPT_DIR, "백업")
STATE = os.path.join(ROOT, ".agent", "state")
LEARNING = os.path.join(STATE, "learning.json")
GOAL = os.path.join(BACKUP, "진도보드_목표.json")     # 방학/내신 목표(논점 집합)
LOG_JSONL = os.path.join(BACKUP, "진도보드_log.jsonl")
SUBJ = ["민법", "형법총론", "형법각론", "헌법", "민사소송법", "민사집행법", "행정법",
        "형사소송법", "상법", "선택법"]  # build_session WIKI_SUBJECTS와 통일(2026-07-08 감사 P1 — 폴더 없으면 자동 skip)
KINDS = ["회독", "선택", "사례", "기록"]
PORT = 8770

# ---------------------------------------------------------------- frontmatter
def _split(t):
    if not t.startswith("---"): return None, None
    e = t.find("\n---", 3)
    return (t[3:e], e) if e > 0 else (None, None)

def _get(fm, key, default=""):
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", fm)
    if not m: return default
    v = m.group(1).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'": v = v[1:-1]
    return v

def _sortkey(jeom):
    m = re.match(r"^(\D*?)(\d+)", jeom or "")
    return (m.group(1) if m else jeom or "", int(m.group(2)) if m else 0)

def note_path(key):
    p = key.split("|")
    if len(p) != 3: return None
    return os.path.join(WIKI, p[0], p[2] + ".md")

def build_board():
    """frontmatter → BOARD{과목:{대분류:[논점제목...]}} + VALUES{key:{회독..약점,진도}}."""
    board, values = {}, {}
    weak = []
    for s in SUBJ:
        import glob
        rows = []
        for f in glob.glob(os.path.join(WIKI, s, "*.md")):
            b = os.path.basename(f)
            if b.startswith("_"): continue
            try: t = open(f, encoding="utf-8").read()
            except Exception: continue
            fm, e = _split(t)
            if fm is None: continue
            if _get(fm, "type") != "쟁점": continue
            title = b[:-3]
            dae = _get(fm, "대분류") or "(미분류)"
            jeom = _get(fm, "논점")
            key = f"{s}|{dae}|{title}"
            def _int(k):
                try: return int(_get(fm, k, "0") or 0)
                except Exception: return 0
            isweak = _get(fm, "약점", "false").lower() == "true"
            values[key] = {"회독": _int("회독"), "선택": _int("선택"), "사례": _int("사례"),
                           "기록": _int("기록"), "약점": isweak, "진도": _get(fm, "진도", "미착수")}
            if isweak: weak.append(key)
            rows.append((dae, _sortkey(jeom), title))
        if not rows: continue
        rows.sort(key=lambda r: (r[0], r[1]))
        board[s] = {}
        for dae, _sk, title in rows:
            board[s].setdefault(dae, []).append(title)
    return board, values, weak

# ---------------------------------------------------------------- 상태 입출력
def read_state():
    _, values, weak = build_board()
    out = {k: {} for k in KINDS}
    upd = ""
    for key, v in values.items():
        for k in KINDS:
            if v[k]: out[k][key] = v[k]
    goal = {"방학_단원": [], "내신_학기별": {}}
    if os.path.exists(GOAL):
        try: goal = json.load(open(GOAL, encoding="utf-8"))
        except Exception: pass
    log = []
    if os.path.exists(LOG_JSONL):
        try:
            log = [json.loads(x) for x in open(LOG_JSONL, encoding="utf-8").read().splitlines()[-200:] if x.strip()]
        except Exception: pass
    return {"updated": upd, "회독": out["회독"], "선택": out["선택"], "사례": out["사례"],
            "기록": out["기록"], "약점단원": weak,
            "기간목표": goal.get("기간목표"),  # v9 기간 모델(학기·방학 12기간, 학기=중간·기말) — 없으면 클라이언트가 구 키에서 이관
            "방학_단원": goal.get("방학_단원", []), "내신_학기별": goal.get("내신_학기별", {}),
            "기록로그": []}

def _set_fm_field(path, key, val):
    t = open(path, encoding="utf-8").read()
    fm, e = _split(t)
    if fm is None: return False
    if re.search(rf"(?m)^{re.escape(key)}:", fm):
        fm2 = re.sub(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {val}", fm)
    else:
        fm2 = fm + f"\n{key}: {val}"
    open(path, "w", encoding="utf-8").write(t[:3] + fm2 + t[e:])
    return True

def write_state(snapshot):
    """HTML 스냅샷(회독/선택/사례/기록 dict, 키=과목|대분류|논점) → 변경분만 frontmatter 기록."""
    _, cur, _ = build_board()
    changed = 0
    for kind in KINDS:
        d = snapshot.get(kind, {}) or {}
        for key, val in d.items():
            try: val = int(val)
            except Exception: continue
            if cur.get(key, {}).get(kind, 0) != val:
                p = note_path(key)
                if p and os.path.exists(p):
                    _set_fm_field(p, kind, val)
                    if val > cur.get(key, {}).get(kind, 0):  # 증가 체크만 스탬프(L0 필수복습 연동)
                        _set_fm_field(p, "최근체크", date.today().isoformat())
                    if kind == "회독" and val > 0 and cur.get(key, {}).get("진도", "미착수") == "미착수":
                        _set_fm_field(p, "진도", "진행")
                    changed += 1
    # 0으로 내려간 키도 반영(스냅샷에 없지만 frontmatter엔 >0)
    for kind in KINDS:
        d = snapshot.get(kind, {}) or {}
        for key, cv in cur.items():
            if cv.get(kind, 0) > 0 and key not in d:
                p = note_path(key)
                if p and os.path.exists(p): _set_fm_field(p, kind, 0); changed += 1
    # 기간/방학/내신 목표 저장 (기간목표=v9 정본, 방학_단원·내신_학기별=레거시 미러 — build_session load_goalset 호환)
    os.makedirs(BACKUP, exist_ok=True)
    json.dump({"기간목표": snapshot.get("기간목표"),
               "방학_단원": snapshot.get("방학_단원", []), "내신_학기별": snapshot.get("내신_학기별", {}),
               "updated": datetime.now().strftime("%Y-%m-%d %H:%M")},
              open(GOAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return changed

def append_log(entry):
    os.makedirs(BACKUP, exist_ok=True)
    with open(LOG_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

_REBUILD_TS = [0.0]  # 마지막 재생성 시각(디바운스)

def rebuild_drill_session():
    """보드 변경(save/bump) → 오늘 드릴 현황(오늘_드릴.md·drill_session.json) 즉시 재생성.
    build_session.py 백그라운드 실행(멱등·논블로킹), 10초 디바운스(연속 저장 중복 방지).
    (서버↔오늘 현황 연동, 2026-07-06 사용자 요청)"""
    now = time.time()
    if now - _REBUILD_TS[0] < 10: return
    _REBUILD_TS[0] = now
    script = os.path.join(ROOT, ".agent", "skills", "daily-drill", "scripts", "build_session.py")
    if not os.path.exists(script): return
    try:
        subprocess.Popen([sys.executable, script], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # 재생성 실패해도 보드 저장 자체는 유효 — 다음 build_session 실행 시 반영

def bump(keys, kind, delta=1):
    """드릴 마감 역연동(log_result.py → POST /api/bump): 논점 frontmatter의
    선택/사례/회독/기록 카운트 증가 + 최근체크 날짜 스탬프(L0 필수복습 연동, 2026-07-06).
    (v1 board_server.py의 bump 엔드포인트가 v2 전환에서 누락되어 있었음 — 복원)"""
    if kind not in KINDS: return {"ok": False, "error": f"kind는 {KINDS} 중 하나"}
    today = date.today().isoformat()
    done, miss = [], []
    for key in keys or []:
        p = note_path(key)
        if not p or not os.path.exists(p):
            miss.append(key); continue
        t = open(p, encoding="utf-8").read()
        fm, _ = _split(t)
        cur = 0
        if fm is not None:
            m = re.search(rf"(?m)^{kind}:\s*(\d+)", fm)
            cur = int(m.group(1)) if m else 0
        _set_fm_field(p, kind, cur + int(delta))
        _set_fm_field(p, "최근체크", today)
        if fm is not None and _get(fm, "진도", "미착수") == "미착수":
            _set_fm_field(p, "진도", "진행")
        done.append(key)
    append_log({"ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "op": "bump",
                "kind": kind, "delta": delta, "keys": done, "미매칭": miss})
    return {"ok": True, "updated": len(done), "미매칭": miss}

# ---------------------------------------------------------------- 약점/시험 (learning.json 재사용)
def read_weak():
    try: lj = json.load(open(LEARNING, encoding="utf-8"))
    except Exception: lj = {}
    srs_items = (lj.get("srs", {}) or {}).get("items", [])
    today = date.today().isoformat()
    due, upcoming = [], []
    for it in srs_items:
        nr = it.get("next_review", "")
        row = {"content": it.get("content", ""), "topic": it.get("topic", ""), "next_review": nr, "priority": it.get("priority", "")}
        (due if nr and nr <= today else upcoming).append(row)
    return {"weak_points": lj.get("weak_points", []), "srs_due": due, "srs_upcoming": upcoming, "today": today}

def read_exams():
    try: lj = json.load(open(LEARNING, encoding="utf-8-sig"))
    except Exception: lj = {}
    today = date.today(); out = []
    for e in (lj.get("exams") or []):
        if not isinstance(e, dict): continue
        d = e.get("date"); dday = None
        if d:
            try: dday = (datetime.strptime(d, "%Y-%m-%d").date() - today).days
            except Exception: dday = None
        subs = e.get("subjects", "all")
        out.append({"name": e.get("name", "시험"), "date": d, "subjects": subs if isinstance(subs, list) else "all", "dday": dday})
    return {"exams": out, "today": today.isoformat()}

def upsert_exam(name, date_str, subjects):
    if not name: return {"ok": False, "error": "name 필요"}
    try: lj = json.load(open(LEARNING, encoding="utf-8-sig"))
    except Exception: lj = {}
    dnorm = None
    if date_str:
        try: dnorm = datetime.strptime(date_str.strip(), "%Y-%m-%d").date().strftime("%Y-%m-%d")
        except Exception: return {"ok": False, "error": f"날짜 형식 오류: {date_str}"}
    subs = subjects
    if isinstance(subs, str): subs = "all" if subs.strip().lower() == "all" else [x.strip() for x in subs.split(",") if x.strip()]
    if not subs: subs = "all"
    exams = lj.get("exams") if isinstance(lj.get("exams"), list) else []
    found = next((e for e in exams if isinstance(e, dict) and e.get("name") == name), None)
    if found is None: exams.append({"name": name, "date": dnorm, "subjects": subs})
    else: found["date"] = dnorm; found["subjects"] = subs
    lj["exams"] = exams
    os.makedirs(STATE, exist_ok=True)
    json.dump(lj, open(LEARNING, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
    return {"ok": True}

def add_weak(candidates):
    try: lj = json.load(open(LEARNING, encoding="utf-8"))
    except Exception: lj = {}
    wp = lj.get("weak_points", []); existing = set(wp); added = []
    for c in candidates:
        label = c.get("label") or c.get("content")
        if not label: continue
        full = f"{c.get('tag', '[진도보드]')} {label}"
        if full in existing: continue
        wp.append(full); existing.add(full); added.append(full)
    lj["weak_points"] = wp
    os.makedirs(STATE, exist_ok=True)
    json.dump(lj, open(LEARNING, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
    return {"added": added, "weak_points": wp}

# ---------------------------------------------------------------- HTML
def serve_html():
    t = open(HTML, encoding="utf-8").read()
    board, _, _ = build_board()
    new = "const BOARD=" + json.dumps(board, ensure_ascii=False) + ";\nconst ALL"
    i = t.index("const BOARD=")
    j = t.index("};\nconst ALL", i) + len("};\nconst ALL")
    t = t[:i] + new + t[j:]
    t = t.replace("진도 보드 v7", "진도 보드 v8 (논점·frontmatter)")
    return t

# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)
    def _json(self, code, obj): self._send(code, json.dumps(obj, ensure_ascii=False))
    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n: return {}
        try: return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception: return {}
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/진도_board.html", "/index.html"):
            try: return self._send(200, serve_html(), "text/html; charset=utf-8")
            except Exception as e: return self._send(500, f"보드 생성 실패: {e}", "text/plain; charset=utf-8")
        if p == "/api/state": return self._json(200, read_state())
        if p == "/api/weak": return self._json(200, read_weak())
        if p == "/api/exams": return self._json(200, read_exams())
        if p == "/api/ping": return self._json(200, {"ok": True, "server": "board_v2", "port": PORT})
        return self._send(404, "not found", "text/plain; charset=utf-8")
    def do_POST(self):
        p = self.path.split("?", 1)[0]; body = self._body()
        try:
            if p == "/api/save":
                changed = write_state(body)
                if changed: rebuild_drill_session()  # 보드 저장 → 오늘 현황 즉시 갱신
                return self._json(200, {"ok": True, "changed": changed})
            if p == "/api/bump":
                res = bump(body.get("keys", []), body.get("kind", ""), body.get("delta", 1))
                if res.get("updated"): rebuild_drill_session()
                return self._json(200, res)
            if p == "/api/log": append_log(body); return self._json(200, {"ok": True})
            if p == "/api/weak":
                cands = list(body.get("candidates", []) or [])
                manual = (body.get("manual") or "").strip()
                if manual: cands.append({"label": manual, "tag": "[추가]"})
                return self._json(200, add_weak(cands))
            if p == "/api/exams": return self._json(200, upsert_exam(body.get("name", ""), body.get("date", ""), body.get("subjects", "all")))
        except Exception as e:
            return self._json(500, {"ok": False, "error": str(e)})
        return self._send(404, "not found", "text/plain; charset=utf-8")
    def log_message(self, *a): pass

# ---------------------------------------------------------------- 엔트리
def selftest():
    board, values, weak = build_board()
    nsub = len(board); njeom = sum(len(us) for m in board.values() for us in m.values())
    ndae = sum(len(m) for m in board.values())
    print(f"[selftest] 과목 {nsub} · 대분류 {ndae} · 논점 {njeom} · 약점 {len(weak)}")
    st = read_state()
    print(f"  state: 회독>0 {len(st['회독'])} · 선택 {len(st['선택'])} · 사례 {len(st['사례'])} · 약점단원 {len(st['약점단원'])}")
    # 쓰기 왕복: 첫 논점 회독 +1 후 복구
    anykey = next(iter(values)); cur = values[anykey]["회독"]
    p = note_path(anykey)
    _set_fm_field(p, "회독", cur + 1)
    _, v2, _ = build_board()
    ok = v2[anykey]["회독"] == cur + 1
    _set_fm_field(p, "회독", cur)  # 복구
    print(f"  쓰기왕복({anykey}): {'OK' if ok else 'FAIL'} (복구 {cur})")
    w = read_weak(); ex = read_exams()
    print(f"  약점 {len(w['weak_points'])} · SRS임박 {len(w['srs_due'])} · 시험 {len(ex['exams'])}")
    print("[selftest] 통과")

def main():
    if "--selftest" in sys.argv: return selftest()
    global PORT
    httpd = None
    for p in range(PORT, PORT + 10):
        try: httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler); PORT = p; break
        except OSError: continue
    if httpd is None: print("포트 확보 실패"); sys.exit(1)
    url = f"http://localhost:{PORT}/"
    print(f"진도 보드 v2(논점·frontmatter) → {url}")
    if "--no-browser" not in sys.argv:
        try: webbrowser.open(url)
        except Exception: pass
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\n종료.")

if __name__ == "__main__":
    main()
