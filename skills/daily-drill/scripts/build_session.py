# -*- coding: utf-8 -*-
"""daily-drill 세션 구성: 오늘 풀 논점 + 복습(SRS due) + 소스 후보 + 사례 대기.
정본 = sync/위키/{과목}/*.md frontmatter (회독·선택·사례·약점·진도·대분류).
키 = 과목|대분류|논점(=파일명 제목). (#19-B·#50·#51)
  .agent/state/drill_session.json  (기계용)
  6.진도관리/오늘_드릴.md           (사람용 브리프)
생성. 선정·소스포인터까지만 — 출제/채점은 Claude가 소스를 직접 읽고 한다(#1).

사용:
  python .agent/skills/daily-drill/scripts/build_session.py [--n 6] [--subject 민법] [--export 경로]
  L0 당일복습(#52-C): --today "민법/대상청구권,민사소송법/기판력"
    → 해당 논점 frontmatter에 최근수업: 오늘 기록 + 당일복습 트랙 출력.
    --today 없이도 최근수업이 오늘·어제인 논점은 자동으로 당일복습 트랙에 포함(익일 재출제).

일일 문항 예산·L0 정원(P0-1, 2026-07-14 — 과부하 설계→완주 실패 연쇄 차단):
  learning.json 설정 키(수치 정본 — 코드 기본값은 폴백):
    daily_question_budget: 일일 총 문항 예산 상한(기본 50)
    l0_capacity:           L0 필수복습 논점 정원(기본 4, 초과분은 l0_carryover.json 익일 이월)
    questions_per_topic:   진도·복습 논점당 추정 문항수(기본 8)
    l0_questions_per_topic: L0 논점당 추정 문항수(기본 5)
  예산 초과 시 보존 우선순위 L0 > 약점 > (목표 > 전체롤링) > 진도 순으로 남기고 절사.
  절사·이월 내역은 브리프·JSON·stdout에 반드시 표기(무단 축소 금지 — 사용자가 본다).
"""
import json, os, re, glob, sys, subprocess
from datetime import datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_p = os.path.abspath(__file__)  # noqa: E402
while os.path.basename(_p) != '.agent' and os.path.dirname(_p) != _p:  # noqa: E402
    _p = os.path.dirname(_p)  # noqa: E402
sys.path.insert(0, os.path.join(_p, 'scripts'))  # noqa: E402
from _vault import VAULT_ROOT, vp  # noqa: E402

ROOT = VAULT_ROOT
STATE = os.path.join(ROOT, ".agent", "state")
INBOX = os.path.join(ROOT, "6.진도관리", "사례답안")
DRILL_LOG = os.path.join(STATE, "drill_log.jsonl")
LEARNING = os.path.join(STATE, "learning.json")
OUT_JSON = os.path.join(STATE, "drill_session.json")
OUT_MD = os.path.join(ROOT, "6.진도관리", "오늘_드릴.md")
SRS = os.path.join(ROOT, ".agent", "skills", "spaced-repetition", "scripts", "srs_scheduler.py")
WIKI_ROOT = os.path.join(ROOT, "sync", "위키")  # 정본 경로 (#50-B)
CARDS = os.path.join(ROOT, "outputs", "02_cards_v37")  # 정본 카드. 새 카드도 여기 두면 자동 연동
CASE_IDX = os.path.join(STATE, "case_problem_answer_index.json")

# 위키 과목 폴더 목록 (#50-B: 약칭 금지, 풀네임 사용)
# board_server_v2.py SUBJ + 추가 과목
WIKI_SUBJECTS = [
    "민법", "형법총론", "형법각론", "헌법",
    "민사소송법", "민사집행법", "행정법",
    "형사소송법", "상법", "선택법",
]

# 카드 정본(02_cards_v37) 과목 분류 — 파일명 키워드(1차) + frontmatter 과목(새 책 폴백).
# 새 카드 파일을 02_cards_v37 에 추가하면 키워드/과목태그로 자동 연동된다(하드코딩 목록 아님).
CARD_KEYWORDS = {
    "민법": ["논점민법재산법", "민사사례연습", "민사례", "사례연습_가족", "사례연습_담보",
            "사례연습_물권", "사례연습_민총", "사례연습_채권", "신민사법선택형",
            "쟁점노트_가족법", "쟁점노트_재산법", "찌라시_민법",
            "컴민법", "포섭트리거_민법", "사례풀이순서_민법"],
    "민사소송법": ["논점민소", "쟁점노트_소송집행", "찌라시_민사소송법",
              "민소사례", "포섭트리거_민사소송법", "사례풀이순서_민사소송법"],
    "민사집행법": ["기초법리집행법", "쟁점노트_소송집행", "찌라시_민사집행", "논점민사집행법"],
    "형법총론": ["compact형총", "김기용형총", "반반형법", "찌라시_형법",
             "포섭트리거_형법총론", "사례풀이순서_형법총론"],
    "형법각론": ["작은변사기", "반반형법", "찌라시_형법",
             "포섭트리거_형법각론", "사례풀이순서_형법각론"],
    "형사소송법": ["찌라시_형사소송법"],
    "헌법": ["강성민OX", "유니온헌법기출", "해커스헌법사례", "헌법핵심정리300", "찌라시_헌법",
           "포섭트리거_헌법", "사례풀이순서_헌법"],
    "상법": ["찌라시_상법"],
    "행정법": ["찌라시_행정법", "행정법강해"],
    "선택법": ["법조윤리"],
}
# (2026-09-06) 키워드 누락으로 과목단위 폴백에서 빠지던 77파일(행정법강해 47·컴민법 14·민소사례 7·
#  포섭트리거 5·사례풀이순서 4) 추가. 행정법 드릴은 종전엔 찌라시 1파일만 보였다.
_SUBJ_NORM = {"민사": "민법", "공법": "헌법", "법조윤리": "선택법",
              "형법": "형법총론"}  # frontmatter 과목 정규화


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


