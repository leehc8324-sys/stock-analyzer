---
name: stock-analysis
description: 종합 주식 분석 커맨드. 종목 티커를 입력하면 기본적 분석(재무지표, 실적), 기술적 분석(차트, 이동평균선, MACD, RSI), 산업 분석, 뉴스 분석을 종합하여 투자 판단을 제공합니다. Use when analyzing stocks, investment decisions, or financial research.
allowed-tools: Bash, Read, Write, WebSearch, WebFetch
argument-hint: <종목_티커> (예: AAPL, 005930.KS, TSLA)
---

# 📊 종합 주식 분석 커맨드

종목 티커: **$ARGUMENTS**

아래 분석 파이프라인을 **순서대로** 실행하고, 최종 결과를 마크다운 리포트로 `/output/stock-report-$ARGUMENTS.md`에 저장하세요.

---

## 🔧 Step 0: 환경 준비

```bash
pip install yfinance pandas numpy matplotlib mplfinance ta requests beautifulsoup4 --quiet
```

아래 Python 유틸리티 스크립트를 먼저 생성하세요:

**`stock_analyzer.py`** — 핵심 데이터 수집·계산 모듈

```python
import yfinance as yf
import pandas as pd
import numpy as np
from ta.trend import MACD, SMAIndicator, EMAIndicator
from ta.momentum import RSIIndicator
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

class StockAnalyzer:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.stock = yf.Ticker(ticker)
        self.info = self.stock.info
        self.today = datetime.today()

    # ── 1. 기본 정보 ──
    def get_basic_info(self) -> dict:
        i = self.info
        return {
            "종목명": i.get("longName") or i.get("shortName", "N/A"),
            "섹터": i.get("sector", "N/A"),
            "산업": i.get("industry", "N/A"),
            "시가총액": i.get("marketCap", "N/A"),
            "현재가": i.get("currentPrice") or i.get("regularMarketPrice", "N/A"),
            "52주_최고": i.get("fiftyTwoWeekHigh", "N/A"),
            "52주_최저": i.get("fiftyTwoWeekLow", "N/A"),
            "통화": i.get("currency", "N/A"),
            "거래소": i.get("exchange", "N/A"),
        }

    # ── 2. 재무 지표 (Valuation) ──
    def get_valuation_metrics(self) -> dict:
        i = self.info
        return {
            "PER(TTM)": i.get("trailingPE", "N/A"),
            "Forward_PER": i.get("forwardPE", "N/A"),
            "PBR": i.get("priceToBook", "N/A"),
            "PSR": i.get("priceToSalesTrailing12Months", "N/A"),
            "EV/EBITDA": i.get("enterpriseToEbitda", "N/A"),
            "배당수익률(%)": round(i.get("dividendYield", 0) * 100, 2) if i.get("dividendYield") else "N/A",
            "ROE(%)": round(i.get("returnOnEquity", 0) * 100, 2) if i.get("returnOnEquity") else "N/A",
            "ROA(%)": round(i.get("returnOnAssets", 0) * 100, 2) if i.get("returnOnAssets") else "N/A",
            "부채비율": i.get("debtToEquity", "N/A"),
            "유동비율": i.get("currentRatio", "N/A"),
            "영업이익률(%)": round(i.get("operatingMargins", 0) * 100, 2) if i.get("operatingMargins") else "N/A",
            "순이익률(%)": round(i.get("profitMargins", 0) * 100, 2) if i.get("profitMargins") else "N/A",
            "매출성장률(%)": round(i.get("revenueGrowth", 0) * 100, 2) if i.get("revenueGrowth") else "N/A",
            "EPS성장률(%)": round(i.get("earningsGrowth", 0) * 100, 2) if i.get("earningsGrowth") else "N/A",
        }

    # ── 3. 재무제표 (3개년) ──
    def get_financials(self) -> dict:
        result = {}

        # 손익계산서
        inc = self.stock.financials
        if inc is not None and not inc.empty:
            result["손익계산서"] = inc.to_dict()

        # 재무상태표
        bal = self.stock.balance_sheet
        if bal is not None and not bal.empty:
            result["재무상태표"] = bal.to_dict()

        # 현금흐름표
        cf = self.stock.cashflow
        if cf is not None and not cf.empty:
            result["현금흐름표"] = cf.to_dict()

        return result

    # ── 4. 기술적 분석 (6개월 일봉) ──
    def get_technical_analysis(self) -> dict:
        start = self.today - timedelta(days=250)
        df = self.stock.history(start=start, end=self.today)

        if df.empty:
            return {"error": "주가 데이터 없음"}

        close = df["Close"]

        # 이동평균선
        df["SMA_20"] = SMAIndicator(close, window=20).sma_indicator()
        df["SMA_60"] = SMAIndicator(close, window=60).sma_indicator()
        df["SMA_120"] = SMAIndicator(close, window=120).sma_indicator()

        # MACD
        macd_obj = MACD(close)
        df["MACD"] = macd_obj.macd()
        df["MACD_Signal"] = macd_obj.macd_signal()
        df["MACD_Hist"] = macd_obj.macd_diff()

        # RSI
        df["RSI_14"] = RSIIndicator(close, window=14).rsi()

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        # 골든크로스 / 데드크로스 판별
        golden_cross_20_60 = (prev["SMA_20"] <= prev["SMA_60"]) and (latest["SMA_20"] > latest["SMA_60"])
        dead_cross_20_60 = (prev["SMA_20"] >= prev["SMA_60"]) and (latest["SMA_20"] < latest["SMA_60"])

        # MACD 시그널
        macd_bullish = (prev["MACD"] <= prev["MACD_Signal"]) and (latest["MACD"] > latest["MACD_Signal"])
        macd_bearish = (prev["MACD"] >= prev["MACD_Signal"]) and (latest["MACD"] < latest["MACD_Signal"])

        return {
            "현재가": round(float(latest["Close"]), 2),
            "SMA_20": round(float(latest["SMA_20"]), 2) if pd.notna(latest["SMA_20"]) else "N/A",
            "SMA_60": round(float(latest["SMA_60"]), 2) if pd.notna(latest["SMA_60"]) else "N/A",
            "SMA_120": round(float(latest["SMA_120"]), 2) if pd.notna(latest["SMA_120"]) else "N/A",
            "MACD": round(float(latest["MACD"]), 4) if pd.notna(latest["MACD"]) else "N/A",
            "MACD_Signal": round(float(latest["MACD_Signal"]), 4) if pd.notna(latest["MACD_Signal"]) else "N/A",
            "MACD_Histogram": round(float(latest["MACD_Hist"]), 4) if pd.notna(latest["MACD_Hist"]) else "N/A",
            "RSI_14": round(float(latest["RSI_14"]), 2) if pd.notna(latest["RSI_14"]) else "N/A",
            "골든크로스_20_60": golden_cross_20_60,
            "데드크로스_20_60": dead_cross_20_60,
            "MACD_매수시그널": macd_bullish,
            "MACD_매도시그널": macd_bearish,
            "이격도_20": round(float(latest["Close"] / latest["SMA_20"] * 100), 2) if pd.notna(latest["SMA_20"]) else "N/A",
            "추세": "상승" if latest["Close"] > latest.get("SMA_60", latest["Close"]) else "하락",
        }

    # ── 5. 차트 생성 ──
    def generate_chart(self, output_path="chart.png"):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        start = self.today - timedelta(days=200)
        df = self.stock.history(start=start, end=self.today)
        if df.empty:
            return None

        close = df["Close"]
        df["SMA_20"] = SMAIndicator(close, window=20).sma_indicator()
        df["SMA_60"] = SMAIndicator(close, window=60).sma_indicator()
        df["SMA_120"] = SMAIndicator(close, window=120).sma_indicator()

        macd_obj = MACD(close)
        df["MACD"] = macd_obj.macd()
        df["MACD_Signal"] = macd_obj.macd_signal()
        df["MACD_Hist"] = macd_obj.macd_diff()
        df["RSI_14"] = RSIIndicator(close, window=14).rsi()

        fig, axes = plt.subplots(3, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [3, 1, 1]})
        fig.suptitle(f"{self.ticker} — Technical Analysis", fontsize=16, fontweight="bold")

        # 가격 + 이동평균선
        ax1 = axes[0]
        ax1.plot(df.index, df["Close"], label="Close", color="#1a1a2e", linewidth=1.5)
        ax1.plot(df.index, df["SMA_20"], label="SMA 20", color="#e94560", linewidth=1, linestyle="--")
        ax1.plot(df.index, df["SMA_60"], label="SMA 60", color="#0f3460", linewidth=1, linestyle="--")
        ax1.plot(df.index, df["SMA_120"], label="SMA 120", color="#16213e", linewidth=1, linestyle=":")
        ax1.fill_between(df.index, df["Close"], alpha=0.05, color="#1a1a2e")
        ax1.set_ylabel("Price")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.3)

        # MACD
        ax2 = axes[1]
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"].fillna(0)]
        ax2.bar(df.index, df["MACD_Hist"], color=colors, alpha=0.6, width=1)
        ax2.plot(df.index, df["MACD"], label="MACD", color="#2196f3", linewidth=1)
        ax2.plot(df.index, df["MACD_Signal"], label="Signal", color="#ff9800", linewidth=1)
        ax2.set_ylabel("MACD")
        ax2.legend(loc="upper left", fontsize=9)
        ax2.grid(True, alpha=0.3)

        # RSI
        ax3 = axes[2]
        ax3.plot(df.index, df["RSI_14"], color="#7b1fa2", linewidth=1.2)
        ax3.axhline(70, color="#ef5350", linestyle="--", alpha=0.5)
        ax3.axhline(30, color="#26a69a", linestyle="--", alpha=0.5)
        ax3.fill_between(df.index, 70, 100, alpha=0.05, color="#ef5350")
        ax3.fill_between(df.index, 0, 30, alpha=0.05, color="#26a69a")
        ax3.set_ylabel("RSI (14)")
        ax3.set_ylim(0, 100)
        ax3.grid(True, alpha=0.3)

        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            ax.xaxis.set_major_locator(mdates.MonthLocator())

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        return output_path

    # ── 6. 실적 데이터 ──
    def get_earnings(self) -> dict:
        try:
            earnings_dates = self.stock.earnings_dates
            if earnings_dates is not None and not earnings_dates.empty:
                recent = earnings_dates.head(8)
                return {"최근_실적": recent.to_dict()}
        except:
            pass

        try:
            quarterly = self.stock.quarterly_earnings
            if quarterly is not None and not quarterly.empty:
                return {"분기실적": quarterly.to_dict()}
        except:
            pass

        return {"실적데이터": "조회 불가"}

    # ── 7. 애널리스트 의견 ──
    def get_analyst_info(self) -> dict:
        i = self.info
        return {
            "목표가_평균": i.get("targetMeanPrice", "N/A"),
            "목표가_최고": i.get("targetHighPrice", "N/A"),
            "목표가_최저": i.get("targetLowPrice", "N/A"),
            "추천의견": i.get("recommendationKey", "N/A"),
            "추천의견_수": i.get("numberOfAnalystOpinions", "N/A"),
        }


# ── 실행 ──
if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

    analyzer = StockAnalyzer(ticker)

    print("=" * 60)
    print(f"📊 {ticker} 종합 분석 데이터")
    print("=" * 60)

    print("\n[1] 기본 정보")
    for k, v in analyzer.get_basic_info().items():
        print(f"  {k}: {v}")

    print("\n[2] 밸류에이션 & 재무 지표")
    for k, v in analyzer.get_valuation_metrics().items():
        print(f"  {k}: {v}")

    print("\n[3] 기술적 분석")
    ta = analyzer.get_technical_analysis()
    for k, v in ta.items():
        print(f"  {k}: {v}")

    print("\n[4] 애널리스트 의견")
    for k, v in analyzer.get_analyst_info().items():
        print(f"  {k}: {v}")

    print("\n[5] 실적 데이터")
    earnings = analyzer.get_earnings()
    print(f"  {json.dumps(earnings, indent=2, default=str)}")

    print("\n[6] 차트 생성 중...")
    chart_path = analyzer.generate_chart(f"chart_{ticker}.png")
    print(f"  차트 저장 완료: {chart_path}")

    print("\n[7] 재무제표 (3개년) 요약")
    fins = analyzer.get_financials()
    for sheet_name, data in fins.items():
        print(f"\n  --- {sheet_name} ---")
        df = pd.DataFrame(data)
        print(df.to_string()[:2000])
```

