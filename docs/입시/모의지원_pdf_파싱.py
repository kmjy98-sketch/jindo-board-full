#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""모의지원 보드 PDF → 표 파싱.

모의지원 사이트의 "전체 현황" 화면을 PDF로 저장한 파일에서 지원자 표를
그대로 뽑아낸다. 스크린샷을 눈으로 읽으면 숫자를 틀리기 쉬워서 만들었다.

이 PDF는 서브셋 폰트에 커스텀 인코딩을 쓰므로, 글자를 읽으려면 폰트마다
붙어 있는 ToUnicode CMap으로 디코딩해야 한다. 위치는 텍스트 행렬(Tm)이
아니라 그 앞의 변환행렬(cm)에 들어 있어서 둘을 합쳐야 한다.

주의: 보드마다 LEET 열의 의미가 다르다. 열 머리글을 반드시 확인할 것.
  - "LEET 표준점수"   → 법전협 원표준점수 합계 (언어+추리)
  - "LEET 백분위점수" → 해당 대학 환산점수. 다른 대학 보드와 직접 비교 불가.

사용법:  python3 모의지원_pdf_파싱.py <보드.pdf> [출력.json]
"""

import re, zlib, sys, json

PDF = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None

import re, zlib, sys

raw = open(PDF,'rb').read()

# --- 1. index all indirect objects ---
objs = {}
for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj(.*?)endobj', raw, re.S):
    objs[int(m.group(1))] = m.group(3)

def stream_of(num):
    body = objs.get(num, b'')
    m = re.search(rb'stream\r?\n(.*?)\r?\nendstream', body, re.S)
    if not m: return None
    try: return zlib.decompress(m.group(1))
    except Exception: return m.group(1)

# --- 2. parse a ToUnicode CMap into {code: char} ---
def parse_cmap(data):
    table = {}
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange', data, re.S):
        for lo, hi, dst in re.findall(rb'<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>', blk):
            lo, hi, dst = int(lo,16), int(hi,16), int(dst,16)
            for i in range(lo, hi+1):
                table[i] = chr(dst + (i-lo))
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar', data, re.S):
        for src, dst in re.findall(rb'<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>', blk):
            table[int(src,16)] = chr(int(dst,16))
    return table

# --- 3. font resource name -> cmap ---
fontmaps = {}
for num, body in objs.items():
    if b'/Type' in body and b'/Font' in body:
        tu = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', body)
        if tu:
            d = stream_of(int(tu.group(1)))
            if d: fontmaps[num] = parse_cmap(d)

name2cmap = {}
for num, body in objs.items():
    fm = re.search(rb'/Font\s*<<(.*?)>>', body, re.S)
    if fm:
        for nm, ref in re.findall(rb'/(\w+)\s+(\d+)\s+\d+\s+R', fm.group(1)):
            if int(ref) in fontmaps:
                name2cmap[nm.decode()] = fontmaps[int(ref)]

# --- 4. walk content streams, capture (y, x, text) ---
def unescape(b):
    out, i = bytearray(), 0
    while i < len(b):
        c = b[i]
        if c == 0x5c and i+1 < len(b):
            n = b[i+1]
            mp = {ord('n'):10, ord('r'):13, ord('t'):9, ord('b'):8, ord('f'):12,
                  ord('('):40, ord(')'):41, ord('\\'):92}
            if n in mp: out.append(mp[n]); i += 2; continue
            if 0x30 <= n <= 0x37:
                oct_ = b[i+1:i+4]
                m = re.match(rb'[0-7]{1,3}', oct_)
                out.append(int(m.group(0),8) & 0xFF); i += 1+len(m.group(0)); continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return bytes(out)

items = []
TOK = re.compile(
    rb'/(\w+)\s+1\s+Tf'                                            # 1 font
    rb'|([-\d.]+)\s+0\s+0\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm'  # 2-5 Tm
    rb'|q\s+1\s+0\s+0\s+-1\s+([-\d.]+)\s+([-\d.]+)\s+cm'          # 6-7 cm
    rb'|\((?:\\.|[^\\()])*\)\s*Tj'                                  # 8 Tj
    rb'|\[(?:[^\[\]\\]|\\.)*\]\s*TJ', re.S)                        # 9 TJ
STR = re.compile(rb'\((?:\\.|[^\\()])*\)', re.S)

for num in sorted(objs):
    data = stream_of(num)
    if not data or (b'Tj' not in data and b'TJ' not in data): continue
    cur_font, x, y, cm_tx, cm_ty = None, 0.0, 0.0, 0.0, 0.0
    for tok in TOK.finditer(data):
        t = tok.group(0)
        if tok.group(1):
            cur_font = tok.group(1).decode()
        elif tok.group(4) is not None:
            x = float(tok.group(4)); y = float(tok.group(5))
        elif tok.group(6) is not None:
            cm_tx = float(tok.group(6)); cm_ty = float(tok.group(7))
        else:
            cmap = name2cmap.get(cur_font, {})
            parts = []
            for sm in STR.finditer(t):
                body = sm.group(0)[1:-1]
                parts.append("".join(cmap.get(bb, chr(bb)) for bb in unescape(body)))
            s = "".join(parts)
            if s.strip():
                items.append((round(cm_ty - y, 1), round(cm_tx + x, 1), s))


# --- 5. 열 경계로 표 복원 -------------------------------------------------
# x 좌표는 머리글 위치에서 얻은 것이다. 보드 폭이 다르면 여기를 고친다.
COLS = [("등수",0,55),("종합점수",55,120),("LEET",120,200),("공인영어",200,290),
        ("GPA",290,350),("서류",350,520),("출신대학",520,605),("전공계열",605,685),
        ("나이",685,735),("타군",735,845),("인증",845,905)]

title = " ".join(s for y,x,s in sorted(items, key=lambda t:(-t[0],t[1])) if y > 6090)

# 각 표 행은 여러 줄에 걸쳐 있다. 맨 왼쪽 열의 등수 숫자를 행 기준선으로 삼는다.
anchors = sorted([(y,s) for y,x,s in items
                  if x < 55 and y < 5900 and re.fullmatch(r"\d{1,3}", s)],
                 key=lambda t: -t[0])

rows = []
for y0, rank in anchors:
    band = [(x,s) for y,x,s in items if y0-46 <= y <= y0+40]
    rec = {name: "".join(s for x,s in sorted(band) if lo <= x < hi).strip()
           for name, lo, hi in COLS}
    rec["등수"] = rank
    rows.append(rec)

hdr = ["등수","종합점수","LEET","공인영어","GPA","출신대학","전공계열","나이","타군"]
print(f"# {title}   ({len(rows)}명)")
print(" | ".join(hdr))
for r in rows:
    print(" | ".join(r[h] for h in hdr))

if OUT:
    json.dump({"title": title, "rows": rows}, open(OUT,"w"),
              ensure_ascii=False, indent=1)
    print(f"\n-> {OUT}", file=sys.stderr)
