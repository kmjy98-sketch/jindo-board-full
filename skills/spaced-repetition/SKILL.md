---
name: spaced-repetition
description: 간격 반복(SM-2) 복습 스케줄러. "복습 주기 계산", "오늘 복습할 문제", "복습 일정 갱신" 요청 시 사용.
---

# Spaced Repetition Skill

<!-- @rule: CLAUDE.md#19-B 진도 정본·#20 약점 저장소 -->

## Quick Start

오늘 복습할 항목 조회:

```powershell
python .agent/skills/spaced-repetition/scripts/srs_scheduler.py --today
```

---

## 데이터 파일 구조

### 약점 원천 — `.agent/state/learning.json` (단일 정본)

약점 목록(`weak_points`)과 SRS 항목(`srs.items`)을 함께 보관한다.

```
learning.json
├── weak_points: ["권리남용 요건 (주관+객관)", ...]   ← 약점 원천(단일 정본)
└── srs.items: [{id, content, topic, ef, interval, next_review, ...}]
```

- **`weak_points`** = 약점 원천. board_server_v2(`6.진도관리/board_server_v2.py`)가 `read_weak()`으로 읽어 진도보드 약점 패널에 표시한다. daily-drill 드릴 결과도 이 배열에 추가/제거한다.
- **`srs.items`** = SM-2 간격 관리. 각 항목은 `weak_points`에서 유래(`source: "weak_points"`)하거나 드릴 채점 결과로 등록된다. 간격(`interval`), EF, `next_review` 계산은 SM-2가 담당한다.
- **`srs_log.json`** = 과거 리뷰 이벤트 로그(타임스탬프·점수 이력). 간격 계산의 이력 기록용이며 약점 원천이 아니다. 약점 원천은 오직 `learning.json weak_points`.

> **규칙**: `srs_log.json`과 `learning.json`은 역할이 다르다. 간격 관리(SM-2 계산·이벤트 로그) = `srs_log.json`, 약점 원천 및 SRS 스케줄 항목 = `learning.json`. 약점 추가/조회는 반드시 `learning.json`을 읽는다.

---

## 보드 약점 frontmatter 연동