# ── 정본: frontmatter 파싱 (board_server_v2 _split/_get 참조) ──────────────────
def _fm_split(text):
    """frontmatter 블록(---..---) 추출. (raw_fm, end_idx) or (None, None)."""
    if not text.startswith("---"):
        return None, None
    e = text.find("\n---", 3)
    return (text[3:e], e) if e > 0 else (None, None)


def _fm_get(fm, key, default=""):
    """frontmatter에서 key 값 추출."""
    if fm is None:
        return default
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", fm)
    if not m:
        return default
    v = m.group(1).strip()
    # 따옴표 제거
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _fm_int(fm, key, default=0):
    try:
        return int(_fm_get(fm, key, str(default)) or default)
    except (ValueError, TypeError):
        return default


def build_pool_from_wiki(subj_filter=None):
    """sync/위키/{과목}/*.md frontmatter → pool 행 목록.
    키 = 과목|대분류|논점(파일명). board_server_v2.build_board() 참조.
    """
    pool = []
    for subj in WIKI_SUBJECTS:
        if subj_filter and subj != subj_filter:
            continue
        folder = os.path.join(WIKI_ROOT, subj)
        if not os.path.isdir(folder):
            print(f"  [경고] 위키 폴더 없음 → 드릴 불가 과목: {subj} (침묵 누락 방지, 2026-07-07)")
            continue
        for f in glob.glob(os.path.join(folder, "*.md")):
            b = os.path.basename(f)
            if b.startswith("_"):
                continue
            try:
                text = open(f, encoding="utf-8").read()
            except Exception:
                continue
            fm, _ = _fm_split(text)
            if fm is None:
                continue
            if _fm_get(fm, "type") != "쟁점":
                continue
            title = b[:-3]  # 파일명 = 논점 제목
            dae = _fm_get(fm, "대분류") or "(미분류)"
            key = f"{subj}|{dae}|{title}"
            pool.append({
                "key": key,
                "과목": subj,
                "대분류": dae,
                "소단원": title,   # 하위호환: 논점 제목을 소단원으로 노출
                "회독": _fm_int(fm, "회독"),
                "선택": _fm_int(fm, "선택"),
                "사례": _fm_int(fm, "사례"),
                "약점": _fm_get(fm, "약점", "false").lower() == "true",
                "진도": _fm_get(fm, "진도", "미착수"),
                "원문": _fm_get(fm, "원문"),     # 소스 포인터 (outputs/ 경로)
                "책": _fm_get(fm, "책") or _fm_get(fm, "출처"),
                "방학": False,      # 방학목표는 아래에서 목표 파일 참조
                "최근드릴": "",
                "최근수업": _fm_get(fm, "최근수업", ""),  # L0 당일복습(#52-C)
                "최근체크": _fm_get(fm, "최근체크", ""),  # 진도보드 체크 일자(L0 필수복습 연동, 2026-07-06)
            })
    return pool


def mark_recent_lesson(names, today):
    """--today "과목/논점,…" → 해당 논점 frontmatter에 최근수업: 오늘 기록 (L0, #52-C)."""
    done, miss = [], []
    for n in names:
        p = os.path.join(WIKI_ROOT, *n.split("/")) + ".md"
        if not os.path.exists(p):
            miss.append(n); continue
        t = open(p, encoding="utf-8").read()
        e = t.find("\n---", 3)
        if not t.startswith("---") or e < 0:
            miss.append(n); continue
        fm = t[3:e]
        if re.search(r"(?m)^최근수업:", fm):
            fm = re.sub(r"(?m)^최근수업:.*$", f"최근수업: {today}", fm)
        else:
            fm = fm + f"\n최근수업: {today}"
        open(p, "w", encoding="utf-8").write(t[:3] + fm + t[e:])
        done.append(n)
    return done, miss


# ── 방학목표 파일 참조 (board_server_v2 GOAL 호환) ────────────────────────────
GOAL = os.path.join(ROOT, "6.진도관리", "백업", "진도보드_목표.json")


def load_banghak():
    if os.path.exists(GOAL):
        try:
            g = json.load(open(GOAL, encoding="utf-8"))
            return set(g.get("방학_단원", []))
        except Exception:
            pass
    return set()


