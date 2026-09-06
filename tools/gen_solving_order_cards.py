# -*- coding: utf-8 -*-
"""사례노트 `## 풀이순서` → 역할② 풀이순서 카드 보충 (anki-card-generation SKILL §4.2).

규칙: 1사례 노트 = 1풀이순서 카드, 섹션 원문 그대로(사실관계·포섭격자·모범답안 불포함).
이미 카드가 있는 노트는 건너뛴다(제목 2-gram 유사도 ≥ 0.40, 헌법은 3자리 사례번호 일치).
새 카드는 과목 파일 `사례풀이순서_{과목}_v37.md` 끝의 "자동 보충" 절에 append 한다.

사용:
  python tools/gen_solving_order_cards.py --dry-run
  python tools/gen_solving_order_cards.py
  python tools/gen_solving_order_cards.py --wiki sync/위키 --cards outputs/02_cards_v37   # 볼트
"""
import argparse
import collections
import datetime
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

SUBJECT_FILES = ["민법", "민사소송법", "헌법", "형법각론", "형법총론"]
THRESHOLD = 0.40


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    d, links = {}, []
    if m:
        cur = None
        for line in m.group(1).splitlines():
            if re.match(r"^\S", line) and ":" in line:
                k, v = line.split(":", 1)
                cur = k.strip()
                d[cur] = v.strip().strip('"')
            elif cur == "쟁점":
                links += re.findall(r"\[\[([^\]|]+)", line)
    return d, links


def norm(x):
    return re.sub(r"[\s_·\-—(),.\[\]「」『』〔〕“”\"'’‘:：;/①②③④⑤⑥⑦⑧⑨⑩+]", "", x)


def grams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)}


def card_titles(path):
    if not os.path.exists(path):
        return []
    t = open(path, encoding="utf-8").read()
    ts = re.findall(r"^### \[풀이순서\]\s*(.+)$", t, re.M)
    return [re.sub(r"\s*\([^)]*p\.?\d[^)]*\)\s*$", "", x) for x in ts]


def matched(stem, titles, subj):
    ns = norm(stem)
    if subj == "헌법":
        mnum = re.match(r"(\d{3})", stem)
        if mnum and any(re.search(r"(?<!\d)%s(?!\d)" % mnum.group(1), t) for t in titles):
            return True
    g = grams(ns)
    for ct in titles:
        nc = norm(ct)
        if ns in nc or nc in ns:
            return True
        gc = grams(nc)
        if len(g & gc) / max(1, len(g | gc)) >= THRESHOLD:
            return True
    return False


def extract_section(text):
    m = re.search(r"^##+\s*풀이순서[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip("\n") if m else ""


def build_card(stem, fmd, links, section):
    src = fmd.get("출처") or fmd.get("사례집") or ""
    page = fmd.get("페이지") or ""
    src_part = f" ({src}{' p' + page if page else ''})" if src or page else ""
    topic = "·".join(l.replace(" ", "") for l in links) if links else stem.replace(" ", "")
    return (f"### [풀이순서] {stem}{src_part}\n\n"
            f"**단계::포섭 주제::{topic}**\n\n"
            f"{section}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--wiki", default="wiki")
    ap.add_argument("--cards", default="cards")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    case_root = os.path.join(a.root, a.wiki, "사례")
    cards_dir = os.path.join(a.root, a.cards)
    today = datetime.date.today().isoformat()

    titles = {s: card_titles(os.path.join(cards_dir, f"사례풀이순서_{s}_v37.md")) for s in SUBJECT_FILES}
    new_cards = collections.defaultdict(list)
    skipped = collections.Counter()
    for d in sorted(os.listdir(case_root)):
        if d not in SUBJECT_FILES:
            continue
        for f in sorted(os.listdir(os.path.join(case_root, d))):
            if not f.endswith(".md"):
                continue
            text = open(os.path.join(case_root, d, f), encoding="utf-8").read()
            fmd, links = frontmatter(text)
            if fmd.get("type") != "사례":
                continue
            stem = f[:-3]
            section = extract_section(text)
            if not section:
                skipped[f"{d}:풀이순서 섹션 없음"] += 1
                continue
            if matched(stem, titles[d], d):
                skipped[f"{d}:기존 카드 있음"] += 1
                continue
            new_cards[d].append(build_card(stem, fmd, links, section))
            titles[d].append(stem)  # 같은 실행 내 중복 방지

    for s in SUBJECT_FILES:
        n = len(new_cards[s])
        print(f"{s}: 신규 {n}장 · " + ", ".join(f"{k.split(':')[1]} {v}" for k, v in skipped.items() if k.startswith(s + ":")))
        if not n or a.dry_run:
            continue
        path = os.path.join(cards_dir, f"사례풀이순서_{s}_v37.md")
        header = (f"\n\n---\n\n## 자동 보충 {today} — 사례노트 `## 풀이순서` 전재 "
                  f"(tools/gen_solving_order_cards.py, {n}장)\n\n"
                  "<!-- 1사례노트=1카드(SKILL §4.2). 본문은 사례노트 풀이순서 섹션 원문. "
                  "cloze 미처리(기존 민법·민사소송법 카드 다수와 동일 형식) -->\n\n")
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(header + "\n---\n\n".join(new_cards[s]))
    total = sum(len(v) for v in new_cards.values())
    print(f"\n{'[dry-run] ' if a.dry_run else ''}합계 신규 {total}장")


if __name__ == "__main__":
    main()
