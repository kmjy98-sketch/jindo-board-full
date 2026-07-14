# -*- coding: utf-8 -*-
"""_srs_review_type.py — 채점 오류유형 → 초기 복습 due 매핑 (Q2-2 파일럿).

배경: srs_scheduler.add_item()은 next_review=today(D+0) 고정이라, case-answer-review
채점 결과를 복습 등록할 때 spaced-repetition SKILL "답안 채점 연동 간격" 표가 코드에
반영되지 않는다(초기 interval=1 고정). 이 모듈이 그 표를 코드로 구현한다.

표(spaced-repetition SKILL):
  쟁점 못 찾음→D+1(issue_spotting) / 결론 반대→D+1(conclusion_drill) /
  키워드<0.5→D+2(keyword_recall) / 목차 누락→D+3(outline_recall) /
  포섭<0.6→D+2(mini_application) / 안정 통과→D+7(stable)
시스템 유틸리티 — 근거 2줄 규칙(#30) 면제.
"""
from datetime import datetime, timedelta

# review_type → 초기 due offset(일). 출처: spaced-repetition SKILL.
INITIAL_DUE_OFFSET = {
    "issue_spotting": 1,
    "conclusion_drill": 1,
    "keyword_recall": 2,
    "mini_application": 2,
    "outline_recall": 3,
    "stable": 7,
}
DEFAULT_OFFSET = 1  # 미지정 review_type은 보수적으로 D+1


def initial_due_offset(review_type):
    """review_type의 초기 due offset(일). 미지정은 D+1."""
    return INITIAL_DUE_OFFSET.get(review_type, DEFAULT_OFFSET)


def initial_next_review(today_str, review_type):
    """등록일(today_str, 'YYYY-MM-DD')에 review_type 오프셋을 더한 next_review 날짜."""
    base = datetime.strptime(today_str, "%Y-%m-%d")
    return (base + timedelta(days=initial_due_offset(review_type))).strftime("%Y-%m-%d")