논점노트(`sync/위키/{과목}/{논점}.md`) frontmatter의 `약점: true/false` 필드와 `learning.json weak_points`는 **닫힌루프(#50-A)**로 연결된다:

```
드릴 틀림
  → mark_progress.py --weak     ← 논점노트 frontmatter 약점: true 기록
  → board_server_v2 build_board ← frontmatter 읽어 약점 목록 집계
  → read_weak()                 ← learning.json weak_points 표시
```

### mark_progress.py 플래그

```powershell
# 약점 표시 (frontmatter 약점: true)
python .agent/skills/daily-drill/scripts/mark_progress.py \
  --notes "민법/채권자대위권" --weak

# 약점 해제 (frontmatter 약점: false)
python .agent/skills/daily-drill/scripts/mark_progress.py \
  --notes "민법/채권자대위권" --clear-weak
```

- `--weak` = 해당 논점노트 frontmatter에 `약점: true` 기록
- `--clear-weak` = `약점: false` 기록 (SRS 완료 후)
- `--review` = `최근복습: YYYY-MM-DD` 기록
- `--read` = `회독` 카운터 +1
- `--dry` = 실행 없이 변경 내용 미리보기

frontmatter `약점: true`인 논점은 board_server_v2 보드에서 약점 패널로 집계된다(CLAUDE.md #19-B).

---

## 주요 기능

### 1. 오늘 복습 항목 조회

```powershell
python scripts/srs_scheduler.py --today
```

### 2. 항목 추가

```powershell
python scripts/srs_scheduler.py --add "불법행위 요건" --topic "민사소송법"
```

과목명은 풀네임 사용: 민사소송법·민사집행법·민법·형법총론·형법각론·헌법·행정법·형사소송법 (약칭 금지 — CLAUDE.md #51·#50-B).

### 3. 복습 결과 기록

```powershell
python scripts/srs_scheduler.py --review <item_id> --score <0-5>
```

**점수 기준 (SM-2):**

- 0: 완전 망각
- 1-2: 틀림 (다시 학습 필요)
- 3: 어려웠지만 맞춤
- 4: 맞춤
- 5: 매우 쉬움

### 4. 전체 상태 조회

```powershell
python scripts/srs_scheduler.py --status
```

---

## 알고리즘 (SM-2)

- 정답 시: 간격 = 이전간격 × EF (2.5 기본)
- 오답 시: 간격 초기화 (1일)
- EF 조정: 점수에 따라 0.8~2.5 범위

---

## 최신연구 반영 (2026-06-21, 보고서 9.작업중/클로드/개선종합_카드SRS_룰감사_2026-06-21.md)

- **SM-2 유지 + Anki FSRS 핸드오프**: 본 스킬(Claude 중단기 복습)은 SM-2 유지. 장기 파지는 Anki(FSRS-6 — SM-2 대비 99.6% 사용자 보정 우수, 단 '리뷰 X% 감소'는 근거 아님)로 핸드오프 — 이중관리 아님. 전면 FSRS 전환은 보류(확정 스코프 제외).
- **'시험 임박 간격 축소 cap' 정정**: 학술근거 약함(Cepeda 2008과 충돌 — 잔여시간 줄면 최적간격 '비율'은 오히려 커짐; 'undershoot가 overshoot보다 해롭다'는 0-3 반증). cap 대신 **deadline-aware desired-retention**(시험일에 recall 확률을 목표치 이상 유지)으로 재정식화. 목적 = 막판 인출이 망각곡선 바닥에 떨어지지 않게.
- **첫 인출 지연·곤란(desirable difficulty)**이 expanding 스케줄 '형태'보다 장기파지에 핵심(Karpicke&Roediger 2007: 등간격 45% vs expanding 33% @2일, d=0.50).
- 초기 due 분산(위 표 D+1/2/3)은 `--review-type` 인자로 코드 반영 완료(P0-3, 2026-07-14 — 아래 표 참조).

---

## 답안 채점 연동 간격 (2026-06-16 신설)

case-answer-review 채점 결과를 복습 항목으로 등록할 때, 오류 유형별 초기 간격을 다음으로 둔다(출처: `9.작업중/클로드/CODEX_BOOTSTRAP_REPORT.md` §19 채택분). 채점 척도는 case-answer-review 루브릭의 0.0~1.0 분수 척도를 기준으로 하며, 본 표의 0~100/% 표기는 0~1로 환산해 적용한다. 이후 간격은 SM-2가 관리한다.

> ※ **코드 반영 완료(P0-3, 2026-07-14)**: `srs_scheduler.py --add "<약점>" --review-type <유형>` 이 아래 표의 초기 due(D+N)를 자동 설정한다(`REVIEW_TYPE_DUE` 매핑, 등록 시 `next_review = D+N` · 이후 간격은 순수 SM-2). 중복 항목에 `--review-type`이 오면 **더 이른 due로만 당긴다**(재오답 반영 — 뒤로 미루지 않음). `--review-type` 미지정 시 기존 동작(초기 interval=1). 등록은 **사용자가 채점 확정/복습 등록을 지시할 때만**(silent write 금지) — case-answer-review는 제안까지만.

| 채점 결과 | 초기 due | review_type |
|---|---|---|
| 쟁점 자체를 못 찾음 | D+1 | issue_spotting |
| 결론 반대 | D+1 | conclusion_drill |
| 키워드 0.5 미만(루브릭 0~1 척도) | D+2 | keyword_recall |
| 목차 구조 누락 | D+3 | outline_recall |
| 포섭 0.6 미만(루브릭 0~1 척도) | D+2 | mini_application |
| 안정적 통과 | D+7 | stable_pass (이후 정상 SM-2) |
| 2회 연속 양호 | completed 후보 | — |

> 쟁점 못 찾음이 목차 구조 누락을 겸할 때는 **issue_spotting(D+1) 우선**(더 이른 재출제). `--review-type` 값은 위 6종(issue_spotting·conclusion_drill·keyword_recall·mini_application·outline_recall·stable_pass)만 허용 — `srs_scheduler.py`의 `REVIEW_TYPE_DUE`와 1:1 대응.

- 등록은 **사용자가 채점 확정/복습 등록을 지시할 때만** 한다(silent write 금지). case-answer-review는 제안까지만 한다.
- 반복 오답(같은 항목 2회+)은 Anki 카드 후보로도 연동된다 — card-wiki-pipeline §8 준수.
