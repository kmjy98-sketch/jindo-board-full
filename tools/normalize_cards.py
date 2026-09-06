# -*- coding: utf-8 -*-
"""카드 파일 정규화 — 빌드 게이트(anki-card-generation SKILL §9) 충족용 기계적 정리.

내용(법리·조문·판례 텍스트)은 바꾸지 않는다. 바꾸는 것은 형식뿐이다.

  1. cloze 번호 부여     : `{{답}}` → `{{cN::답}}` (카드 블록 단위로 순번, 기존 번호 다음부터)
  2. 한자 → 한글 (#37)   : 당사자 천간 10자(甲乙丙丁戊己庚辛壬癸 → 갑을병정무기경신임계),
                           판례 표기 (全合)/(全) → (전합)/(전). 그 외 한자(주석용 子·父·死者 등)는 보존.
  3. 구포맷 구분자       : `### ` 카드가 하나도 없는 파일의 `## [속성] 제목` → `### [속성] 제목`
  4. 비표준 필드 라벨    : `**앞:**`/`**뒤:**`/`**빈칸:**`/`**태그:**` → 볼드 제거, `앞/뒤:` → `앞:`
  5. frontmatter 과목    : 민사→민법, 공법→헌법, "헌법 — 통치구조…"→헌법 (#50-B 풀네임)

사용:
  python tools/normalize_cards.py --dry-run     # 파일별 변경 건수만
  python tools/normalize_cards.py               # 적용
  python tools/normalize_cards.py --cards outputs/02_cards_v37   # 볼트 경로 지정
"""
import argparse
import collections
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

HANJA_MAP = str.maketrans("甲乙丙丁戊己庚辛壬癸", "갑을병정무기경신임계")
CLOZE_NUM = re.compile(r"\{\{c(\d+)::")
CLOZE_UNNUM = re.compile(r"\{\{(?!c\d+::)([^{}\n]+?)\}\}")
BLOCK_START = re.compile(r"^(#{2,3} |---\s*$|카드 [A-Z]\d*:|앞:|앞/뒤:|\*\*앞:\*\*)")
SUBJ_NORM = {"민사": "민법", "공법": "헌법"}


def split_frontmatter(text):
    m = re.match(r"^(---\n.*?\n---\n)", text, re.S)
    return (m.group(1), text[m.end():]) if m else ("", text)


def fix_frontmatter(fm, stats):
    if not fm:
        return fm

    def repl(m):
        v = m.group(2).strip()
        nv = SUBJ_NORM.get(v, v)
        if v.startswith("헌법"):
            nv = "헌법"
        if nv != v:
            stats["과목정규화"] += 1
        return f"{m.group(1)}{nv}"

    return re.sub(r"(?m)^(과목:\s*)(.+)$", repl, fm)


def number_clozes(body, stats):
    out = []
    max_n = 0
    for line in body.split("\n"):
        if BLOCK_START.match(line):
            max_n = 0
        nums = [int(x) for x in CLOZE_NUM.findall(line)]
        if nums:
            max_n = max(max_n, max(nums))

        def repl(m):
            nonlocal max_n
            max_n += 1
            stats["cloze번호부여"] += 1
            return "{{c%d::%s}}" % (max_n, m.group(1))

        out.append(CLOZE_UNNUM.sub(repl, line))
    return "\n".join(out)


def convert_hanja(body, stats):
    before = body
    body = body.translate(HANJA_MAP)
    body = re.sub(r"\(全合\)|\(全합\)|全合", lambda m: "(전합)" if m.group(0).startswith("(") else "전합", body)
    body = body.replace("(全)", "(전)")
    stats["한자→한글(문자)"] += sum(1 for a, b in zip(before, body) if a != b) if len(before) == len(body) \
        else int(before != body)
    return body


def fix_headings(body, stats):
    if re.search(r"^### ", body, re.M):
        return body  # 신포맷 파일: `##`는 섹션 헤더이므로 보존
    new, n = re.subn(r"(?m)^## \[", "### [", body)
    stats["##→###"] += n
    return new


def fix_labels(body, stats):
    new, n = re.subn(r"(?m)^\*\*(앞|뒤|빈칸|태그|출처):\*\*\s?", r"\1: ", body)
    stats["볼드라벨"] += n
    new, n2 = re.subn(r"(?m)^앞/뒤:", "앞:", new)
    stats["앞/뒤→앞"] += n2
    return new


def normalize(text):
    stats = collections.Counter()
    fm, body = split_frontmatter(text)
    fm = fix_frontmatter(fm, stats)
    body = fix_headings(body, stats)
    body = fix_labels(body, stats)
    body = convert_hanja(body, stats)
    body = number_clozes(body, stats)
    return fm + body, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--cards", default="cards")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = os.path.join(a.root, a.cards)
    total = collections.Counter()
    changed = 0
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md"):
            continue
        p = os.path.join(d, f)
        text = open(p, encoding="utf-8").read()
        new, stats = normalize(text)
        if new != text:
            changed += 1
            total.update(stats)
            if a.dry_run:
                print(f"{f}: " + ", ".join(f"{k} {v}" for k, v in stats.items() if v))
            else:
                open(p, "w", encoding="utf-8", newline="").write(new)
    print(f"\n{'[dry-run] ' if a.dry_run else ''}변경 파일 {changed}개 · " +
          ", ".join(f"{k} {v}" for k, v in total.items()))


if __name__ == "__main__":
    main()
