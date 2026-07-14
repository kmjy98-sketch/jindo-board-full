# -*- coding: utf-8 -*-
"""드릴 결과를 논점노트 frontmatter(Bases 정본)에 역기록. 닫힌루프 보드층.
드릴 에이전트가 실제 다룬 논점을 명시(과목/제목) — 정규식 추정 금지(#1 근거주의).

사용:
  python .agent/skills/daily-drill/scripts/mark_progress.py \
    --notes "민법/채권자대위권,민법/대상청구권" --weak --review
플래그: --weak(약점:true) / --clear-weak(약점:false) / --read(회독+1) / --review(최근복습=오늘) / --dry
"""
import os, re, sys, json
from datetime import datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = r"E:\법학볼트"
def has(f): return f in sys.argv
def arg(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    return None
notes = [n.strip() for n in (arg("--notes") or "").split(",") if n.strip()]
DRY = has("--dry")
today = datetime.now().strftime("%Y-%m-%d")
if not notes:
    print("--notes 필요 (예: 민법/채권자대위권,민법/대상청구권)"); sys.exit(1)
def setline(fm, key, val):
    if re.search(rf"(?m)^{key}:", fm):
        return re.sub(rf"(?m)^{key}:.*$", f"{key}: {val}", fm)
    return fm + f"\n{key}: {val}"
ok = miss = 0
done = []
for n in notes:
    p = os.path.join(ROOT, "sync", "위키", *n.split("/")) + ".md"
    if not os.path.exists(p):
        print(f"  [없음] {n}"); miss += 1; continue
    t = open(p, encoding="utf-8").read()
    e = t.find("\n---", 3)
    if not t.startswith("---") or e < 0:
        print(f"  [frontmatter X] {n}"); miss += 1; continue
    fm = t[3:e]; chg = []
    if has("--weak"): fm = setline(fm, "약점", "true"); chg.append("약점=true")
    if has("--clear-weak"): fm = setline(fm, "약점", "false"); chg.append("약점=false")
    if has("--read"):
        m = re.search(r"(?m)^회독:\s*(\d+)", fm); cur = int(m.group(1)) if m else 0
        fm = setline(fm, "회독", cur + 1); chg.append(f"회독={cur+1}")
    if has("--review"): fm = setline(fm, "최근복습", today); chg.append(f"최근복습={today}")
    if not chg: print("  (변경 플래그 없음)"); sys.exit(1)
    if DRY:
        print(f"  [dry] {n}: {', '.join(chg)}")
    else:
        open(p, "w", encoding="utf-8").write(t[:3] + fm + t[e:]); print(f"  [기록] {n}: {', '.join(chg)}")
        done.append(n)
    ok += 1

# learning.json weak_points 동기(#20·#35 약점→쟁점 연결). --weak 추가 / --clear-weak 제거.
if done and not DRY and (has("--weak") or has("--clear-weak")):
    lp = os.path.join(ROOT, ".agent", "state", "learning.json")
    try:
        d = json.load(open(lp, encoding="utf-8"))
        wp = d.setdefault("weak_points", [])
        for n in done:
            if has("--weak") and n not in wp: wp.append(n)
            if has("--clear-weak") and n in wp: wp.remove(n)
        json.dump(d, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  [learning.json] weak_points {len(wp)}건 동기")
    except Exception as ex:
        print(f"  [learning.json 동기 실패] {ex}")

print(f"{'(dry) ' if DRY else ''}대상 {ok} / 누락 {miss}")
