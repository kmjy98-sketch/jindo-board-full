# -*- coding: utf-8 -*-
"""카드 현황 인벤토리 — cards/·wiki/·state/ 스냅샷을 스캔해 마크다운 표로 출력.

핸드오프 문서(docs/카드현황_핸드오프_*.md)의 수치 원천. 표준 라이브러리만 사용.

사용:
  python tools/card_inventory.py            # 저장소 루트 기준
  python tools/card_inventory.py --root E:\\법학볼트 --cards outputs/02_cards_v37 --wiki sync/위키 --state .agent/state

카드 단위 추정 규칙(v3.7 구분자 기준):
  - `### ` 헤딩 수 = 카드 수 (v3.7 output_format_lock: `### [속성] 소제목`)
  - `### `가 없고 `## `만 있는 구포맷 파일은 `## ` 헤딩 수로 대체
  - `low yield` 스텁(카드화 대상 본문 없음)은 0
"""
import argparse
import collections
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

HANJA = re.compile(r"[一-鿿]")
PAGED = re.compile(r"^(.*?)_(?:llamaparse_)?p(\d+)-p?(\d+)")
# 위키 논점 `원문:` → 카드 glob 매칭 규칙(build_session._원문_to_card_paths)과 동일한 키
CLOZE_NUM = re.compile(r"\{\{c\d+::")
CLOZE_ANY = re.compile(r"\{\{(?!c\d+::)[^{}]+\}\}")  # 번호 없는 cloze
STD_SUBJECTS = ["민법", "민사소송법", "민사집행법", "형법총론", "형법각론", "형법",
                "형사소송법", "헌법", "행정법", "상법", "선택법", "법조윤리"]


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    d = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip().strip('"')
    return d


def book_of(fname):
    m = PAGED.match(fname)
    if m:
        return m.group(1)
    base = re.sub(r"_(기본서_)?v37\.md$", "", fname)
    base = re.sub(r"\.md$", "", base)
    return re.sub(r"_\d+$", "", base)


def scan_cards(cards_dir):
    rows = []
    for f in sorted(os.listdir(cards_dir)):
        if not f.endswith(".md"):
            continue
        t = read(os.path.join(cards_dir, f))
        fm = frontmatter(t)
        h3 = len(re.findall(r"^### ", t, re.M))
        h2 = len(re.findall(r"^## ", t, re.M))
        stub = bool(re.search(r"low yield|카드화 대상 본문 없음", t))
        ledger = "감사 대장" in t and h3 == 0
        est = 0 if stub or ledger else (h3 if h3 else h2)
        fmt = ("스텁(low yield)" if stub else
               "감사대장(신규0)" if ledger else
               "### + 앞/뒤" if h3 and re.search(r"^앞:", t, re.M) else
               "### (빈칸/기타)" if h3 else
               "## + 앞/뒤(구포맷)" if h2 and re.search(r"^앞:", t, re.M) else
               "## + **앞:**/앞/뒤:(비표준 라벨)" if h2 else "기타")
        m = PAGED.match(f)
        rows.append(dict(
            file=f, book=book_of(f), fm=fm, est=est, fmt=fmt,
            pages=(int(m.group(2)), int(m.group(3))) if m else None,
            has_fm=bool(fm), subj=fm.get("과목", ""),
            cloze_num=len(CLOZE_NUM.findall(t)),
            cloze_nonum=len(CLOZE_ANY.findall(t)),
            hanja=len(HANJA.findall(t)),
            stage=len(re.findall(r"단계::", t)),
            burden=len(re.findall(r"증명책임::", t)),
            topic=len(re.findall(r"주제::", t)),
            need_verify=len(re.findall(r"검증필요", t)),
            unclear=len(re.findall(r"\[불명확", t)),
            kichul=len(re.findall(r"기출", t)),
        ))
    return rows


def scan_wiki(wiki_dir):
    per = collections.defaultdict(collections.Counter)
    cases = collections.Counter()
    case_subj = collections.Counter()
    case_with_order = collections.Counter()
    for r, _, fs in os.walk(wiki_dir):
        for f in fs:
            if not f.endswith(".md"):
                continue
            t = read(os.path.join(r, f))
            d = frontmatter(t)
            ty = d.get("type", "")
            s = d.get("과목", "?")
            if ty == "쟁점":
                c = per[s]
                c["논점"] += 1
                if "카드검증" in d:
                    c["카드검증"] += 1
                if d.get("약점") == "true":
                    c["약점"] += 1
                try:
                    if int(d.get("회독", 0)) > 0:
                        c["회독>0"] += 1
                except ValueError:
                    pass
                c["진도=" + (d.get("진도") or "-")] += 1
            elif ty == "사례":
                cases["사례노트"] += 1
                case_subj[s] += 1
                if "풀이순서검증" in d:
                    cases["풀이순서검증"] += 1
                if re.search(r"^##+\s*풀이순서", t, re.M):
                    case_with_order[s] += 1
    return per, cases, case_subj, case_with_order