def load_goalset():
    """'하고 있는 것' 집합(3계층 복습 스코프). v9(2026-07-13): 기간목표.현재 기간의 단원 우선
    — 보드가 [현재로 지정]한 당장 목표가 곧 드릴 스코프. 기간목표 없거나 현재 미지정이면
    구 키 폴백(방학_단원 ∪ 내신_학기별[현재 학기], 내신 키 'YYYY-1'/'YYYY-2' 규약, 2026-07-07)."""
    if not os.path.exists(GOAL):
        return set()
    try:
        g = json.load(open(GOAL, encoding="utf-8"))
    except Exception:
        return set()
    pg = g.get("기간목표") or {}
    cur = pg.get("현재")
    bucket = (pg.get("기간별") or {}).get(cur) if cur else None
    if isinstance(bucket, dict) and bucket.get("단원"):
        return set(bucket["단원"])
    s = set(g.get("방학_단원", []))
    now = datetime.now()
    sem = f"{now.year}-{1 if now.month <= 6 else 2}"
    for k, v in (g.get("내신_학기별", {}) or {}).items():
        if sem in str(k) and isinstance(v, list):
            s.update(v)
    return s


# ── SRS / 드릴 로그 ────────────────────────────────────────────────────────────
def srs_due():
    if not os.path.exists(SRS):
        return ""
    try:
        out = subprocess.run([sys.executable, SRS, "--today"],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def last_drilled():
    """drill_log.jsonl에서 논점별 최근 드릴 날짜(키=과목|대분류|논점)."""
    seen = {}
    if not os.path.exists(DRILL_LOG):
        return seen
    for ln in open(DRILL_LOG, encoding="utf-8"):
        try:
            d = json.loads(ln)
            # 새 키(과목|대분류|논점) 기록 우선
            for u in d.get("논점", d.get("단원", [])):
                seen[u] = d.get("날짜", "")
        except Exception:
            pass
    return seen


def weak_unit_keys():
    """learning.json weak_points → 논점 키(과목|대분류|논점) 집합.
    형식: '[진도보드] 과목>대분류>논점 …' 또는 '과목|대분류|논점'."""
    keys = set()
    try:
        lj = json.load(open(LEARNING, encoding="utf-8"))
    except Exception:
        return keys
    subs = "|".join(WIKI_SUBJECTS)
    # 과목>대분류>논점 형식
    pat = re.compile(rf"({subs})>([^>]+)>([^—\n]+?)(?:\s*—|$)")
    for w in lj.get("weak_points", []):
        m = pat.search(w or "")
        if m:
            keys.add(f"{m.group(1)}|{m.group(2)}|{m.group(3).strip()}")
        # 파이프 키 직접 포함된 경우
        pipe = re.search(r"([가-힣A-Za-z]+\|[^|\n]+\|[^|\n]+)", w or "")
        if pipe:
            keys.add(pipe.group(1).strip())
    return keys


# ── 카드 파일 매칭 ─────────────────────────────────────────────────────────────
def _frontmatter_subject(path):
    """카드 파일 frontmatter 의 '과목:' 값을 정규화해 반환(없으면 None)."""
    try:
        head = open(path, encoding="utf-8").read(1200)
    except Exception:
        return None
    m = re.search(r"^\s*과목\s*[:：]\s*([^\n/|—]+)", head, re.M)
    if not m:
        return None
    v = (m.group(1).strip().split() or [""])[0]
    v = _SUBJ_NORM.get(v, v)
    return v if v in CARD_KEYWORDS else None


_CARD_INDEX = None


def _card_index():
    """02_cards_v37 전체를 1회 스캔해 과목별 카드파일 목록(파일명 키워드→frontmatter 폴백)."""
    global _CARD_INDEX
    if _CARD_INDEX is not None:
        return _CARD_INDEX
    idx = {s: [] for s in CARD_KEYWORDS}
    for fp in glob.glob(os.path.join(CARDS, "*.md")):
        name = os.path.basename(fp)
        matched = False
        for subj, kws in CARD_KEYWORDS.items():
            if any(k in name for k in kws):
                idx[subj].append(fp); matched = True
        if not matched:
            fs = _frontmatter_subject(fp)
            if fs in idx:
                idx[fs].append(fp)
    _CARD_INDEX = {s: sorted(set(v)) for s, v in idx.items()}
    return _CARD_INDEX


def card_files(subj):
    return _card_index().get(subj, [])


# ── 논점별 카드 매칭: 원문(outputs/ 경로) 기반 ────────────────────────────────
# 논점 frontmatter `원문: outputs/01_ocr_llamaparse/{책}_llamaparse_p{범위}.md`
# 대응 카드:  outputs/02_cards_v37/{책}_llamaparse_p{범위}_암기장_v37.md
_PAGE_RE = re.compile(r"_p0*(\d+)-0*(\d+)")


def _원문_to_card_paths(원문):
    """원문 경로 → 매칭 카드 파일 후보 목록.
    원문: 'outputs/01_ocr_llamaparse/{책}_llamaparse_p{s}-{e}.md' (뒤에 ' (p.N)' 주석·', ' 다중 경로 허용)
    카드: 'outputs/02_cards_v37/{책}[_llamaparse]_p{s}-{e}*_v37.md'
    1차 같은 페이지 범위 glob → 2차 같은 책에서 페이지 구간이 겹치는 파일 → 3차 책 prefix 앞 3개.
    (2026-09-06 수정: 종전 코드는 basename에 원문 전체 문자열의 오프셋을 적용해 book_part가
     파일명 전체가 되어 glob이 항상 실패 → 사실상 전 논점이 과목단위 폴백으로 떨어졌다.)
    """
    if not 원문:
        return []
    m = _PAGE_RE.search(원문)
    if not m:
        return []
    # 다중 경로·괄호 주석 대비: 첫 파일명만 사용. 오프셋은 basename 기준으로 다시 계산.
    base = os.path.basename(원문[:m.end()])
    mb = _PAGE_RE.search(base)
    if not mb:
        return []
    book_part = base[:mb.start()]          # e.g. "쟁점노트_재산법_llamaparse"
    page_part = mb.group(0)                # e.g. "_p481-510"
    s, e = int(mb.group(1)), int(mb.group(2))
    book_glob = book_part.replace("_llamaparse", "*")   # 카드 파일명의 llamaparse 유무 허용
    # 1차: 같은 책·같은 페이지 범위
    hits = glob.glob(os.path.join(CARDS, f"{book_glob}{page_part}*_v37.md"))
    if not hits:
        # 2차: 같은 책에서 페이지 구간이 겹치는 카드 파일(행정법강해처럼 A번호 단위로 잘린 책)
        book_prefix = book_part.replace("_llamaparse", "")
        for fp in glob.glob(os.path.join(CARDS, f"{book_prefix}*_v37.md")):
            mm = _PAGE_RE.search(os.path.basename(fp))
            if mm and int(mm.group(1)) <= e and int(mm.group(2)) >= s:
                hits.append(fp)
    if not hits:
        # 3차: 책 이름 prefix 폴백(페이지 부정확 — 브리프에 과목단위로 표기됨)
        hits = glob.glob(os.path.join(CARDS, f"{book_glob}*_v37.md"))[:3]
    return sorted(set(hits))


def attach_sources(targets):
    """각 대상 논점에 카드파일·원문 포인터를 붙인다(출제 소스).
    1차: 원문 frontmatter → 매칭 카드 glob.
    2차: 과목 단위 card_files 폴백."""
    for t in targets:
        원문 = t.get("원문", "")
        unit_cards = _원문_to_card_paths(원문)
        if unit_cards:
            t["카드파일"] = [os.path.relpath(f, ROOT) for f in unit_cards][:6]
            t["카드범위"] = "논점단위"
        else:
            t["카드파일"] = [os.path.relpath(f, ROOT) for f in card_files(t["과목"])][:6]
            t["카드범위"] = "과목단위"
        # 원문 경로 (절대→상대)
        if 원문:
            t["원문경로"] = 원문  # 이미 상대경로 형식
        else:
            t["원문경로"] = ""
    return targets


# ── 사례 인덱스 ───────────────────────────────────────────────────────────────
def load_case_index():
    if os.path.exists(CASE_IDX):
        try:
            return json.load(open(CASE_IDX, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def case_for_unit(idx, key):
    """논점 키(과목|대분류|논점)에 진도매핑된 사례 문제 목록."""
    out = []
    for p in idx.get("problems", []):
        if key in p.get("진도매핑", []):
            out.append({"id": p.get("id"), "title": p.get("title", ""),
                        "points": p.get("points"), "book": p.get("book", ""),
                        "question": p.get("question"), "answer": p.get("answer")})
    return out


def load_case_notes():
    """사례노트(sync/위키/사례/{과목}/) 쟁점 백링크 → {논점제목: [사례노트]} 인덱스 (#50-B·#51 사례층 닫힌루프)."""
    idx = {}
    base = os.path.join(ROOT, "sync", "위키", "사례")
    if not os.path.isdir(base):
        return idx
    for f in glob.glob(os.path.join(base, "*", "*.md")):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            t = open(f, encoding="utf-8").read()
        except Exception:
            continue
        if "소스부재" in t[:1500]:  # 원문성 확정미상 격리분 — 출제 소스 제외(#52-B 채점 정본 아님)
            continue
        m = re.search(r"(?m)^쟁점:\s*(.+)$", t)
        if not m:
            continue
        for link in re.findall(r"\[\[([^\]]+)\]\]", m.group(1)):
            idx.setdefault(link.strip(), []).append(
                {"title": os.path.basename(f)[:-3], "path": os.path.relpath(f, ROOT)})
    return idx


def case_notes_for(cnotes, 논점제목):
    """논점 제목에 백링크된 사례노트(최대 5)."""
    return cnotes.get(논점제목, [])[:5]


# ── 일일 문항 예산·L0 정원 (P0-1, 2026-07-14, #52-C) ─────────────────────────
L0_CARRY = os.path.join(STATE, "l0_carryover.json")


def load_learning_json():
    try:
        return json.load(open(LEARNING, encoding="utf-8-sig"))
    except Exception:
        return {}


def budget_config(learning):
    """수치 정본 = learning.json(운영 설정값). 코드 기본값은 미설정 시 폴백."""
    def _i(key, default):
        try:
            return int(learning.get(key, default))
        except (TypeError, ValueError):
            return default
    return {
        "budget": _i("daily_question_budget", 50),
        "l0_cap": _i("l0_capacity", 4),
        "q_topic": _i("questions_per_topic", 8),
        "q_l0": _i("l0_questions_per_topic", 5),
    }


def apply_l0_capacity(l0_targets, pool, l0_cap, today):
    """L0 정원(≤l0_cap). 초과분은 l0_carryover.json 익일 이월 큐(삭제 아님).
    같은 날 재실행 시 오늘자 이월분은 다시 넣지 않아 선정이 흔들리지 않는다."""
    carry_prev, carry_today = [], []
    if os.path.exists(L0_CARRY):
        try:
            for e in json.load(open(L0_CARRY, encoding="utf-8")).get("이월", []):
                (carry_prev if e.get("날짜", "") < today else carry_today).append(e)
        except Exception:
            pass
    bykey = {t["key"]: t for t in l0_targets}
    merged, dropped = [], []
    for e in carry_prev:  # 전일 이월분을 선두에(먼저 소화)
        k = e.get("key")
        if k in bykey:
            t = bykey.pop(k)
            t["원천"] = (t.get("원천") + "·이월") if t.get("원천") else "이월"
            merged.append(t)
        else:
            c = next((c for c in pool if c["key"] == k), None)
            if c is not None:
                merged.append(dict(c, track="당일", 필수=True, 원천="이월"))
            else:
                dropped.append(k)  # 논점 삭제·개명 등 — 큐에서 제외(고지)
    merged += [t for t in l0_targets if t["key"] in bykey]
    kept, overflow = merged[:l0_cap], merged[l0_cap:]
    new_carry, seen = [], set()
    for e in carry_today + [{"key": t["key"], "원천": t.get("원천", ""), "날짜": today}
                            for t in overflow]:
        if e.get("key") and e["key"] not in seen and e["key"] not in {t["key"] for t in kept}:
            seen.add(e["key"])
            new_carry.append(e)
    if new_carry or os.path.exists(L0_CARRY):
        json.dump({"이월": new_carry}, open(L0_CARRY, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return kept, overflow, dropped


def apply_budget(l0_targets, review_targets, jindo_targets, cfg):
    """일일 총 문항 예산 상한. 초과 시 보존 우선순위
    L0(필수복습) > 복습 약점 > 복습 목표 > 복습 전체롤링 > 진도 순으로 남기고 절사.
    사례형 건수(#52-C 복습 사례 3건)는 별도 축 — 여기서는 선택형 문항만 추정.
    절사 내역 반환 — 브리프·stdout 표기 의무(무단 축소 금지)."""
    tier_rank = {"약점": 0, "목표": 1, "전체롤링": 2}
    plan = ([("L0", t, cfg["q_l0"]) for t in l0_targets]
            + [("복습", t, cfg["q_topic"]) for t in
               sorted(review_targets, key=lambda t: tier_rank.get(t.get("티어"), 1))]
            + [("진도", t, cfg["q_topic"]) for t in jindo_targets])
    used, keep, cut = 0, set(), []
    for track, t, q in plan:
        if used + q <= cfg["budget"]:
            used += q
            keep.add((track, t["key"]))
        else:
            cut.append({"트랙": track, "key": t["key"], "추정문항": q,
                        "티어": t.get("티어", "")})
    return ([t for t in l0_targets if ("L0", t["key"]) in keep],
            [t for t in review_targets if ("복습", t["key"]) in keep],
            [t for t in jindo_targets if ("진도", t["key"]) in keep],
            used, cut)


# ── 브리프 출력 ───────────────────────────────────────────────────────────────
def unit_lines(t):
    """브리프용 논점 줄(소스 포인터 포함)."""
    tag = (" ·약점" if t.get("약점") else "") + (" ·방학목표" if t.get("방학") else "")
    L = [f'- **{t["과목"]} > {t["대분류"]} > {t["소단원"]}**'
         f' (회독{t["회독"]}·선{t["선택"]}·사{t["사례"]}{tag})']
    if t.get("카드파일"):
        scope = t.get("카드범위", "")
        L.append(f'  - 카드[{scope}]: ' + ", ".join(t["카드파일"]) if scope
                 else "  - 카드: " + ", ".join(t["카드파일"]))
    if t.get("원문경로"):
        L.append(f'  - 원문: {t["원문경로"]}')
    if t.get("책"):
        L.append(f'  - 출처: {t["책"]}')
    if t.get("사례노트"):
        L.append("  - 사례노트: " + ", ".join(f'[[{c["title"]}]]' for c in t["사례노트"]))
    return L


# ── 메인 ─────────────────────────────────────────────────────────────────────
def emit_dashboard(l0_targets, jindo_targets, review_targets, today):
    """Meta Bind 진도대시보드 생성 → sync/위키/진도대시보드.md (2026-07-07).
    보드서버와 병존(이중구조): 같은 논점 frontmatter를 Meta Bind INPUT/버튼으로 직접 편집.
    서버가 죽어도 동작(보완책)·폰 Obsidian에서도 동작. 매일 build_session 시 재생성."""
    out = os.path.join(WIKI_ROOT, "진도대시보드.md")
    seen, rows = set(), []
    for sec, targets in [("필수복습(L0)", l0_targets), ("진도", jindo_targets), ("복습", review_targets)]:
        for t in targets:
            if t["key"] in seen:
                continue
            seen.add(t["key"])
            ref = f"sync/위키/{t['과목']}/{t['소단원']}"  # 볼트 상대경로(확장자 제외)
            src = f" — {t.get('원천', '')}" if t.get("원천") else ""
            tier = f"({t['티어']})" if t.get("티어") else ""
            rows.append(f"### [[{t['소단원']}]]  `{t['과목']} > {t['대분류']}` · {sec}{tier}{src}")
            rows.append(f"회독 `INPUT[number:{ref}#회독]` · 선택 `INPUT[number:{ref}#선택]` · "
                        f"사례 `INPUT[number:{ref}#사례]` · 약점 `INPUT[toggle:{ref}#약점]`")
            rows.append("```meta-bind-button")
            rows.append(f'label: "선택 +1 (오늘 체크)"')
            rows.append("style: primary")
            rows.append("actions:")
            rows.append("  - type: updateMetadata")
            rows.append(f"    bindTarget: {ref}#선택")
            rows.append("    evaluate: true")
            rows.append("    value: x + 1")
            rows.append("  - type: updateMetadata")
            rows.append(f"    bindTarget: {ref}#최근체크")
            rows.append("    evaluate: false")
            rows.append(f"    value: {today}")
            rows.append("```")
            rows.append("")
    body = [
        f"# 진도 대시보드 — {today}",
        "",
        "> **이중구조**: 이 대시보드(Meta Bind)와 보드서버(:8770)는 같은 논점 frontmatter를 읽고 쓴다 — 어느 쪽으로 기록해도 동일.",
        "> 서버 미가동·폰에서도 여기서 직접 수정 가능. '선택 +1' 버튼은 `최근체크`를 함께 찍어 다음날 필수복습(L0)에 자동 편입된다.",
        "> 매일 드릴 세션 구성 시 자동 재생성(오늘 논점만 표시). 전체 열람·일괄 편집은 [[진도보드.base|진도보드]] 사용.",
        "",
    ] + rows
    open(out, "w", encoding="utf-8").write("\n".join(body) + "\n")


def main():
    n = int(arg("--n", "6"))  # 일 기본 6 (2026-07-06 사용자 확정, 구 3)
    subj_filter = arg("--subject")

    # 0. L0 당일복습(#52-C): --today "과목/논점,…" → frontmatter 최근수업 기록 (pool 빌드 전)
    _today_str = datetime.now().strftime("%Y-%m-%d")
    today_arg = [x.strip() for x in (arg("--today", "") or "").split(",") if x.strip()]
    if today_arg:
        marked, missed = mark_recent_lesson(today_arg, _today_str)
        if marked:
            print(f"  [L0] 최근수업 기록: {len(marked)}논점 ({_today_str})")
        for m in missed:
            print(f"  [L0 없음] {m}")

    # 1. 정본 pool 구성 (sync/위키 frontmatter)
    pool = build_pool_from_wiki(subj_filter)

    # 2. 방학목표 주입
    banghak = load_banghak()
    for c in pool:
        if c["key"] in banghak:
            c["방학"] = True

    # 3. 드릴 로그 → 최근드릴 주입
    seen = last_drilled()
    for c in pool:
        c["최근드릴"] = seen.get(c["key"], "")

    # 4. 약점 주입
    weakkeys = weak_unit_keys()
    for c in pool:
        if not c["약점"]:
            c["약점"] = c["key"] in weakkeys

    today = datetime.now().strftime("%Y-%m-%d")

    # ── 진도 트랙: 회독 0 + 진행 흔적(방학목표/선택>0/사례>0/최근드릴)
    def jrank(c):
        return (0 if c["방학"] else 1,
                c["최근드릴"] or "0000-00-00",
                c["선택"], c["사례"])
    jindo_cand = [c for c in pool if c["회독"] == 0 and
                  (c["방학"] or c["선택"] or c["사례"] or c["최근드릴"])]
    jindo_cand.sort(key=jrank)
    # 혼동 클러스터 우선(2026-07-06, 변별 대비): 최상위 후보의 과목·대분류와 같은 후보를
    # 우선 채워 세션 논점을 인접 법리로 묶는다(상위 3n 창 안에서만 — 진도 순서 왜곡 방지).
    jindo_targets = []
    if jindo_cand:
        head = jindo_cand[0]
        window = jindo_cand[:max(n * 3, n)]
        same = [c for c in window if c["과목"] == head["과목"] and c["대분류"] == head["대분류"]]
        rest = [c for c in jindo_cand if c not in same]
        jindo_targets = [dict(c, track="진도") for c in (same + rest)[:n]]

    # ── 복습·심화 트랙: 3계층 스코프(2026-07-07) — 약점(최우선, 계층 무관) →
    #    목표 집합('하고 있는 것'=방학·내신 현행 단원, 슬롯 ~2/3: 인접 논점이라 변별 대비
    #    인터리빙 자연 발생 + successive relearning) → 전체 롤링(최소 1슬롯: 유지 리허설,
    #    재학습 절약 — 장기 유지 주 담당은 안키 FSRS). 비율은 운영 설정값.
    def rrank(c):
        return (c["최근드릴"] or "0000-00-00", c["선택"], c["회독"])
    goalset = load_goalset()
    review_cand = [c for c in pool if c["회독"] >= 1 or c["약점"]]
    weak = sorted([c for c in review_cand if c["약점"]], key=rrank)
    goal = sorted([c for c in review_cand if not c["약점"] and c["key"] in goalset], key=rrank)
    rest = sorted([c for c in review_cand if not c["약점"] and c["key"] not in goalset], key=rrank)
    # 계층 정원제(2026-07-07 '양을 늘려 모두 충족'): 약점 ≤4(초과분 SRS 익일 순환) + 목표 3 + 롤링 2
    # = 최대 9논점(후보 없으면 자동 축소, 상호 잠식 없음). "가볍게"(--n 2 등 n<5)면 절반 정원.
    q_weak, q_goal, q_roll = (4, 3, 2) if n >= 5 else (2, 2, 1)
    picks = weak[:q_weak] + goal[:q_goal] + rest[:q_roll]
    if len(picks) < 3:  # 극단 미달 시에만 잔여 후보로 최소 3 보충
        remain = [c for c in weak + goal + rest if c not in picks]
        picks += remain[:3 - len(picks)]
    def _tier(c):
        return "약점" if c["약점"] else ("목표" if c["key"] in goalset else "전체롤링")
    review_targets = [dict(c, track="복습", 티어=_tier(c)) for c in picks]

    # 5. 소스 포인터 부착
    attach_sources(jindo_targets)
    attach_sources(review_targets)

    # ── L0 당일·전일 필수복습 트랙(#52-C, 2026-07-06 확대): 어제·오늘 '본' 논점은 복습 필수.
    #    원천 3종 — 수업 지정(최근수업) · 드릴 출제(최근드릴, drill_log) · 진도보드 체크(최근체크, 서버 스탬프)
    from datetime import timedelta
    _yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _recent = (today, _yday)
    l0_targets = []
    for c in pool:
        srcs = []
        if c.get("최근수업") in _recent: srcs.append("수업")
        if c.get("최근드릴") in _recent: srcs.append("드릴")
        if c.get("최근체크") in _recent: srcs.append("보드체크")
        if srcs:
            l0_targets.append(dict(c, track="당일", 필수=True, 원천="·".join(srcs)))

    # 5b. P0-1(#52-C, 2026-07-14): L0 정원 + 일일 문항 예산 — 수치 정본 learning.json
    cfg = budget_config(load_learning_json())
    l0_targets, l0_overflow, l0_dropped = apply_l0_capacity(
        l0_targets, pool, cfg["l0_cap"], today)
    l0_targets, review_targets, jindo_targets, q_used, q_cut = apply_budget(
        l0_targets, review_targets, jindo_targets, cfg)

    # 6. 복습 × 사례 인덱스 조인 + 사례노트 백링크 조인(#51 사례층 닫힌루프)
    cidx = load_case_index()
    cnotes = load_case_notes()
    attach_sources(l0_targets)
    for t in review_targets + jindo_targets + l0_targets:
        t["사례문제"] = case_for_unit(cidx, t["key"])
        t["사례노트"] = case_notes_for(cnotes, t.get("소단원", ""))

    # 7. 사례 인박스
    inbox = []
    if os.path.isdir(INBOX):
        fs = [f for f in glob.glob(os.path.join(INBOX, "*"))
              if os.path.isfile(f) and not os.path.basename(f).startswith("_")
              and not f.lower().endswith(".md")]
        for f in sorted(fs, key=os.path.getmtime, reverse=True)[:5]:
            inbox.append({"파일": os.path.relpath(f, ROOT),
                          "수정": datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")})

    # 8. SRS
    due = srs_due()

    # 8b. 시험모드(#52-C 가변구도): learning.json exams에서 최근접 시험 D-21 이내면 가동
    exam_mode = None
    try:
        from datetime import timedelta as _td
        ex = json.load(open(LEARNING, encoding="utf-8")).get("exams", [])
        upcoming = []
        for e in ex:
            try:
                d = datetime.strptime(e.get("date", ""), "%Y-%m-%d")
                dd = (d - datetime.now()).days
                if 0 <= dd <= 21:
                    upcoming.append((dd, e))
            except Exception:
                pass
        if upcoming:
            dd, e = sorted(upcoming)[0]
            subjs = e.get("subjects", "all")
            exam_mode = {"name": e.get("name"), "date": e.get("date"), "D": dd,
                         "과목": subjs, "사례억제": dd <= 14}
            # 시험과목 가중: subjects가 목록이면 그 과목 논점을 트랙 선두로(안정 정렬)
            if isinstance(subjs, list):
                jindo_targets.sort(key=lambda t: 0 if t["과목"] in subjs else 1)
                review_targets.sort(key=lambda t: 0 if t["과목"] in subjs else 1)
    except Exception:
        pass

    # 9. JSON 출력
    budget_info = {"상한": cfg["budget"], "추정문항": q_used, "절사": q_cut,
                   "L0정원": cfg["l0_cap"], "L0이월": [t["key"] for t in l0_overflow],
                   "L0이월소실": l0_dropped}   # P0-1 (#52-C)
    out = {"날짜": today, "데이터소스": "sync/위키/{과목}/*.md frontmatter",
           "시험모드": exam_mode,   # #52-C 가변구도 (None=평시)
           "예산": budget_info,     # P0-1 일일 문항 예산·L0 정원 (2026-07-14)
           "당일복습": l0_targets,   # L0 (#52-C)
           "진도단원": jindo_targets, "복습단원": review_targets,
           "대상단원": jindo_targets + review_targets,   # 하위호환
           "복습due": due, "사례대기": inbox,
           "방학단원수": len(banghak), "총논점수": len(pool)}
    os.makedirs(STATE, exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 10. 사람용 브리프
    L = [f"# 오늘의 드릴 — {today}", ""]
    if exam_mode:
        L.append(f"> **시험모드**: {exam_mode['name']} D-{exam_mode['D']} ({exam_mode['date']})"
                 + (" — 시험과목 우선" if isinstance(exam_mode['과목'], list) else "")
                 + (" · **복습 사례형 억제(선택형·찌라시 위주)**" if exam_mode['사례억제'] else ""))
    L += [
         "> 2트랙: **진도**(나가고 있는·회독0 → 선택형 바로) · **복습·심화**(나간·회독≥1 → 사례형+SRS 선택형)",
         f"> 정본: sync/위키 frontmatter · 총 논점 {len(pool)}개",
         f"> **예산(P0-1)**: 일 문항 상한 {cfg['budget']} · 오늘 추정 {q_used}문 · "
         f"L0 정원 {cfg['l0_cap']} (수치는 운영 설정값 — learning.json 정본)", ""]
    if q_cut or l0_overflow or l0_dropped:
        L.append("## 예산 절사·이월 (오늘 뺀 것 — 무단 축소 아님, 반드시 확인)")
        for c in q_cut:
            L.append(f'- [절사·{c["트랙"]}{("·" + c["티어"]) if c.get("티어") else ""}] '
                     f'{c["key"]} (추정 {c["추정문항"]}문) — 예산 초과분')
        for t in l0_overflow:
            L.append(f'- [L0 이월] {t["key"]} → 내일 필수복습 선두 (l0_carryover.json)')
        for k in l0_dropped:
            L.append(f'- [이월 소실] {k} — 논점 파일 미발견(개명·이동 확인 필요)')
        L.append("")
    L.append("## 복습 (SRS due)")
    L.append("```\n" + due + "\n```\n" if due else "- 없음 (또는 srs_log 미설정)\n")

    if l0_targets:
        L.append(f"## 필수복습 (L0 — 어제·오늘 본 논점, 반드시 재출제. "
                 f"선택형 4~5문/논점 · 정원 {cfg['l0_cap']})")
        for t in l0_targets:
            L += unit_lines(t)
            L.append(f'    · 원천: {t.get("원천", "")} (필수)')
        L.append("")

    L.append("## 진도 트랙 — 선택형 바로 (회독0·진행 중)")
    if not jindo_targets:
        L.append("- (진행 중 논점 미식별 — 위키 논점 frontmatter 회독/선택/방학 표시 필요)")
    for t in jindo_targets:
        L += unit_lines(t)

    L.append("\n## 복습·심화 트랙 — 사례형(포섭)+SRS 선택형 (회독≥1)")
    if not review_targets:
        L.append("- (회독≥1 논점 없음 — frontmatter 회독 갱신 확인)")
    for t in review_targets:
        L += unit_lines(t)
        for c in t.get("사례문제", []):
            pts = f'·{c["points"]}점' if c.get("points") else ""
            L.append(f'    · 사례[연결]: {c["title"]}{pts} [{c["id"]}]')
        if not t.get("사례문제"):
            L.append('    · 사례[미연결]: case_problem_answer_index에 이 논점 문제 없음')

    L.append("\n## 사례 대기 (인박스)")
    if inbox:
        for f in inbox:
            L.append(f'- {f["파일"]} ({f["수정"]})')
    else:
        L.append('- 없음. `6.진도관리/사례답안/`에 답안 파일 올리고 "올렸어".')
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")

    # 11. Meta Bind 진도대시보드 (2026-07-07, 서버 병존·보완책 — 서버 없이도 frontmatter 직접 편집)
    emit_dashboard(l0_targets, jindo_targets, review_targets, today)

    print(f"세션 구성: 진도 {len(jindo_targets)}논점 · 복습 {len(review_targets)}논점 · "
          f"사례대기 {len(inbox)}건 · 총논점 {len(pool)}")
    print(f"  예산(P0-1): 상한 {cfg['budget']}문 · 추정 {q_used}문 · L0 정원 {cfg['l0_cap']}"
          f" · 절사 {len(q_cut)}논점 · L0 이월 {len(l0_overflow)}논점")
    for c in q_cut:
        print(f'  [절사·{c["트랙"]}] {c["key"]} ({c["추정문항"]}문)')
    for t in l0_overflow:
        print(f'  [L0 이월→내일] {t["key"]}')
    for k in l0_dropped:
        print(f'  [이월 소실] {k} (논점 파일 미발견)')
    for t in jindo_targets:
        print(f'  [진도] {t["과목"]}>{t["대분류"]}>{t["소단원"]}'
              f' (회독{t["회독"]}{" 방학" if t.get("방학") else ""})')
    for t in review_targets:
        print(f'  [복습] {t["과목"]}>{t["대분류"]}>{t["소단원"]}'
              f' (회독{t["회독"]}{" 방학" if t.get("방학") else ""})')
    print(f"  → {os.path.relpath(OUT_MD, ROOT)} / drill_session.json")


if __name__ == "__main__":
    main()
