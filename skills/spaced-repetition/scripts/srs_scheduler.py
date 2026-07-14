#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spaced Repetition Scheduler (SM-2 Algorithm)
복습 주기 관리 스크립트
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Windows 콘솔 인코딩
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

STATE_DIR = Path(__file__).resolve().parents[3] / "state"
STATE_FILE = STATE_DIR / "srs_log.json"
LEARNING_FILE = STATE_DIR / "learning.json"
EVENTS_FILE = STATE_DIR / "srs_events.jsonl"      # append-only 리뷰 이벤트 로그(2026-07-07 감사)
GRAD_QUEUE = STATE_DIR / "srs_graduated_queue.jsonl"  # 졸업 → 안키 증분덱 핸드오프 대기열


def log_event(kind, item, extra=None):
    """리뷰·등록·졸업 이벤트를 append-only로 기록 — '연속 세션' 판정·재출제 지표의 원천."""
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "kind": kind,
           "id": item.get("id"), "content": item.get("content", "")[:80]}
    if extra:
        rec.update(extra)
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PRIORITY_LEVELS = {
    'low': 0,
    'normal': 1,
    'high': 2,
}

# P0-3(2026-07-14): 오류유형별 초기 due 코드화 — spaced-repetition SKILL
# '답안 채점 연동 간격' 표(D+N)를 --review-type 인자로 반영(수동 가이드 → 실제 로직).
# 등록(--add) 시 초기 next_review = D+N. 이후 간격은 순수 SM-2가 관리.
REVIEW_TYPE_DUE = {
    'issue_spotting': 1,    # 쟁점 자체를 못 찾음 → D+1
    'conclusion_drill': 1,  # 결론 반대 → D+1
    'keyword_recall': 2,    # 키워드 0.5 미만(루브릭 0~1) → D+2
    'mini_application': 2,  # 포섭 0.6 미만(루브릭 0~1) → D+2
    'outline_recall': 3,    # 목차 구조 누락 → D+3 (쟁점 못 찾음 겸용 시 issue_spotting 우선)
    'stable_pass': 7,       # 안정적 통과 → D+7 (이후 정상 SM-2)
}


def _review_history(item_id, limit=50):
    """srs_events.jsonl에서 해당 항목의 리뷰 이력(간단 배열)을 추출.
    P0-2(2026-07-14): 졸업 레코드에 세션 이력을 보존(SM-2→FSRS 핸드오프 근거 자료)."""
    hist = []
    if not EVENTS_FILE.exists():
        return hist
    try:
        with open(EVENTS_FILE, encoding='utf-8') as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get('kind') == 'review' and e.get('id') == item_id:
                    hist.append({'ts': e.get('ts'), 'score': e.get('score'),
                                 'new_session': e.get('new_session')})
    except Exception:
        pass
    return hist[-limit:]