def scan_state(state_dir):
    out = {}
    lj = os.path.join(state_dir, "learning.json")
    if os.path.exists(lj):
        d = json.load(open(lj, encoding="utf-8"))
        items = d.get("srs", {}).get("items", [])
        out["weak_points"] = len(d.get("weak_points", []))
        out["srs_items"] = len(items)
        out["srs_reviewed"] = sum(1 for i in items if (i.get("repetitions") or 0) > 0)
        out["srs_graduated"] = sum(1 for i in items if i.get("status") == "graduated")
        out["exams"] = d.get("exams", [])
        out["last_session"] = d.get("last_session")
    out["grad_queue"] = os.path.exists(os.path.join(state_dir, "srs_graduated_queue.jsonl"))
    dl = os.path.join(state_dir, "drill_log.jsonl")
    out["drill_rows"] = (sum(1 for l in open(dl, encoding="utf-8") if l.strip())
                         if os.path.exists(dl) else 0)
    return out


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--cards", default="cards")
    ap.add_argument("--wiki", default="wiki")
    ap.add_argument("--state", default="state")
    a = ap.parse_args()
    cards_dir = os.path.join(a.root, a.cards)
    rows = scan_cards(cards_dir)

    total = sum(r["est"] for r in rows)
    print(f"# 카드 인벤토리 (자동 생성)\n")
    print(f"- 카드 파일: {len(rows)}개 · 추정 카드 수: {total:,}장 · cards/ 총 크기: "
          f"{sum(os.path.getsize(os.path.join(cards_dir, r['file'])) for r in rows) / 1e6:.1f} MB")
    print(f"- frontmatter 있음: {sum(r['has_fm'] for r in rows)} / 과목 키 있음: "
          f"{sum(1 for r in rows if r['subj'])}")

    # 책별
    books = collections.defaultdict(list)
    for r in rows:
        books[r["book"]].append(r)
    print("\n## 책(소스)별 커버리지\n")
    brows = []
    for b, rs in sorted(books.items(), key=lambda x: -sum(r["est"] for r in x[1])):
        paged = sorted([r for r in rs if r["pages"]], key=lambda r: r["pages"])
        overlaps, gaps = [], []
        for r1, r2 in zip(paged, paged[1:]):
            s1, e1 = r1["pages"]
            s2, e2 = r2["pages"]
            if s2 <= e1:
                overlaps.append(f"p{s2}-{min(e1, e2)}")
            elif s2 > e1 + 1:
                gaps.append(f"p{e1 + 1}-{s2 - 1}")
        cover = (f"p{paged[0]['pages'][0]}-{max(r['pages'][1] for r in paged)}" if paged else "-")
        brows.append([b, len(rs), f"{sum(r['est'] for r in rs):,}", cover,
                      len(overlaps), ", ".join(gaps) if gaps else "-"])
    print(md_table(["책", "파일", "카드(추정)", "커버 페이지", "겹침 구간 수", "빈 구간"], brows))

    # 포맷
    print("\n## 파일 포맷 분류\n")
    fc = collections.Counter(r["fmt"] for r in rows)
    print(md_table(["포맷", "파일 수"], sorted(fc.items(), key=lambda x: -x[1])))

    # 품질
    print("\n## 품질 지표(파일 단위 집계)\n")
    q = [
        ["번호 있는 cloze `{{cN::}}`", sum(r["cloze_num"] for r in rows),
         sum(1 for r in rows if r["cloze_num"])],
        ["번호 없는 cloze `{{…}}` (빌드 전 0이어야 함)", sum(r["cloze_nonum"] for r in rows),
         sum(1 for r in rows if r["cloze_nonum"])],
        ["한자 잔존 글자(빌드 전 0이어야 함)", sum(r["hanja"] for r in rows),
         sum(1 for r in rows if r["hanja"])],
        ["`단계::` 태그", sum(r["stage"] for r in rows), sum(1 for r in rows if r["stage"])],
        ["`증명책임::` 태그", sum(r["burden"] for r in rows), sum(1 for r in rows if r["burden"])],
        ["`주제::` 태그", sum(r["topic"] for r in rows), sum(1 for r in rows if r["topic"])],
        ["`검증필요` 표기", sum(r["need_verify"] for r in rows),
         sum(1 for r in rows if r["need_verify"])],
        ["`[불명확]` 표기", sum(r["unclear"] for r in rows), sum(1 for r in rows if r["unclear"])],
        ["`기출` 표기(출처 명시 여부 수동 확인 필요)", sum(r["kichul"] for r in rows),
         sum(1 for r in rows if r["kichul"])],
    ]
    print(md_table(["지표", "건수", "파일 수"], q))
    print("\n번호 없는 cloze 상위 파일:")
    for r in sorted(rows, key=lambda r: -r["cloze_nonum"])[:8]:
        if r["cloze_nonum"]:
            print(f"- {r['file']} — {r['cloze_nonum']}건")
    print("\n한자 잔존 상위 파일:")
    for r in sorted(rows, key=lambda r: -r["hanja"])[:8]:
        if r["hanja"]:
            print(f"- {r['file']} — {r['hanja']}자")

    # frontmatter 과목 값
    print("\n## frontmatter `과목:` 값 분포(풀네임 규칙 #50-B 대조)\n")
    sc = collections.Counter(r["subj"] or "(없음)" for r in rows)
    print(md_table(["과목 값", "파일 수", "비고"],
                   [[k, v, "" if k in STD_SUBJECTS or k == "(없음)" else "비표준(정규화 필요)"]
                    for k, v in sc.most_common()]))

    # 위키
    wiki_dir = os.path.join(a.root, a.wiki)
    if os.path.isdir(wiki_dir):
        per, cases, case_subj, case_order = scan_wiki(wiki_dir)
        print("\n## 위키 논점 노트 — 카드검증 게이트 현황\n")
        wr = []
        for s, c in sorted(per.items(), key=lambda x: -x[1]["논점"]):
            wr.append([s, c["논점"], c["카드검증"], c["논점"] - c["카드검증"], c["회독>0"], c["약점"],
                       ", ".join(f"{k[3:]} {v}" for k, v in c.items() if k.startswith("진도="))])
        wr.append(["합계", sum(c["논점"] for c in per.values()), sum(c["카드검증"] for c in per.values()),
                   sum(c["논점"] - c["카드검증"] for c in per.values()),
                   sum(c["회독>0"] for c in per.values()), sum(c["약점"] for c in per.values()), ""])
        print(md_table(["과목", "논점", "카드검증 완료", "미완료", "회독>0", "약점", "진도"], wr))
        print("\n## 사례노트 ↔ 풀이순서 카드(역할②)\n")
        order_cards = {}
        for r in rows:
            if r["file"].startswith("사례풀이순서_"):
                order_cards[r["file"].split("_")[1]] = r["est"]
        cr = []
        for s, n in case_subj.most_common():
            cr.append([s, n, case_order.get(s, 0), order_cards.get(s, "(파일 없음)")])
        cr.append(["합계", sum(case_subj.values()), sum(case_order.values()), sum(order_cards.values())])
        print(md_table(["과목(노트 frontmatter)", "사례노트", "`## 풀이순서` 보유", "풀이순서 카드 파일의 카드 수"], cr))
        print(f"\n- 사례노트 `풀이순서검증` 마커 보유: {cases['풀이순서검증']} / {cases['사례노트']}")

    # state
    state_dir = os.path.join(a.root, a.state)
    if os.path.isdir(state_dir):
        st = scan_state(state_dir)
        print("\n## 약점·SRS → 카드 핸드오프 상태\n")
        print(f"- weak_points {st.get('weak_points')}건 · SRS 항목 {st.get('srs_items')}건 · "
              f"리뷰 1회 이상 {st.get('srs_reviewed')}건 · 졸업 {st.get('srs_graduated')}건")
        print(f"- srs_graduated_queue.jsonl 존재: {st.get('grad_queue')} · drill_log 행: {st.get('drill_rows')} · "
              f"last_session: {st.get('last_session')}")
        print(f"- 약점포섭_*_v37.md 파일: "
              f"{[r['file'] for r in rows if r['file'].startswith('약점포섭_')] or '없음'}")
        print(f"- exams: {json.dumps(st.get('exams'), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
