"""
Stock Analyzer — Streamlit Web App
검색 → 종목 선택 → 보고서 발급
"""

import sys, warnings, json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf

warnings.filterwarnings("ignore")

# ── 경로 설정 ──────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(BASE_DIR))

# ── StockAnalyzer + 리포트 생성기 import ────────
try:
    from stock_analyzer import StockAnalyzer
    from report_generator import fetch_all_data, generate_full_report
    ANALYZER_OK = True
except Exception as e:
    ANALYZER_OK = False
    IMPORT_ERROR = str(e)

# ══════════════════════════════════════════════
#  페이지 설정 & CSS
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="Stock Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* 검색 결과 카드 */
.stock-card {
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 14px 18px;
    background: #ffffff;
    margin-bottom: 4px;
    transition: box-shadow .15s;
}
.stock-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.08); }
.stock-ticker { font-size: 1.05rem; font-weight: 700; color: #1d4ed8; }
.stock-name   { font-size: 0.95rem; font-weight: 500; color: #1e293b; }
.stock-meta   { font-size: 0.78rem; color: #64748b; margin-top: 2px; }

/* 퀵 버튼 */
div[data-testid="stButton"] > button {
    border-radius: 8px;
}
/* 보고서 발급 버튼 강조 */
.report-btn > div[data-testid="stButton"] > button {
    background-color: #1d4ed8;
    color: white;
    font-weight: 600;
    border: none;
}
.report-btn > div[data-testid="stButton"] > button:hover {
    background-color: #1e40af;
}

/* KPI 카드 배경 */
div[data-testid="metric-container"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 10px 16px;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
#  Session State 초기화
# ══════════════════════════════════════════════
def init_state():
    defaults = {
        "page":           "home",   # "home" | "analyze" | "briefing"
        "search_query":   "",
        "search_results": [],
        "sel_ticker":     "",
        "sel_info":       {},
        "analysis":       None,     # 분석 결과 dict
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ══════════════════════════════════════════════
#  유틸 함수
# ══════════════════════════════════════════════
POPULAR = [
    ("AAPL", "Apple"),
    ("NVDA", "NVIDIA"),
    ("KLAC", "KLA Corp"),
    ("TSLA", "Tesla"),
    ("MSFT", "Microsoft"),
    ("005930.KS", "삼성전자"),
    ("000660.KS", "SK하이닉스"),
    ("247540.KQ", "에코프로비엠"),
]

def do_search(query: str) -> list:
    """Yahoo Finance 검색 → EQUITY만 필터링"""
    try:
        results = yf.Search(query, max_results=12).quotes
        return [r for r in results if r.get("quoteType") == "EQUITY"]
    except Exception as e:
        st.error(f"검색 오류: {e}")
        return []

def fmt(v, suffix=""):
    if v in ("N/A", None, ""):
        return "N/A"
    if isinstance(v, float):
        return f"{v:,.2f}{suffix}"
    if isinstance(v, int) and abs(v) > 1_000_000:
        b = v / 1e9
        return f"${b:.1f}B" if b >= 1 else f"${v/1e6:.0f}M"
    return f"{v}{suffix}"

def build_plotly_chart(ticker: str):
    from ta.trend import MACD, SMAIndicator
    from ta.momentum import RSIIndicator
    today = datetime.today()
    df = yf.Ticker(ticker).history(start=today - timedelta(days=220), end=today)
    if df.empty:
        return None
    close = df["Close"]
    df["SMA20"]   = SMAIndicator(close, window=20).sma_indicator()
    df["SMA60"]   = SMAIndicator(close, window=60).sma_indicator()
    df["SMA120"]  = SMAIndicator(close, window=120).sma_indicator()
    m = MACD(close)
    df["MACD"]    = m.macd()
    df["Signal"]  = m.macd_signal()
    df["Hist"]    = m.macd_diff()
    from ta.momentum import RSIIndicator
    df["RSI"]     = RSIIndicator(close, window=14).rsi()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.58, 0.21, 0.21],
        vertical_spacing=0.035,
        subplot_titles=("가격 & 이동평균선", "MACD", "RSI (14)"),
    )
    fig.add_trace(go.Scatter(x=df.index, y=df["Close"],  name="Close",   line=dict(color="#2563eb", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA20"],  name="SMA 20",  line=dict(color="#f59e0b", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA60"],  name="SMA 60",  line=dict(color="#10b981", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA120"], name="SMA 120", line=dict(color="#ef4444", width=1,   dash="dash")), row=1, col=1)

    hist_colors = ["#10b981" if v >= 0 else "#ef4444" for v in df["Hist"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=df["Hist"], name="Histogram", marker_color=hist_colors, opacity=0.5), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"],   name="MACD",   line=dict(color="#3b82f6", width=1.2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["Signal"], name="Signal", line=dict(color="#f97316", width=1.2)), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="#8b5cf6", width=1.5), showlegend=False), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",   opacity=0.4, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.4, row=3, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="red",   opacity=0.03, row=3, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="green", opacity=0.03, row=3, col=1)

    fig.update_layout(
        height=680, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=8, r=8, t=55, b=8),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    return fig

def generate_report(ticker, basic, val, tech, analyst) -> str:
    today = datetime.today().strftime("%Y-%m-%d")
    rsi   = tech.get("RSI_14", "N/A")
    rsi_label = ("과매수 ⚠️" if isinstance(rsi, float) and rsi > 70
                 else "과매도 🟢" if isinstance(rsi, float) and rsi < 30
                 else "중립 ✅")
    trend  = "✅ 상승" if tech.get("추세") == "상승" else "🔴 하락"
    macd_s = ("✅ 매수 시그널" if tech.get("MACD_매수시그널")
              else "🔴 매도 시그널" if tech.get("MACD_매도시그널") else "➖ 중립")
    target = analyst.get("목표가_평균", "N/A")
    price  = basic.get("현재가", "N/A")
    updown = ""
    if isinstance(target, float) and isinstance(price, float) and price > 0:
        updown = f" ({(target-price)/price*100:+.1f}% 현재가 대비)"

    return f"""# 📊 {basic.get('종목명', ticker)} ({ticker}) 종합 분석 리포트

> 분석일: {today} | 도구: Stock Analyzer (yfinance)

---

## 1. 종목 개요

| 항목 | 내용 |
|------|------|
| 종목명 | {basic.get('종목명','N/A')} |
| 섹터 | {basic.get('섹터','N/A')} |
| 산업 | {basic.get('산업','N/A')} |
| 시가총액 | {fmt(basic.get('시가총액'))} |
| 현재가 | {basic.get('통화','USD')} {fmt(price)} |
| 52주 최고 | {fmt(basic.get('52주_최고'))} |
| 52주 최저 | {fmt(basic.get('52주_최저'))} |

---

## 2. 핵심 투자 지표

| 지표 | 값 | 지표 | 값 |
|------|---|------|---|
| PER (TTM) | {fmt(val.get('PER(TTM)'))}x | Forward PER | {fmt(val.get('Forward_PER'))}x |
| PBR | {fmt(val.get('PBR'))}x | PSR | {fmt(val.get('PSR'))}x |
| EV/EBITDA | {fmt(val.get('EV/EBITDA'))}x | 배당수익률 | {fmt(val.get('배당수익률(%)'))}% |
| ROE | {fmt(val.get('ROE(%)'))}% | ROA | {fmt(val.get('ROA(%)'))}% |
| 영업이익률 | {fmt(val.get('영업이익률(%)'))}% | 순이익률 | {fmt(val.get('순이익률(%)'))}% |
| 매출성장률 | {fmt(val.get('매출성장률(%)'))}% | EPS성장률 | {fmt(val.get('EPS성장률(%)'))}% |
| 부채비율 | {fmt(val.get('부채비율'))} | 유동비율 | {fmt(val.get('유동비율'))}x |

---

## 3. 기술적 분석

| 항목 | 값 | 항목 | 값 |
|------|---|------|---|
| 현재가 | {fmt(tech.get('현재가'))} | 추세 | {trend} |
| SMA 20일 | {fmt(tech.get('SMA_20'))} | 이격도 (SMA20) | {fmt(tech.get('이격도_20'))}% |
| SMA 60일 | {fmt(tech.get('SMA_60'))} | MACD | {fmt(tech.get('MACD'))} |
| SMA 120일 | {fmt(tech.get('SMA_120'))} | MACD Signal | {fmt(tech.get('MACD_Signal'))} |
| RSI (14) | {fmt(rsi)} — {rsi_label} | MACD 시그널 | {macd_s} |
| 골든크로스 | {'✅ 발생' if tech.get('골든크로스_20_60') else '—'} | 데드크로스 | {'🔴 발생' if tech.get('데드크로스_20_60') else '—'} |

---

## 4. 애널리스트 의견

| 항목 | 값 |
|------|---|
| 추천 의견 | **{str(analyst.get('추천의견','N/A')).upper()}** |
| 참여 애널리스트 수 | {analyst.get('추천의견_수','N/A')}명 |
| 평균 목표가 | {fmt(target)}{updown} |
| 최고 목표가 | {fmt(analyst.get('목표가_최고'))} |
| 최저 목표가 | {fmt(analyst.get('목표가_최저'))} |

---

## 5. 시그널 종합

| 시그널 | 상태 |
|--------|------|
| 이동평균 배열 | {trend} |
| MACD | {macd_s} |
| RSI | {rsi_label} ({fmt(rsi)}) |
| 골든크로스 | {'✅ 발생' if tech.get('골든크로스_20_60') else '미발생'} |

---

> ⚠️ **면책 조항:** 본 분석은 공개 데이터(yfinance) 기반 자동 분석으로 투자 권유가 아닙니다.
> 모든 투자 판단과 손익은 투자자 본인의 책임입니다.
"""

# ── yfinance 레이트 리밋 방지: 30분 캐시 ─────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_yf_fetch(ticker: str) -> dict:
    """yfinance 전체 데이터를 한 번만 수집 후 30분 캐시 (레이트 리밋 방지)"""
    import time
    last_err = None
    for attempt in range(3):
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info
            # info가 비어 있거나 quoteType이 없으면 유효하지 않은 티커
            if not info or not info.get("symbol"):
                raise ValueError(f"'{ticker}' 종목 정보를 가져올 수 없습니다. 티커를 확인하세요.")
            return {"ok": True, "info": info}
        except Exception as e:
            last_err = e
            msg = str(e)
            if "Too Many Requests" in msg or "Rate" in msg or "429" in msg:
                wait = (attempt + 1) * 5   # 5s → 10s → 15s
                time.sleep(wait)
                continue
            raise   # 다른 오류는 즉시 상위로
    raise RuntimeError(
        f"Yahoo Finance 레이트 리밋 초과 (3회 재시도 실패). "
        f"약 1분 후 다시 시도해주세요. 원인: {last_err}"
    )

def run_analysis(ticker: str) -> dict:
    import time

    # ── 캐시에서 yfinance info 가져오기 (레이트 리밋 방지) ──────────
    _cached_yf_fetch(ticker)   # 유효성 검증 + 캐시 워밍업

    # Phase 1: StockAnalyzer — 기술적 분석
    analyzer = StockAnalyzer(ticker)
    basic    = analyzer.get_basic_info()
    val      = analyzer.get_valuation_metrics()
    tech     = analyzer.get_technical_analysis()
    analyst  = analyzer.get_analyst_info()
    earnings = analyzer.get_earnings()

    # Phase 2: 전체 데이터 수집 (재무제표, 뉴스, 실적)
    data = fetch_all_data(ticker)

    # Phase 3: Plotly 차트 생성
    fig = build_plotly_chart(ticker)

    # Phase 4: 10섹션 풀 리포트 생성
    report = generate_full_report(ticker, tech, data)

    # 파일 저장
    (OUTPUT_DIR / f"stock-report-{ticker}.md").write_text(report, encoding="utf-8")
    return dict(basic=basic, val=val, tech=tech, analyst=analyst,
                earnings=earnings, fig=fig, report=report)


# ══════════════════════════════════════════════
#  사이드바 — 최근 리포트
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📁 최근 리포트")
    reports = sorted(OUTPUT_DIR.glob("stock-report-*.md"), reverse=True)
    if not reports:
        st.caption("아직 발급된 리포트가 없습니다.")
    for rpt in reports[:10]:
        ticker_name = rpt.stem.replace("stock-report-", "")
        mtime = datetime.fromtimestamp(rpt.stat().st_mtime).strftime("%m/%d %H:%M")
        col_a, col_b = st.columns([2, 1])
        with col_a:
            if st.button(f"**{ticker_name}**\n{mtime}", key=f"hist_{ticker_name}", use_container_width=True):
                st.session_state.page      = "analyze"
                st.session_state.sel_ticker = ticker_name
                content = rpt.read_text(encoding="utf-8")
                st.session_state.analysis  = {"report": content, "fig": build_plotly_chart(ticker_name),
                                              "basic":{}, "val":{}, "tech":{}, "analyst":{}}
                st.rerun()
        with col_b:
            st.download_button("↓", data=rpt.read_bytes(), file_name=rpt.name,
                               mime="text/markdown", key=f"dl_{ticker_name}", use_container_width=True)
    if st.session_state.page in ("analyze", "briefing"):
        st.markdown("---")
        if st.button("🔍 검색으로 돌아가기", use_container_width=True):
            st.session_state.page     = "home"
            st.session_state.analysis = None
            st.rerun()
        if st.session_state.page == "briefing":
            if st.button("← 보고서로 돌아가기", use_container_width=True):
                st.session_state.page = "analyze"
                st.rerun()


# ══════════════════════════════════════════════
#  HOME PAGE — 검색 & 결과
# ══════════════════════════════════════════════
if st.session_state.page == "home":

    # ── 헤더
    st.markdown("## 📊 Stock Analyzer")
    st.markdown("기업명 또는 티커를 검색해 보고서를 발급하세요.")
    st.markdown("---")

    # ── 검색 바
    search_col, btn_col = st.columns([5, 1])
    with search_col:
        query = st.text_input(
            "검색",
            value=st.session_state.search_query,
            placeholder="기업명 또는 티커 입력 — Apple, KLAC, 삼성, 005930.KS …",
            label_visibility="collapsed",
        )
    with btn_col:
        search_clicked = st.button("🔍 검색", type="primary", use_container_width=True)

    # 검색 실행
    if search_clicked and query.strip():
        st.session_state.search_query   = query.strip()
        st.session_state.search_results = do_search(query.strip())

    # ── 인기 종목 바로가기
    st.markdown("**⚡ 인기 종목**")
    pop_cols = st.columns(len(POPULAR))
    for i, (tk, label) in enumerate(POPULAR):
        with pop_cols[i]:
            if st.button(f"{tk}\n{label}", key=f"pop_{tk}", use_container_width=True):
                st.session_state.search_query   = tk
                st.session_state.search_results = do_search(tk)

    # ── 검색 결과 카드
    results = st.session_state.search_results
    if results:
        st.markdown("---")
        st.markdown(f"**검색 결과** {len(results)}건")

        # 2열 그리드
        for row_start in range(0, len(results), 2):
            row_results = results[row_start:row_start+2]
            cols = st.columns(2)
            for col, r in zip(cols, row_results):
                with col:
                    ticker  = r.get("symbol", "")
                    name    = r.get("longname") or r.get("shortname", "—")
                    exch    = r.get("exchDisp", r.get("exchange", ""))
                    sector  = r.get("sectorDisp", "")
                    industry = r.get("industryDisp", "")
                    meta    = " · ".join(filter(None, [exch, sector, industry]))

                    with st.container(border=True):
                        info_col, btn_col2 = st.columns([3, 1.4])
                        with info_col:
                            st.markdown(
                                f'<span class="stock-ticker">{ticker}</span> '
                                f'<span class="stock-name">&nbsp;{name}</span><br>'
                                f'<span class="stock-meta">{meta}</span>',
                                unsafe_allow_html=True,
                            )
                        with btn_col2:
                            if st.button("📊 보고서 발급", key=f"issue_{ticker}",
                                         type="primary", use_container_width=True):
                                st.session_state.page       = "analyze"
                                st.session_state.sel_ticker = ticker
                                st.session_state.sel_info   = r
                                st.session_state.analysis   = None   # 새로 분석
                                st.rerun()

    elif st.session_state.search_query and not results:
        st.info("검색 결과가 없습니다. 다른 키워드나 정확한 티커를 입력해보세요.")

    else:
        # 빈 홈 화면 안내
        st.markdown("""
---
| 종류 | 입력 예 |
|------|--------|
| 미국 주식 | `Apple`, `KLAC`, `NVIDIA`, `TSLA` |
| 코스피 | `삼성전자`, `005930.KS`, `SK hynix` |
| 코스닥 | `에코프로`, `247540.KQ` |
        """)


# ══════════════════════════════════════════════
#  ANALYZE PAGE — 분석 결과
# ══════════════════════════════════════════════
elif st.session_state.page == "analyze":
    ticker = st.session_state.sel_ticker

    if not ANALYZER_OK:
        st.error(f"분석 모듈 로드 실패: {IMPORT_ERROR}")
        st.stop()

    # 분석이 아직 안 된 경우 실행
    if st.session_state.analysis is None:
        progress = st.progress(0, text=f"📡 {ticker} 기본 정보 수집 중…")
        status   = st.empty()
        steps = [
            (10,  "📊 기본 정보 & 재무 지표 수집…"),
            (25,  "📈 기술적 분석 (SMA/MACD/RSI) 계산…"),
            (40,  "🗂 재무제표 3개년 데이터 수집…"),
            (55,  "📰 최신 뉴스 & 실적 데이터 조회…"),
            (70,  "🔍 애널리스트 의견 & 목표가 수집…"),
            (85,  "📊 인터랙티브 차트 생성…"),
            (95,  "📝 10섹션 종합 리포트 작성…"),
        ]
        try:
            for pct, msg in steps:
                progress.progress(pct, text=msg)
                status.caption(msg)
            result = run_analysis(ticker)
            progress.progress(100, text="✅ 분석 완료!")
            status.empty()
            progress.empty()
            st.session_state.analysis = result
        except Exception as e:
            progress.empty()
            status.empty()
            st.error(f"분석 실패: {e}")
            if st.button("← 검색으로 돌아가기"):
                st.session_state.page = "home"
                st.rerun()
            st.stop()   # 분석 실패 시 이후 코드 실행 방지

    if st.session_state.analysis is None:
        st.stop()

    data    = st.session_state.analysis
    basic   = data.get("basic", {})
    val     = data.get("val", {})
    tech    = data.get("tech", {})
    analyst = data.get("analyst", {})
    fig     = data.get("fig")
    report  = data.get("report", "")

    # ── 헤더
    company = basic.get("종목명") or ticker
    price   = basic.get("현재가", "N/A")
    sector  = basic.get("섹터", "")

    header_col, back_col = st.columns([5, 1])
    with header_col:
        st.markdown(f"## {company}  `{ticker}`")
        if sector:
            st.caption(f"{sector} · {basic.get('산업','')} · {basic.get('거래소','')} · {datetime.today().strftime('%Y-%m-%d')}")
    with back_col:
        if st.button("← 검색", use_container_width=True):
            st.session_state.page     = "home"
            st.session_state.analysis = None
            st.rerun()

    # ── KPI 카드
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    def kpi(col, label, raw, suffix=""):
        v = fmt(raw, suffix) if raw not in ("N/A", None) else "N/A"
        col.metric(label, v)
    kpi(k1, "현재가",    price)
    kpi(k2, "PER(TTM)", val.get("PER(TTM)"),    "x")
    kpi(k3, "ROE",       val.get("ROE(%)"),      "%")
    kpi(k4, "영업이익률", val.get("영업이익률(%)"), "%")
    kpi(k5, "RSI (14)",  tech.get("RSI_14"))

    target = analyst.get("목표가_평균", "N/A")
    if isinstance(target, float) and isinstance(price, float) and price > 0:
        delta = f"{(target-price)/price*100:+.1f}%"
        k6.metric("목표가 (평균)", f"${target:,.0f}", delta=delta)
    else:
        kpi(k6, "목표가 (평균)", target)

    st.markdown("---")

    # ── 탭
    tab_chart, tab_report, tab_raw = st.tabs(["📈 차트", "📄 리포트", "📋 원시 지표"])

    with tab_chart:
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("차트 데이터를 불러올 수 없습니다.")

    with tab_report:
        dl_col, brief_col, _ = st.columns([1.2, 1.6, 3.2])
        with dl_col:
            st.download_button(
                "📥 MD 다운로드", data=report.encode("utf-8"),
                file_name=f"stock-report-{ticker}.md", mime="text/markdown",
                use_container_width=True,
            )
        with brief_col:
            if st.button("🔮 브리핑 시뮬레이터", key="go_briefing",
                         use_container_width=True, type="primary"):
                st.session_state.page = "briefing"
                st.rerun()
        st.markdown(report)

    with tab_raw:
        c1, c2 = st.columns(2)
        with c1:
            if basic:
                st.subheader("기본 정보")
                st.dataframe(pd.DataFrame(basic.items(), columns=["항목","값"]).set_index("항목"), use_container_width=True)
            if analyst:
                st.subheader("애널리스트 의견")
                st.dataframe(pd.DataFrame(analyst.items(), columns=["항목","값"]).set_index("항목"), use_container_width=True)
        with c2:
            if val:
                st.subheader("재무 지표")
                st.dataframe(pd.DataFrame(val.items(), columns=["항목","값"]).set_index("항목"), use_container_width=True)
            if tech:
                st.subheader("기술적 분석")
                st.dataframe(pd.DataFrame(tech.items(), columns=["항목","값"]).set_index("항목"), use_container_width=True)

    st.success(f"✅ 리포트 저장 완료: `output/stock-report-{ticker}.md`")


# ══════════════════════════════════════════════
#  BRIEFING PAGE — 브리핑 시뮬레이터
# ══════════════════════════════════════════════
elif st.session_state.page == "briefing":
    import streamlit.components.v1 as components

    ticker  = st.session_state.sel_ticker
    report  = ""
    if st.session_state.analysis:
        report = st.session_state.analysis.get("report", "")

    # briefing/index.html 읽기
    briefing_html_path = BASE_DIR / "briefing" / "index.html"
    if not briefing_html_path.exists():
        st.error("briefing/index.html 파일을 찾을 수 없습니다.")
        st.stop()

    html = briefing_html_path.read_text(encoding="utf-8")

    # MD 콘텐츠와 파일명을 JS 변수로 안전하게 주입 (JSON 인코딩으로 이스케이프)
    report_json   = json.dumps(report)
    filename_json = json.dumps(f"stock-report-{ticker}.md")
    inject = (
        f"window.preloadedMdContent = {report_json};\n"
        f"window.preloadedFilename  = {filename_json};"
    )
    html = html.replace("// __PRELOADED_CONTENT__", inject)

    # 헤더
    company = ""
    if st.session_state.analysis:
        company = st.session_state.analysis.get("basic", {}).get("종목명", ticker)

    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown(f"## 🔮 브리핑 시뮬레이터  `{ticker}`")
        if company and company != ticker:
            st.caption(f"{company} · AI 기반 실전 대응 전략 생성기")
    with bcol:
        if st.button("← 보고서", use_container_width=True):
            st.session_state.page = "analyze"
            st.rerun()

    st.info(
        "💡 **사용 방법:** 좌측 패널에서 Anthropic API 키 입력 → 평균 단가 입력 → "
        "원하는 시뮬레이션 옵션 선택 → **브리핑 생성** 클릭",
        icon="ℹ️",
    )

    # 브리핑 앱 임베드
    components.html(html, height=1100, scrolling=True)
