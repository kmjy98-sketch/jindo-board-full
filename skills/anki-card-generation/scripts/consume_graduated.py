# -*- coding: utf-8 -*-
"""SRS 졸업 큐 소비 → 안키 증분덱 카드 후보 초안 (P0-2, 2026-07-14).

srs_graduated_queue.jsonl(SM-2 졸업 — 간격 둔 3세션 연속 성공, #20)을 읽어
각 미소비 항목을 outputs/02_cards_v37/약점포섭_{과목}_v37.md 에
카드 후보 초안(제목 + 출처 + 제안 initial due = 졸업 interval)으로 append 한다.

- 카드 '본문' 생성은 LLM 몫(#1 소스근거) — 여기서는 스텁 섹션만 남긴다.
- 소비된 항목은 큐에서 `consumed: true` 마킹(삭제 금지 — 이력 보존).
- 증분 덱 '약점' 파일은 정본 카드파일과 분리(#51(E) 정본 스냅샷 원칙,
  daily-drill SKILL §2-A-후속과 같은 파일 규약).

사용:
  python .agent/skills/anki-card-generation/scripts/consume_graduated.py [--dry-run]
"""
import json
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_p = os.path.abspath(__file__)
while os.path.basename(_p) != '.agent' and os.path.dirname(_p) != _p:
    _p = os.path.dirname(_p)
sys.path.insert(0, os.path.join(_p, 'scripts'))
from _vault import VAULT_ROOT  # noqa: E402

ROOT = VAULT_ROOT
QUEUE = os.path.join(ROOT, ".agent", "state", "srs_graduated_queue.jsonl")
CARDS_DIR = os.path.join(ROOT, "outputs", "02_cards_v37")

# 과목 풀네임(#50-B·#51 약칭 금지). subject 값이 이 목록 밖이면 '미분류' 파일로.
SUBJECTS = ["민법", "민사소송법", "민사집행법", "형법총론", "형법각론", "형법",
            "형사소송법", "헌법", "행정법", "상법", "선택법"]


def _target_file(subject):
    subj = subject if subject in SUBJECTS else "미분류"
    return os.path.join(CARDS_DIR, f"약점포섭_{subj}_v37.md"), subj


def _header(subj):
    return (f"# 약점포섭_{subj}_v37 — SRS 졸업 핸드오프 카드 후보\n\n"
            "> SM-2 졸업 항목(간격 둔 3세션 연속 성공, #20)의 안키 증분덱 후보 초안.\n"
            "> 카드 본문은 LLM이 위키·원문 소스에서만 생성한다(#1). 정본 카드파일과\n"
            "> 분리된 증분 덱 '약점'으로 빌드한다(#51(E) — 기존 카드파일 수정 금지).\n")


def _draft(rec, today):
    interval = rec.get("final_interval")
    due = f"{interval}일 (졸업 시점 SM-2 interval — 안키 초기 간격 제안)" \
        if interval is not None else "(구 레코드 — interval 미기록, 안키 기본값 사용)"
    lines = [
        f"## 졸업 핸드오프 후보 — {rec.get('content', '(내용 없음)')}",
        f"- 등록일: {today} · 졸업일: {rec.get('졸업일', '?')} · SRS id: {rec.get('id', '?')}",
        "- 출처: .agent/state/srs_graduated_queue.jsonl (SM-2→FSRS 핸드오프, #20)",
        f"- topic: {rec.get('topic', '')}",
        f"- 제안 initial due: {due}",
    ]
    if rec.get("final_ef") is not None:
        lines.append(f"- 최종 ef: {rec.get('final_ef')} · repetitions: "
                     f"{rec.get('repetitions')} · sessions_ok: {rec.get('sessions_ok')}")
    if rec.get("history"):
        hist = ", ".join(f"{h.get('ts', '?')}={h.get('score', '?')}"
                         for h in rec["history"][-5:])
        lines.append(f"- 세션 이력(최근 5): {hist}")
    lines.append("<!-- TODO: 카드 본문 생성 대기 — 소스(sync/위키·outputs/01_ocr_llamaparse)"
                 "에서만 생성(#1), 형식은 anki-card-generation SKILL §3 -->")
    return "\n".join(lines) + "\n\n"


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(QUEUE):
        print(f"큐 없음(졸업 항목 없음): {os.path.relpath(QUEUE, ROOT)}")
        return
    raw_lines = open(QUEUE, encoding="utf-8").read().splitlines()
    today = datetime.now().strftime("%Y-%m-%d")
    out_lines, appended, skipped = [], [], 0
    pending_writes = {}  # 파일경로 → append할 초안 텍스트 목록

    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except Exception:
            out_lines.append(ln)  # 파싱 불가 행은 원문 보존
            continue
        if rec.get("consumed"):
            out_lines.append(ln)
            skipped += 1
            continue
        target, subj = _target_file(rec.get("subject"))
        # 중복 방지: 같은 제목의 후보 섹션이 이미 있으면 초안 생략(소비 마킹은 수행)
        heading = f"## 졸업 핸드오프 후보 — {rec.get('content', '(내용 없음)')}"
        existing = ""
        if os.path.exists(target):
            try:
                existing = open(target, encoding="utf-8").read()
            except Exception:
                existing = ""
        dup = heading in existing or any(
            heading in t for t in pending_writes.get(target, []))
        if not dup:
            pending_writes.setdefault(target, []).append(_draft(rec, today))
        appended.append((rec.get("content", ""), subj, "중복생략" if dup else "초안"))
        rec["consumed"] = True
        rec["consumed_date"] = today
        out_lines.append(json.dumps(rec, ensure_ascii=False))

    if dry:
        print(f"[dry-run] 소비 대상 {len(appended)}건 · 기소비 {skipped}건")
        for c, subj, kind in appended:
            print(f"  [{kind}] {c} → 약점포섭_{subj}_v37.md")
        return

    os.makedirs(CARDS_DIR, exist_ok=True)
    for target, drafts in pending_writes.items():
        is_new = not os.path.exists(target)
        with open(target, "a", encoding="utf-8") as f:
            if is_new:
                subj = os.path.basename(target).split("_")[1]
                f.write(_header(subj) + "\n")
            f.writelines(drafts)
    if appended:  # 소비 마킹 재기록(삭제 금지 — consumed: true 마킹만)
        open(QUEUE, "w", encoding="utf-8").write("\n".join(out_lines) + "\n")
    print(f"소비 {len(appended)}건 (초안 {sum(len(v) for v in pending_writes.values())}건"
          f"·중복생략 {len(appended) - sum(len(v) for v in pending_writes.values())}건)"
          f" · 기소비 {skipped}건")
    for c, subj, kind in appended:
        print(f"  [{kind}] {c} → outputs/02_cards_v37/약점포섭_{subj}_v37.md")


if __name__ == "__main__":
    main()
