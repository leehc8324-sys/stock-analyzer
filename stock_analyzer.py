import yfinance as yf
import pandas as pd
import numpy as np
from ta.trend import MACD, SMAIndicator, EMAIndicator
from ta.momentum import RSIIndicator
from datetime import datetime, timedelta
import time, json
import warnings
warnings.filterwarnings('ignore')


def _yf_retry(fn, retries: int = 3, base_wait: float = 4.0):
    """Too Many Requests 에러 시 지수 백오프 재시도"""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            msg = str(e)
            if "Too Many Requests" in msg or "Rate" in msg or "429" in msg:
                if i < retries - 1:
                    time.sleep(base_wait * (i + 1))
                    continue
            raise
    raise RuntimeError(
        f"yfinance 레이트 리밋 초과 ({retries}회 재시도 실패). "
        f"잠시 후 다시 시도해주세요. 마지막 오류: {last}"
    )


class StockAnalyzer:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.stock  = yf.Ticker(ticker)
        self.info   = _yf_retry(lambda: self.stock.info)
        self.today  = datetime.today()

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

    def get_financials(self) -> dict:
        result = {}
        inc = self.stock.financials
        if inc is not None and not inc.empty:
            result["손익계산서"] = inc.to_dict()
        bal = self.stock.balance_sheet
        if bal is not None and not bal.empty:
            result["재무상태표"] = bal.to_dict()
        cf = self.stock.cashflow
        if cf is not None and not cf.empty:
            result["현금흐름표"] = cf.to_dict()
        return result

    def get_technical_analysis(self) -> dict:
        start = self.today - timedelta(days=250)
        df = self.stock.history(start=start, end=self.today)
        if df.empty:
            return {"error": "주가 데이터 없음"}
        close = df["Close"]
        df["SMA_20"] = SMAIndicator(close, window=20).sma_indicator()
        df["SMA_60"] = SMAIndicator(close, window=60).sma_indicator()
        df["SMA_120"] = SMAIndicator(close, window=120).sma_indicator()
        macd_obj = MACD(close)
        df["MACD"] = macd_obj.macd()
        df["MACD_Signal"] = macd_obj.macd_signal()
        df["MACD_Hist"] = macd_obj.macd_diff()
        df["RSI_14"] = RSIIndicator(close, window=14).rsi()
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        golden_cross_20_60 = (prev["SMA_20"] <= prev["SMA_60"]) and (latest["SMA_20"] > latest["SMA_60"])
        dead_cross_20_60 = (prev["SMA_20"] >= prev["SMA_60"]) and (latest["SMA_20"] < latest["SMA_60"])
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
        ax1 = axes[0]
        ax1.plot(df.index, df["Close"], label="Close", color="#1a1a2e", linewidth=1.5)
        ax1.plot(df.index, df["SMA_20"], label="SMA 20", color="#e94560", linewidth=1, linestyle="--")
        ax1.plot(df.index, df["SMA_60"], label="SMA 60", color="#0f3460", linewidth=1, linestyle="--")
        ax1.plot(df.index, df["SMA_120"], label="SMA 120", color="#16213e", linewidth=1, linestyle=":")
        ax1.fill_between(df.index, df["Close"], alpha=0.05, color="#1a1a2e")
        ax1.set_ylabel("Price")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.3)
        ax2 = axes[1]
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"].fillna(0)]
        ax2.bar(df.index, df["MACD_Hist"], color=colors, alpha=0.6, width=1)
        ax2.plot(df.index, df["MACD"], label="MACD", color="#2196f3", linewidth=1)
        ax2.plot(df.index, df["MACD_Signal"], label="Signal", color="#ff9800", linewidth=1)
        ax2.set_ylabel("MACD")
        ax2.legend(loc="upper left", fontsize=9)
        ax2.grid(True, alpha=0.3)
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

    def get_analyst_info(self) -> dict:
        i = self.info
        return {
            "목표가_평균": i.get("targetMeanPrice", "N/A"),
            "목표가_최고": i.get("targetHighPrice", "N/A"),
            "목표가_최저": i.get("targetLowPrice", "N/A"),
            "추천의견": i.get("recommendationKey", "N/A"),
            "추천의견_수": i.get("numberOfAnalystOpinions", "N/A"),
        }


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "DASH"

    analyzer = StockAnalyzer(ticker)

    print("=" * 60)
    print(f"📊 {ticker} 종합 분석 데이터")
    print("=" * 60)

    print("\n[1] 기본 정보")
    basic = analyzer.get_basic_info()
    for k, v in basic.items():
        print(f"  {k}: {v}")

    print("\n[2] 밸류에이션 & 재무 지표")
    val = analyzer.get_valuation_metrics()
    for k, v in val.items():
        print(f"  {k}: {v}")

    print("\n[3] 기술적 분석")
    ta = analyzer.get_technical_analysis()
    for k, v in ta.items():
        print(f"  {k}: {v}")

    print("\n[4] 애널리스트 의견")
    analyst = analyzer.get_analyst_info()
    for k, v in analyst.items():
        print(f"  {k}: {v}")

    print("\n[5] 실적 데이터")
    earnings = analyzer.get_earnings()
    print(f"  {json.dumps(earnings, indent=2, default=str)}")

    print("\n[6] 차트 생성 중...")
    import os
    os.makedirs("output", exist_ok=True)
    chart_path = analyzer.generate_chart(f"output/chart_{ticker}.png")
    print(f"  차트 저장 완료: {chart_path}")

    print("\n[7] 재무제표 (3개년) 요약")
    fins = analyzer.get_financials()
    for sheet_name, data in fins.items():
        print(f"\n  --- {sheet_name} ---")
        df = pd.DataFrame(data)
        print(df.to_string()[:2000])