def load_data():
    """SRS 데이터 로드"""
    if not STATE_FILE.exists():
        return {"items": []}
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_data(data):
    """SRS 데이터 저장"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    sync_learning_srs(data)


def load_learning_data():
    """학습 상태 파일 로드"""
    if not LEARNING_FILE.exists():
        return {}
    with open(LEARNING_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def get_exam_date(learning=None):
    """learning.json의 'exam_date'(ISO 'YYYY-MM-DD')를 datetime.date로 반환.
    없거나/빈값/형식오류면 None → 마감 인식 비활성(기존 동작과 완전 동일).
    과거 날짜도 파싱은 하되, 캡핑은 호출부에서 '미래일 때만' 적용한다."""
    if learning is None:
        learning = load_learning_data()
    raw = (learning or {}).get('exam_date')
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def deadline_fraction(days_to_exam):
    """마감까지 남은 일수(보존기간)에 대한 '최적 간격 분수' 보간.

    근거: FSRS optimal-retention — 최적 복습 간격은 보존기간(여기선 마감까지
    남은 일수)의 '분수'이며, 그 분수는 보존기간이 길수록 작아진다.
    보고서 《FSRS최적성_읽기카운트_약점재순환_연구_2026-06-22.md》:
      "최적 간격 = 보존기간의 분수, 분수는 보존기간이 길수록 작아짐
       (약 1주=0.4 → 6개월+=0.1)"
    구현: 1주(7일)에서 frac=0.4, 6개월(180일)에서 frac=0.1 의 두 점을 단순
    선형 보간하고 양 끝에서 클램프. (시험이 가까울수록 간격을 압축하고,
    멀수록 더 자주 끼워 넣지 않도록 분수를 낮춘다.)"""
    near_days, near_frac = 7, 0.4      # 약 1주: 보존기간의 0.4
    far_days, far_frac = 180, 0.1      # 약 6개월+: 보존기간의 0.1
    if days_to_exam <= near_days:
        return near_frac
    if days_to_exam >= far_days:
        return far_frac
    # near_days~far_days 구간 선형 보간
    ratio = (days_to_exam - near_days) / (far_days - near_days)
    return near_frac + (far_frac - near_frac) * ratio


# === 다중 시험 타깃(내신·변시 등) — 고정 단일날짜 대신 그때그때 맞춤 ===
# learning.json["exams"] = [{name, date(null=미정), subjects(list|"all")}, ...]
# 각 SRS 항목은 '자기 과목에 걸린 가장 가까운 미래 시험'으로 압축된다.
# 날짜 미정 타깃은 무시(추후 입력 시 자동 적용). 구버전 단일 'exam_date'도 호환.
SUBJECTS = ["민사소송법", "민사집행법", "형사소송법", "민법", "형법",
            "헌법", "행정법", "상법", "선택법"]  # 긴 이름 먼저(부분일치 오판 방지)
# 개념 어간 → 과목 (topic이 '권리주체_행위능력'처럼 과목명을 안 담을 때 폴백).
# 양과목 모호어(사기·취소·배임 등)는 제외 — 고신뢰 어간만.
_CONCEPT_SUBJECT = {
    "권리주체": "민법", "행위능력": "민법", "제한능력": "민법", "성년후견": "민법",
    "특정후견": "민법", "후견": "민법", "권리남용": "민법", "신의칙": "민법",
    "강행법규": "민법", "의사표시": "민법", "통정허위": "민법", "표현대리": "민법",
    "물권": "민법", "점유": "민법", "소유권": "민법", "저당": "민법", "부당이득": "민법",
    "구성요건": "형법", "위법성": "형법", "책임론": "형법", "공범": "형법", "죄수": "형법",
    "기본권": "헌법", "위헌법률": "헌법", "헌법소원": "헌법", "권한쟁의": "헌법",
    "관할": "민사소송법", "당사자적격": "민사소송법", "기판력": "민사소송법", "소송물": "민사소송법",
}


def _parse_date(raw):
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def load_exams(learning=None):
    """learning.json['exams']를 정규화: [{name, date(date|None), subjects(list|'all')}]."""
    if learning is None:
        learning = load_learning_data()
    learning = learning or {}
    out = []
    for e in (learning.get('exams') or []):
        if not isinstance(e, dict):
            continue
        subs = e.get('subjects', 'all')
        if isinstance(subs, str):
            subs = 'all' if subs.strip().lower() == 'all' else [s.strip() for s in subs.split(',') if s.strip()]
        if not subs:
            subs = 'all'
        out.append({'name': e.get('name', '시험'), 'date': _parse_date(e.get('date')), 'subjects': subs})
    if not out:  # 구버전 단일 exam_date 호환(exams 없을 때만)
        legacy = _parse_date(learning.get('exam_date'))
        if legacy:
            out.append({'name': '시험', 'date': legacy, 'subjects': 'all'})
    return out


def _applies(exam, subject):
    subs = exam.get('subjects', 'all')
    if subs == 'all':
        return True
    return bool(subject) and subject in subs


def effective_deadline(subject, learning=None, today=None):
    """과목에 적용되는(=subjects 'all' 또는 포함) 시험 중 '가장 가까운 미래' 날짜.
    날짜 미정(None) 타깃은 제외. 없으면 None → 캡핑 안 함(순수 SM-2)."""
    if today is None:
        today = datetime.now().date()
    cands = [e['date'] for e in load_exams(learning)
             if e['date'] is not None and e['date'] > today and _applies(e, subject)]
    return min(cands) if cands else None


def item_subject(item):
    """SRS 항목에서 과목 추정(subject 필드 → content/topic 부분일치). 없으면 None."""
    if not isinstance(item, dict):
        return None
    s = item.get('subject')
    if s in SUBJECTS:
        return s
    text = f"{item.get('topic', '')} {item.get('content', '')}"
    for subj in SUBJECTS:  # 긴 이름 먼저
        if subj in text:
            return subj
    for concept, subj in _CONCEPT_SUBJECT.items():  # 개념 어간 폴백
        if concept in text:
            return subj
    return None


def sync_learning_srs(data):
    """learning.json의 SRS 스냅샷과 마지막 세션 날짜를 함께 갱신"""
    learning = load_learning_data()
    if not learning:
        return

    learning.setdefault('srs', {})
    learning['srs']['items'] = data.get('items', [])
    learning['last_session'] = datetime.now().strftime('%Y-%m-%d')

    with open(LEARNING_FILE, 'w', encoding='utf-8') as f:
        json.dump(learning, f, ensure_ascii=False, indent=4)


def normalize_priority(value):
    """우선순위 라벨 정규화"""
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in PRIORITY_LEVELS:
            return lowered
    return 'normal'


def normalize_content(value):
    """중복 비교용 텍스트 정규화"""
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split()).strip().lower()


def priority_from_score(score):
    """오답일수록 높은 복습 우선순위 부여"""
    if score is None:
        return 'normal'
    if score <= 2:
        return 'high'
    if score == 3:
        return 'normal'
    return 'low'


def priority_label(item):
    """항목의 표시용 우선순위"""
    explicit = item.get('priority')
    if explicit:
        return normalize_priority(explicit)
    return priority_from_score(item.get('last_score'))


def retention_factor(subject, learning=None):
    """S4(신경망연구 ⑤): 과목별 desired-retention 차등 — interval 승수 + due 정렬 가중.
    learning.json['retention_factors'] = {과목: 승수, '_default': 1.0}. 낮을수록 자주
    복습(고보존)·오늘 목록에서 우선. 핵심 과목 0.85, 주변 1.0 식. 기본 1.0 = 무변화(미설정 시 순수 SM-2).
    (2026-07-05 수정: 종전엔 load_data()로 srs_log.json을 읽어 기능이 죽어 있었음 — learning.json 정본으로 교정)"""
    if learning is None:
        try:
            learning = load_learning_data()
        except Exception:
            return 1.0
    rf = (learning or {}).get('retention_factors', {}) or {}
    try:
        return float(rf.get(subject, rf.get('_default', 1.0)))
    except (TypeError, ValueError):
        return 1.0


def calculate_next_review(item, score, exam_date=None):
    """SM-2 알고리즘으로 다음 복습일 계산.

    exam_date: 선택 인자(테스트 용이성). None이면 learning.json의 'exam_date'에서
    읽는다(없으면 마감 인식 비활성 → 순수 SM-2와 완전 동일). datetime.date 또는
    'YYYY-MM-DD' 문자열을 받는다.

    마감 인식 캡핑: exam_date가 '미래'면 SM-2 간격을 다음으로 압축한다.
      - days_to_exam = (exam_date - today).days
      - 시험 당일/이후로는 절대 예약하지 않음: interval = min(interval, days_to_exam)
      - 시험이 가까울수록 압축: 최적 간격 = days_to_exam * frac
        (frac은 deadline_fraction() — 보존기간이 길수록 작아짐, ~1주 0.4 → 6개월+ 0.1)
      - interval = min(sm2_interval, max(1, round(days_to_exam*frac)), days_to_exam)
    exam_date가 없거나 과거/오늘이면 캡핑하지 않는다(하위호환).
    """
    ef = item.get('ef', 2.5)
    interval = item.get('interval', 1)
    repetitions = item.get('repetitions', 0)

    if score >= 3:
        # 정답: 간격 증가
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = int(interval * ef)
        repetitions += 1
    else:
        # 오답: 처음부터
        repetitions = 0
        interval = 1

    # EF 조정 (0.8 ~ 2.5 범위)
    ef = max(1.3, ef + (0.1 - (5 - score) * (0.08 + (5 - score) * 0.02)))

    # --- 마감(시험일) 인식 캡핑 (exam_date 미래일 때만, 없으면 기존 동작 그대로) ---
    # exam_date 인자: 명시되면 그대로(테스트/단일 강제). None이면 이 항목의 과목에 걸린
    # '가장 가까운 미래 시험'(다중 타깃, 날짜 미정은 제외)을 자동 적용.
    if exam_date is None:
        exam_date = effective_deadline(item_subject(item))
    elif isinstance(exam_date, str):
        exam_date = _parse_date(exam_date)

    if exam_date is not None:
        days_to_exam = (exam_date - datetime.now().date()).days
        if days_to_exam > 0:  # 시험이 미래일 때만 압축 — 과거/오늘이면 하위호환
            frac = deadline_fraction(days_to_exam)
            compressed = max(1, round(days_to_exam * frac))
            # 시험 당일/이후 예약 금지 + 마감 인식 압축
            interval = min(interval, compressed, days_to_exam)

    # --- S4: 과목별 desired-retention 차등 (기본 1.0 = 무변화, 신경망연구 ⑤) ---
    rf = retention_factor(item_subject(item))
    if rf != 1.0:
        interval = max(1, round(interval * rf))
        if exam_date is not None:  # 마감 캡 재적용(시험일 이후 예약 금지 보존)
            d2e = (exam_date - datetime.now().date()).days
            if d2e > 0:
                interval = min(interval, d2e)

    next_date = (datetime.now() + timedelta(days=interval)).strftime('%Y-%m-%d')

    return {
        'ef': round(ef, 2),
        'interval': interval,
        'repetitions': repetitions,
        'next_review': next_date,
        'last_reviewed': datetime.now().strftime('%Y-%m-%d'),
        'last_score': score,
        'priority': priority_from_score(score),
    }


def get_today_items(data):
    """오늘 복습할 항목 반환. 정렬: 우선순위 → 과목 가중(retention_factor 낮은 과목 먼저,
    2026-07-05 과목별 가중) → 예정일 → 반복수 → 점수 → id."""
    today = datetime.now().strftime('%Y-%m-%d')
    due_items = []
    learning = load_learning_data()  # 루프에서 재로드 방지

    for item in data['items']:
        if item.get('status') == 'graduated':  # 졸업 항목 제외(안키 FSRS 이관)
            continue
        next_review = item.get('next_review', today)
        if next_review <= today:
            due_items.append(item)

    return sorted(
        due_items,
        key=lambda item: (
            -PRIORITY_LEVELS[priority_label(item)],
            retention_factor(item_subject(item), learning),
            item.get('next_review', today),
            item.get('repetitions', 0),
            item.get('last_score', 5),
            item.get('id', 0),
        ),
    )


def add_item(data, content, topic, priority, source='manual', review_type=None):
    """새 항목 추가. 중복(정규화 내용 일치) 시 신규 발급 대신 기존 항목 반환+우선순위 상향
    (2026-07-07 감사: --add 무중복검사로 인한 항목 증식 차단 — sync_weak_points와 기준 통일).
    review_type(P0-3): REVIEW_TYPE_DUE 키면 초기 next_review를 D+N으로 설정(이후 순수 SM-2).
    중복 항목에 review_type이 오면 더 이른 due로만 당긴다(뒤로 미루지 않음 — 재오답 반영)."""
    normalized = normalize_content(content)
    due_days = REVIEW_TYPE_DUE.get(review_type) if review_type else None
    for it in data['items']:
        if normalize_content(it.get('content')) == normalized:
            if PRIORITY_LEVELS[priority_label(it)] < PRIORITY_LEVELS[normalize_priority(priority)]:
                it['priority'] = normalize_priority(priority)
            if due_days is not None:
                pulled = (datetime.now() + timedelta(days=due_days)).strftime('%Y-%m-%d')
                if pulled < it.get('next_review', pulled):
                    it['next_review'] = pulled
                it['review_type'] = review_type
            log_event('add_dup', it, {'review_type': review_type} if review_type else None)
            return it
    new_id = max([i.get('id', 0) for i in data['items']], default=0) + 1
    today = datetime.now().strftime('%Y-%m-%d')

    new_item = {
        'id': new_id,
        'content': content,
        'topic': topic,
        'ef': 2.5,
        'interval': 1,
        'repetitions': 0,
        'next_review': today,
        'created': today,
        'priority': normalize_priority(priority),
        'source': source,
    }
    if due_days is not None:  # P0-3: 오류유형별 초기 due(D+N)
        new_item['interval'] = due_days
        new_item['next_review'] = (datetime.now() + timedelta(days=due_days)).strftime('%Y-%m-%d')
        new_item['review_type'] = review_type
    subj = item_subject({'topic': topic, 'content': content})  # 마감인식 다중타깃용 과목 저장
    if subj:
        new_item['subject'] = subj

    data['items'].append(new_item)
    return new_item


def sync_weak_points(data):
    """learning.json의 weak_points를 SRS에 동기화"""
    learning = load_learning_data()
    weak_points = learning.get('weak_points', [])
    topic = learning.get('current_scope', '일반')
    existing_items = {
        normalize_content(item.get('content')): item
        for item in data.get('items', [])
        if item.get('content')
    }

    added_items = []
    promoted_items = []

    for weak_point in weak_points:
        normalized = normalize_content(weak_point)
        if not normalized:
            continue

        existing = existing_items.get(normalized)
        if existing is None:
            item = add_item(data, weak_point, topic, 'high', source='weak_points')
            added_items.append(item)
            existing_items[normalized] = item
            continue

        current_priority = priority_label(existing)
        if PRIORITY_LEVELS[current_priority] < PRIORITY_LEVELS['high']:
            existing['priority'] = 'high'
            promoted_items.append(existing)

        existing.setdefault('source', 'weak_points')

    return added_items, promoted_items


def set_exam_date(date_str):
    """learning.json의 'exam_date'를 기록한다(다른 키 전부 보존).
    utf-8-sig로 읽고 utf-8 indent=4로 쓴다. 'YYYY-MM-DD' 형식만 허용.
    반환: (성공여부, 정규화된 날짜문자열 또는 오류메시지)"""
    try:
        parsed = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False, f"날짜 형식 오류(YYYY-MM-DD 필요): {date_str}"

    normalized = parsed.strftime('%Y-%m-%d')

    # 기존 내용 전부 보존하고 exam_date만 갱신
    if LEARNING_FILE.exists():
        with open(LEARNING_FILE, 'r', encoding='utf-8-sig') as f:
            learning = json.load(f)
    else:
        learning = {}

    learning['exam_date'] = normalized

    with open(LEARNING_FILE, 'w', encoding='utf-8') as f:
        json.dump(learning, f, ensure_ascii=False, indent=4)

    return True, normalized


def _write_learning(learning):
    with open(LEARNING_FILE, 'w', encoding='utf-8') as f:
        json.dump(learning, f, ensure_ascii=False, indent=4)


def add_or_update_exam(name, date_str=None, subjects=None):
    """시험 타깃 추가/수정. date_str=None이면 날짜 미정(추후 입력).
    subjects=None이면 기존 유지(신규는 'all'). 다른 키 전부 보존."""
    if LEARNING_FILE.exists():
        with open(LEARNING_FILE, 'r', encoding='utf-8-sig') as f:
            learning = json.load(f)
    else:
        learning = {}
    date_norm = None
    if date_str:
        d = _parse_date(date_str)
        if d is None:
            return False, f"날짜 형식 오류(YYYY-MM-DD): {date_str}"
        date_norm = d.strftime('%Y-%m-%d')
    subs = None
    if subjects is not None:
        subs = 'all' if subjects.strip().lower() == 'all' else [s.strip() for s in subjects.split(',') if s.strip()]
    exams = learning.get('exams')
    if not isinstance(exams, list):
        exams = []
    found = next((e for e in exams if isinstance(e, dict) and e.get('name') == name), None)
    if found is None:
        found = {'name': name, 'date': date_norm, 'subjects': subs if subs is not None else 'all'}
        exams.append(found)
    else:
        if date_str:
            found['date'] = date_norm
        if subs is not None:
            found['subjects'] = subs
    learning['exams'] = exams
    _write_learning(learning)
    return True, found


def list_exams_str():
    today = datetime.now().date()
    exams = load_exams()
    if not exams:
        return "  등록된 시험 없음 — --add-exam 으로 추가(날짜 생략 시 미정)."
    lines = []
    for e in exams:
        if e['date'] is None:
            dd = "날짜미정"
        else:
            dd = f"{e['date'].strftime('%Y-%m-%d')} (D-day {(e['date'] - today).days}일)"
        subs = '전과목' if e['subjects'] == 'all' else ', '.join(e['subjects'])
        lines.append(f"  · {e['name']}: {dd} — {subs}")
    return "\n".join(lines)


def review_item(data, item_id, score):
    """항목 복습 결과 기록 + 세션 dedup·졸업 판정(2026-07-07, 채점복습 #20 코드화).
    - '같은 날 반복=1세션': 같은 날 두 번째 이후 리뷰는 간격 재계산만, 세션 카운트 불변.
    - 간격 둔 세션 3회 연속 성공(score>=3) → status='graduated' + 핸드오프 큐 기록.
      졸업 항목은 오늘 목록에서 제외(장기 유지는 안키 FSRS 담당)."""
    today = datetime.now().strftime('%Y-%m-%d')
    for item in data['items']:
        if item.get('id') == item_id:
            new_session = item.get('last_session_date') != today
            updates = calculate_next_review(item, score)
            item.update(updates)
            if new_session:
                item['last_session_date'] = today
                if score >= 3:
                    item['sessions_ok'] = item.get('sessions_ok', 0) + 1
                else:
                    item['sessions_ok'] = 0
            log_event('review', item, {'score': score, 'new_session': new_session,
                                       'sessions_ok': item.get('sessions_ok', 0)})
            if item.get('sessions_ok', 0) >= 3 and item.get('status') != 'graduated':
                item['status'] = 'graduated'
                item['graduated'] = today
                # P0-2(2026-07-14): SM-2→FSRS 졸업 핸드오프 이력 보존 —
                # 최종 interval·ef·repetitions + 세션 이력(srs_events.jsonl 리뷰 추출)
                with open(GRAD_QUEUE, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "졸업일": today, "content": item.get('content'),
                        "topic": item.get('topic'), "subject": item.get('subject'),
                        "id": item.get('id'),
                        "final_interval": item.get('interval'),
                        "final_ef": item.get('ef'),
                        "repetitions": item.get('repetitions'),
                        "sessions_ok": item.get('sessions_ok'),
                        "history": _review_history(item.get('id')),
                    }, ensure_ascii=False) + "\n")
                log_event('graduated', item)
            return item
    return None


def main():
    parser = argparse.ArgumentParser(description="Spaced Repetition Scheduler")
    parser.add_argument('--today', action='store_true', help='오늘 복습할 항목')
    parser.add_argument('--add', type=str, help='새 항목 추가')
    parser.add_argument('--topic', type=str, default='일반', help='주제')
    parser.add_argument('--priority', choices=['high', 'normal', 'low'], default='normal', help='복습 우선순위')
    parser.add_argument('--review-type', choices=sorted(REVIEW_TYPE_DUE),
                        help='오류유형별 초기 due(P0-3, SKILL 표 코드화) — --add와 함께 사용')
    parser.add_argument('--sync-weak-points', action='store_true', help='learning.json의 약점을 SRS에 동기화')
    parser.add_argument('--review', type=int, help='복습할 항목 ID')
    parser.add_argument('--score', type=int, choices=[0,1,2,3,4,5], help='복습 점수 (0-5)')
    parser.add_argument('--status', action='store_true', help='전체 상태')
    parser.add_argument('--set-exam', type=str, metavar='YYYY-MM-DD',
                        help='(레거시) 단일 시험일 — 다중 타깃 "시험"(전과목)으로 저장')
    parser.add_argument('--add-exam', type=str, metavar='NAME',
                        help='시험 타깃 추가/수정(이름). --date·--subjects 동반')
    parser.add_argument('--date', type=str, metavar='YYYY-MM-DD',
                        help='--add-exam 의 시험일(생략=날짜 미정, 추후 입력)')
    parser.add_argument('--subjects', type=str,
                        help="--add-exam 의 과목(쉼표 구분) 또는 'all'(전과목)")
    parser.add_argument('--list-exams', action='store_true', help='등록 시험 타깃 목록')

    args = parser.parse_args()
    data = load_data()
    
    if args.today:
        items = get_today_items(data)
        print(f"=== 오늘 복습할 항목: {len(items)}개 ===\n")
        for item in items:
            print(f"[{item['id']}] {item['content']} ({item['topic']}) [{priority_label(item)}]")
            print(f"    EF: {item.get('ef', 2.5)}, 간격: {item.get('interval', 1)}일")
        if not items:
            print("오늘 복습할 항목이 없습니다.")
    
    elif args.add:
        item = add_item(data, args.add, args.topic, args.priority,
                        review_type=args.review_type)
        save_data(data)
        rt = f" · {item['review_type']} → due {item['next_review']}" if item.get('review_type') else ""
        print(f"항목 추가됨: [{item['id']}] {item['content']} [{item['priority']}]{rt}")

    elif args.sync_weak_points:
        added_items, promoted_items = sync_weak_points(data)
        save_data(data)
        print(f"약점 동기화 완료: 추가 {len(added_items)}개, 우선순위 상향 {len(promoted_items)}개")
        for item in added_items:
            print(f"  + [{item['id']}] {item['content']} [{item['priority']}]")
        for item in promoted_items:
            print(f"  ^ [{item['id']}] {item['content']} [{item['priority']}]")
    
    elif args.review is not None and args.score is not None:
        item = review_item(data, args.review, args.score)
        if item:
            save_data(data)
            print(f"복습 기록됨: [{item['id']}] {item['content']}")
            print(f"  다음 복습: {item['next_review']} ({item['interval']}일 후)")
        else:
            print(f"항목을 찾을 수 없습니다: {args.review}")
    
    elif args.add_exam:
        ok, res = add_or_update_exam(args.add_exam, args.date, args.subjects)
        if ok:
            subs = '전과목' if res['subjects'] == 'all' else ', '.join(res['subjects'])
            print(f"시험 타깃 저장: {res['name']} · 날짜 {res['date'] or '미정(추후 입력)'} · 과목 {subs}")
            print("--- 현재 타깃 ---")
            print(list_exams_str())
        else:
            print(res)

    elif args.list_exams:
        print("=== 등록 시험 타깃 ===")
        print(list_exams_str())

    elif args.set_exam:  # 레거시: 단일 → 다중 타깃 "시험"(전과목)으로 저장
        ok, res = add_or_update_exam('시험', args.set_exam, 'all')
        if ok:
            d_day = (_parse_date(res['date']) - datetime.now().date()).days
            print(f"시험일 기록됨(타깃 '시험'·전과목): {res['date']} (D-day: {d_day}일)")
        else:
            print(res)

    elif args.status:
        print(f"=== SRS 상태 ===")
        exams = load_exams()
        if exams:
            print("시험 타깃:")
            print(list_exams_str())
        print(f"총 항목: {len(data['items'])}개")
        today_count = len(get_today_items(data))
        print(f"오늘 복습: {today_count}개")
        
        # 주제별 통계
        topics = {}
        for item in data['items']:
            t = item.get('topic', '일반')
            topics[t] = topics.get(t, 0) + 1
        print(f"\n주제별:")
        for t, c in topics.items():
            print(f"  {t}: {c}개")

        priorities = {'high': 0, 'normal': 0, 'low': 0}
        for item in data['items']:
            priorities[priority_label(item)] += 1
        print(f"\n우선순위별:")
        for label in ['high', 'normal', 'low']:
            print(f"  {label}: {priorities[label]}개")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
