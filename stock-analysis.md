---
allowed-tools: Bash, Read, Write, WebSearch, WebFetch
description: 종합 주식 분석 — 기본적·기술적·산업 분석 + 투자 판단
argument-hint: <티커> (예: AAPL, 005930.KS)
---

$ARGUMENTS 종목에 대해 아래 종합 주식 분석을 수행해줘.

## 분석 절차

### Step 1: 환경 & 데이터 수집
1. `pip install yfinance pandas numpy matplotlib ta --quiet` 실행
2. 프로젝트 루트의 `.claude/skills/stock-analysis/SKILL.md`를 참조하여 `stock_analyzer.py` 스크립트 생성
3. `python stock_analyzer.py $ARGUMENTS` 실행하여 전량 데이터 수집 + 차트 생성

### Step 2: 웹 리서치
아래 키워드로 최신 뉴스·실적·산업 동향 검색:
- "$ARGUMENTS stock news latest"
- "$ARGUMENTS earnings quarterly results"
- "$ARGUMENTS industry outlook competitor"
- "$ARGUMENTS analyst rating forecast"

### Step 3: 종합 리포트 작성
SKILL.md의 Phase 3 리포트 템플릿에 따라 10개 섹션 분석 리포트를 마크다운으로 작성.

포함 항목:
- 종목 개요 & 핵심 지표 (PER/PBR/ROE)
- 3개년 재무제표 분석 (수익성/안정성/성장성)
- 기술적 분석 (이동평균선 20/60/120일, MACD, RSI)
- 매수/매도 타이밍 판단
- 최근 실적 & 가이던스
- 산업 동향 & 경쟁 분석 (반도체 정책, AI 수요 포함)
- 리스크 요인 & 향후 6개월 주가 영향 요인
- 100점 만점 종합 점수 & 투자 의견 (단기/중기/장기)

### Step 4: 저장
`output/stock-report-$ARGUMENTS.md` 및 `output/chart_$ARGUMENTS.png` 저장
