# 📊 Claude Code 종합 주식 분석 커맨드

> Claude Code에서 `/stock-analysis AAPL` 한 줄로 종합 주식 분석 리포트를 자동 생성합니다.

---

## 🚀 설치 방법

### 방법 1: Skills 형식 (권장 — 최신 포맷)

```bash
# 프로젝트 루트에서 실행
mkdir -p .claude/skills/stock-analysis
cp stock-analysis-command/.claude/skills/stock-analysis/SKILL.md \
   .claude/skills/stock-analysis/SKILL.md
```

또는 전역(모든 프로젝트)에서 사용하려면:

```bash
mkdir -p ~/.claude/skills/stock-analysis
cp stock-analysis-command/.claude/skills/stock-analysis/SKILL.md \
   ~/.claude/skills/stock-analysis/SKILL.md
```

### 방법 2: Commands 형식 (레거시 — 호환용)

```bash
# 프로젝트 루트에서
mkdir -p .claude/commands
cp stock-analysis-command/.claude/commands/stock-analysis.md \
   .claude/commands/stock-analysis.md
```

전역 사용:

```bash
mkdir -p ~/.claude/commands
cp stock-analysis-command/.claude/commands/stock-analysis.md \
   ~/.claude/commands/stock-analysis.md
```

---

## 📖 사용법

Claude Code 터미널에서:

```
# 미국 주식
/stock-analysis AAPL
/stock-analysis TSLA
/stock-analysis NVDA
/stock-analysis MSFT

# 한국 주식 (코스피)
/stock-analysis 005930.KS     # 삼성전자
/stock-analysis 000660.KS     # SK하이닉스
/stock-analysis 035720.KS     # 카카오

# 한국 주식 (코스닥)
/stock-analysis 247540.KQ     # 에코프로비엠
/stock-analysis 068270.KQ     # 셀트리온제약
```

---

## 📦 분석 항목

| # | 분석 영역 | 세부 내용 |
|---|----------|----------|
| 1 | **종목 개요** | 종목명, 섹터, 시가총액, 52주 범위 |
| 2 | **핵심 투자 지표** | PER, PBR, PSR, EV/EBITDA, ROE, ROA, 배당수익률 |
| 3 | **재무제표 (3개년)** | 손익계산서, 재무상태표, 현금흐름표 |
| 4 | **수익성 분석** | 영업이익률, 순이익률, FCF 추이 |
| 5 | **안정성 분석** | 부채비율, 유동비율, 이자보상배율 |
| 6 | **성장성 분석** | 매출·EPS 성장률, YoY 비교 |
| 7 | **기술적 분석** | SMA 20/60/120, MACD, RSI, 골든/데드크로스 |
| 8 | **매수/매도 타이밍** | 종합 기술적 시그널 판정 |
| 9 | **최근 실적** | 분기 실적, 컨센서스 대비, 가이던스 |
| 10 | **산업 분석** | 글로벌 동향, 경쟁사, 정책, AI 수요 |
| 11 | **뉴스·센티먼트** | 최신 뉴스 5건, 시장 심리 |
| 12 | **리스크 요인** | 거시, 기업, 산업, 규제 리스크 |
| 13 | **6개월 전망** | 상방/하방 요인, 주요 일정 |
| 14 | **종합 투자 판단** | 100점 만점 스코어, 단기/중기/장기 의견 |

---

## 📂 출력 결과

```
output/
├── stock-report-AAPL.md       # 종합 분석 리포트 (마크다운)
└── chart_AAPL.png             # 기술적 분석 차트 (이동평균, MACD, RSI)
```

---

## ⚙️ 필요 패키지

커맨드 실행 시 자동 설치됩니다:

```
yfinance pandas numpy matplotlib ta requests beautifulsoup4
```

---

## 🔧 커스터마이징

### 분석 범위 조정
`SKILL.md`의 Phase 2에서 웹 검색 키워드를 수정하면 특정 관점의 분석을 추가할 수 있습니다.

### 차트 스타일 변경
`stock_analyzer.py`의 `generate_chart()` 메서드에서 색상·레이아웃 조정 가능.

### 리포트 템플릿 변경
Phase 3의 마크다운 구조를 원하는 형식으로 수정하세요.

---

## ⚠️ 면책 조항

본 도구는 **교육·참고 목적**으로만 사용하세요.
AI 기반 자동 분석 결과이며, **투자 권유가 아닙니다.**
투자 판단은 본인 책임이며, 전문 투자자문을 권장합니다.

---

## 📁 디렉토리 구조

```
.claude/
├── skills/
│   └── stock-analysis/
│       └── SKILL.md              ← 권장 (최신 포맷)
└── commands/
    └── stock-analysis.md         ← 레거시 호환용
```
