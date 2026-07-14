# 진도 보드 — 풀버전 (개인 학습 시스템 백업) 🔒

> **비공개(Private) 개인 백업.** 배포 금지. 카드·위키에 시판 교재에서 추출한 저작권 자료가 포함되어 있어 절대 공개하지 않는다. 공개 배포판은 별도 저장소 [jindo-board](https://github.com/kmjy98-sketch/jindo-board)(도구·프레임워크만).

법학 진도·카드·SRS·드릴을 하나로 묶은 **닫힌 루프 학습 시스템**의 시점 스냅샷이다. 라이브 볼트(`E:\법학볼트`)에서 복제했으며, 스터디 인수인계가 아니라 **내 기기 간 백업·이관**용이다.

## ⚠️ 먼저 알아둘 것

- **단독 실행 안 됨.** 드릴·SRS·카드 생성은 그냥 프로그램이 아니라 **Claude Code 스킬**이다. `build_session.py`는 논점을 고를 뿐, 실제 출제·채점은 Claude가 소스를 읽어서 한다(SKILL.md 소스근거 원칙). 사용하려면 Claude Code + 볼트 규칙(CLAUDE.md) + 본인 소유 교재가 있어야 한다.
- **시점 스냅샷.** 라이브 볼트가 정본이다. 이 저장소는 공부하는 순간 곧 낡는다 — 백업/이관 목적으로만.
- **저작권.** `cards/`·`wiki/`는 교재 OCR 파생물. 개인 소장·백업은 사적 이용이지만 **배포·공개는 침해**다.

## 📂 구성

```
진도_board.html      # v9 볼트직결 보드(기간목표) — 데스크톱 입력 UI
server/              # (선택) 로컬 서버 모드 board_server_v2.py
skills/              # 엔진 = Claude Code 스킬 3종
  ├─ daily-drill/         # 일일 드릴(2트랙): build_session·log_result·mark_progress
  ├─ spaced-repetition/   # SM-2 SRS: srs_scheduler
  └─ anki-card-generation/# 카드 → apkg 소비: consume_graduated
cards/               # 암기장 카드 408개 (outputs/02_cards_v37 스냅샷)
state/               # learning.json(약점·시험·SRS) · srs_log · srs_events · drill_log
wiki/                # 논점 frontmatter = 진도 정본 + 사례노트 + MOC (sync/위키 스냅샷)
docs/                # 사용설명서
```

## 🔄 닫힌 루프

```
목차 → 쟁점(wiki) → 카드(cards) → 드릴(daily-drill) → 보드(진도_board.html)
                                                          |
                        약점(state/learning.json) <-------+
                                  |
                        SRS(spaced-repetition -> 안키 FSRS)
```

키 표준: `과목|대분류|논점`. 보드·드릴·SRS가 모두 같은 논점 frontmatter를 읽고 쓴다.

## 🛠 복원/사용

1. 라이브 볼트가 있으면 그걸 쓴다(이 저장소는 백업).
2. 새 기기로 이관 시: 이 저장소 내용을 볼트 구조(`sync/위키/`, `outputs/02_cards_v37/`, `.agent/state/`, `.agent/skills/`, `6.진도관리/`)에 배치 → Claude Code + CLAUDE.md 규칙 로드.
3. 보드만 쓸 거면 `진도_board.html`을 크롬·엣지로 열고 [볼트 연결] → `wiki/` 상위 폴더 지정.

## 관련

- 공개 도구판: https://github.com/kmjy98-sketch/jindo-board (+ 모바일 앱 `app/`)
- 진행 현황·재개 지점: 볼트 `9.작업중/클로드/현황_진도보드_웹앱화_git_앱_2026-07-14.md`