---

## 📋 분석 파이프라인

### Phase 1: 데이터 수집 (자동)

1. **`stock_analyzer.py`를 생성**하고 위 코드를 저장
2. `python stock_analyzer.py $ARGUMENTS` 실행하여 전체 데이터 수집
3. 차트 PNG 파일 생성 확인

### Phase 2: 웹 리서치 (WebSearch 활용)

아래 항목을 **각각 검색**하여 최신 정보 수집:

1. **`$ARGUMENTS stock news latest 2025`** — 최신 뉴스·이슈
2. **`$ARGUMENTS earnings results quarterly`** — 최근 분기 실적 발표 내용
3. **`$ARGUMENTS stock analyst rating forecast`** — 애널리스트 전망
4. **`$ARGUMENTS industry outlook trend`** — 산업 동향·전망
5. **`$ARGUMENTS competitor comparison market share`** — 경쟁사 비교

한국 종목(`.KS`, `.KQ`)인 경우 추가로:
- **`$ARGUMENTS 주가 전망 2025`**
- **`$ARGUMENTS 실적 분석`**

### Phase 3: 종합 분석 리포트 작성

수집된 모든 데이터를 아래 구조로 **마크다운 리포트**를 작성하세요:

```markdown
# 📊 $ARGUMENTS 종합 주식 분석 리포트

> 분석일: [오늘 날짜] | 분석 모델: Claude

---

## 1. 종목 개요
- 종목명, 섹터, 시가총액, 현재가, 52주 범위

## 2. 핵심 투자 지표 (Valuation)
| 지표 | 값 | 업종 평균 대비 |
|------|---|--------------|
| PER | ... | ... |
| PBR | ... | ... |
| ROE | ... | ... |
| ... | ... | ... |
- 밸류에이션 판단: 고평가/적정/저평가

## 3. 재무제표 분석 (3개년)

### 3-1. 수익성 분석
- 매출액, 영업이익, 순이익 추이
- 영업이익률, 순이익률 변화

### 3-2. 안정성 분석
- 부채비율, 유동비율, 이자보상배율
- 재무 건전성 판단

### 3-3. 성장성 분석
- 매출 성장률, EPS 성장률
- 잉여현금흐름(FCF) 추이

## 4. 기술적 분석 (6개월 일봉)

### 4-1. 이동평균선 분석
- SMA 20/60/120일 배열 상태
- 골든크로스/데드크로스 여부
- 지지선/저항선

### 4-2. MACD 분석
- MACD 라인 vs 시그널 라인
- 히스토그램 방향
- 매수/매도 시그널 판별

### 4-3. RSI 분석
- 현재 RSI 값 (과매수 >70 / 과매도 <30)
- 다이버전스 여부

### 4-4. 종합 기술적 판단
- ✅ 매수 시그널 / ⚠️ 중립 / 🔴 매도 시그널

## 5. 최근 실적 분석
- 최근 분기 실적 요약
- 시장 예상치(컨센서스) 대비 서프라이즈/미스
- 가이던스 및 향후 전망

## 6. 산업 분석 & 경쟁 환경
- 산업 글로벌 동향
- 주요 경쟁사 비교 (시총, PER, 성장률)
- 미·중 정책 영향 (반도체 관련 시)
- AI 수요와의 관련성

## 7. 뉴스 & 시장 센티먼트
- 최근 주요 뉴스 요약 (3~5건)
- 시장 심리 분석

## 8. 리스크 요인
- 거시경제 리스크 (금리, 환율, 지정학)
- 기업 고유 리스크
- 산업 리스크
- 규제 리스크

## 9. 향후 6개월 주가 영향 요인
- 상방 요인 (Catalyst)
- 하방 요인 (Risk)
- 주요 일정 (실적 발표, 배당, 이벤트)

## 10. 투자 판단 종합

### 🎯 종합 점수 (100점 만점)
| 항목 | 점수 | 비중 | 가중점수 |
|------|------|------|---------|
| 기본적 분석 (재무·실적) | /40 | 40% | ... |
| 기술적 분석 (차트) | /25 | 25% | ... |
| 산업·경쟁력 | /20 | 20% | ... |
| 시장 센티먼트·뉴스 | /15 | 15% | ... |
| **종합** | **/100** | | **...** |

### 📌 투자 의견
- **단기(1~3개월)**: 매수 / 보유 / 매도
- **중기(6개월)**: 매수 / 보유 / 매도
- **장기(1년+)**: 매수 / 보유 / 매도

### ⚠️ 면책 조항
> 본 분석은 AI 기반 자동 분석으로, 투자 권유가 아닙니다.
> 투자 판단은 본인 책임이며, 전문 투자자문을 권장합니다.
```

### Phase 4: 결과물 저장

1. 리포트를 `output/stock-report-$ARGUMENTS.md`에 저장
2. 차트 이미지를 `output/chart_$ARGUMENTS.png`에 저장
3. 저장 경로를 사용자에게 알려주세요

---

## ⚠️ 주의사항

- 한국 종목은 티커 뒤에 `.KS`(코스피) 또는 `.KQ`(코스닥)를 붙여야 합니다
  - 예: 삼성전자 → `005930.KS`, 카카오 → `035720.KS`
- 데이터 조회 실패 시 해당 섹션을 "데이터 미제공"으로 표기
- **투자 판단은 반드시 면책 조항을 포함**할 것
- yfinance 데이터가 불완전할 수 있으므로 웹 검색으로 보완할 것
