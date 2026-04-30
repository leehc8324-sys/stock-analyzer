"""
종합 주식 분석 리포트 생성기 (10섹션 풀 리포트)
yfinance 전체 데이터 기반 — 재무제표, 뉴스, 실적, 애널리스트 포함
뉴스: 미장 → yfinance content 구조, 국장(.KS/.KQ) → 네이버 금융 스크래핑
"""

import warnings, json, re, time
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
#  yfinance 재시도 래퍼 (레이트 리밋 대응)
# ──────────────────────────────────────────────
def _yf_retry(fn, retries: int = 3, base_wait: float = 4.0):
    """Too Many Requests 에러 발생 시 지수 백오프로 재시도"""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            msg = str(e)
            if "Too Many Requests" in msg or "Rate" in msg or "429" in msg:
                if i < retries - 1:
                    time.sleep(base_wait * (i + 1))   # 4s → 8s → 12s
                    continue
            raise   # 다른 에러는 즉시 전파
    raise RuntimeError(
        f"yfinance 레이트 리밋 초과 ({retries}회 재시도 실패). "
        f"잠시 후 다시 시도해주세요. 마지막 오류: {last}"
    )

# ──────────────────────────────────────────────
#  티커 타입 감지
# ──────────────────────────────────────────────
def is_korean_ticker(ticker: str) -> bool:
    """코스피(.KS) / 코스닥(.KQ) 여부"""
    return ticker.upper().endswith(".KS") or ticker.upper().endswith(".KQ")

def get_kr_code(ticker: str) -> str:
    """'005930.KS' → '005930'"""
    return ticker.split(".")[0]


# ──────────────────────────────────────────────
#  뉴스 수집 — 미장 (yfinance 새 구조)
# ──────────────────────────────────────────────
def _fetch_us_news(stock) -> list:
    """yfinance 0.2.x 이후 news 구조(content dict) 파싱 → 통합 포맷"""
    raw = []
    try:
        raw = stock.news or []
    except Exception:
        return []

    result = []
    for item in raw[:10]:
        try:
            # 신 구조: {"id": ..., "content": {...}}
            if "content" in item and isinstance(item["content"], dict):
                c       = item["content"]
                title   = c.get("title", "")
                summary = c.get("summary", c.get("description", ""))
                pub     = (c.get("provider") or {}).get("displayName", "")
                raw_url = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {})
                url     = raw_url.get("url", "#") if isinstance(raw_url, dict) else str(raw_url)
                # pubDate: "2026-03-22T11:06:12Z"
                pd_str  = c.get("pubDate", c.get("displayTime", ""))
                try:
                    date_str = pd_str[:10] if pd_str else ""
                except Exception:
                    date_str = ""
            else:
                # 구 구조 호환
                title   = item.get("title", "")
                summary = item.get("summary", "")
                pub     = item.get("publisher", "")
                url     = item.get("link", item.get("url", "#"))
                ts      = item.get("providerPublishTime", 0)
                try:
                    date_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d") if ts else ""
                except Exception:
                    date_str = ""

            if title:
                result.append(dict(title=title, publisher=pub,
                                   date=date_str, url=url, summary=summary,
                                   source="yfinance"))
        except Exception:
            continue
    return result


# ──────────────────────────────────────────────
#  뉴스 수집 — 국장 (네이버 금융 스크래핑)
# ──────────────────────────────────────────────
def _fetch_kr_news(ticker: str) -> list:
    """네이버 금융 종목 뉴스 스크래핑 → 통합 포맷"""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    code = get_kr_code(ticker)
    url  = f"https://finance.naver.com/item/news_news.nhn?code={code}&page=1"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://finance.naver.com/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=8)
        r.encoding = "euc-kr"
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    result = []
    for row in soup.select("table.type5 tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue
        a = tds[0].find("a")
        if not a:
            continue
        title   = a.get_text(strip=True)
        pub     = tds[1].get_text(strip=True)
        date    = tds[2].get_text(strip=True)          # "2026.03.18 15:09"
        href    = a.get("href", "")
        full_url = "https://finance.naver.com" + href if href.startswith("/") else href

        # 날짜 정규화 "2026.03.18 15:09" → "2026-03-18"
        date_str = re.sub(r"\.(?=\d{2}\s)", "-", date[:10]).replace(".", "-")

        if title:
            result.append(dict(title=title, publisher=pub,
                               date=date_str, url=full_url, summary="",
                               source="naver"))
        if len(result) >= 10:
            break
    return result

# ──────────────────────────────────────────────
#  데이터 수집
# ──────────────────────────────────────────────
def fetch_all_data(ticker: str) -> dict:
    """yfinance + 외부 3개 소스(TradingView/Investing.com/TradingEconomics) 수집"""
    # ── 캐시 세션으로 Ticker 생성 (레이트 리밋 방지) ─────────────────
    from yf_session import make_ticker
    stock = make_ticker(ticker)
    info  = _yf_retry(lambda: stock.info)

    time.sleep(0.3)   # 연속 호출 완화

    # ── 재무제표
    try: inc = stock.financials
    except: inc = None
    try: bal = stock.balance_sheet
    except: bal = None
    try: cf  = stock.cashflow
    except: cf = None

    # ── 분기 데이터
    try: q_inc = stock.quarterly_financials
    except: q_inc = None
    try: q_bal = stock.quarterly_balance_sheet
    except: q_bal = None

    # ── 실적 날짜 (EPS 실제/예상)
    try:
        edf = stock.earnings_dates
        earnings_dates = edf.head(8) if edf is not None and not edf.empty else None
    except: earnings_dates = None

    # ── 애널리스트 추천 히스토리
    try:
        recs = stock.recommendations
        recs_summary = stock.recommendations_summary
    except: recs = None; recs_summary = None

    # ── 뉴스 (최신 10건) — 미장/국장 분기
    if is_korean_ticker(ticker):
        news = _fetch_kr_news(ticker)       # 네이버 금융 스크래핑
    else:
        news = _fetch_us_news(stock)        # yfinance content 구조 파싱

    # ── 주가 히스토리 (1년)
    try:
        hist = stock.history(period="1y")
    except: hist = pd.DataFrame()

    # ── 외부 3개 소스 병렬 수집 (TradingView / Investing.com / Trading Economics)
    try:
        from web_scraper import fetch_external_data
        yf_exchange = info.get("exchange", "")
        country     = "South Korea" if is_korean_ticker(ticker) else (info.get("country") or "United States")
        external    = fetch_external_data(ticker, yf_exchange=yf_exchange, country=country)
    except Exception as e:
        external = {"tradingview": {}, "investing": {}, "macro": {}}

    return dict(
        info=info, inc=inc, bal=bal, cf=cf,
        q_inc=q_inc, q_bal=q_bal,
        earnings_dates=earnings_dates,
        recs=recs, recs_summary=recs_summary,
        news=news, hist=hist,
        tv=external.get("tradingview", {}),
        inv=external.get("investing", {}),
        macro=external.get("macro", {}),
    )


# ──────────────────────────────────────────────
#  헬퍼 함수
# ──────────────────────────────────────────────
def _b(v) -> str:
    """숫자 → 억/조 or B/M 포맷"""
    if v is None or v == "N/A": return "N/A"
    try:
        v = float(v)
        if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except: return str(v)

def _f(v, d=2, sfx="") -> str:
    if v is None or v == "N/A": return "N/A"
    try: return f"{float(v):,.{d}f}{sfx}"
    except: return str(v)

def _row(label, *vals) -> str:
    cells = " | ".join(str(v) for v in vals)
    return f"| {label} | {cells} |"

def _get(df, *keys):
    """재무제표 DataFrame에서 행 안전 조회"""
    if df is None or df.empty: return None
    for k in keys:
        if k in df.index:
            return df.loc[k]
    return None

def _parse_fin_years(df):
    """연간 재무제표 컬럼을 연도 문자열로 변환"""
    if df is None or df.empty: return []
    return [c.strftime("%Y") if hasattr(c, 'strftime') else str(c)[:4] for c in df.columns[:4]]

def _val(series, idx):
    try:
        v = series.iloc[idx]
        return float(v) if pd.notna(v) else None
    except: return None

def _chg(series):
    """최근 → 전년 YoY 변화율"""
    try:
        cur  = float(series.iloc[0])
        prev = float(series.iloc[1])
        if prev and prev != 0:
            return (cur - prev) / abs(prev) * 100
    except: pass
    return None


# ──────────────────────────────────────────────
#  섹션별 생성 함수
# ──────────────────────────────────────────────
def _sec1_overview(info, hist) -> str:
    cur  = info.get("currentPrice") or info.get("regularMarketPrice", "N/A")
    hi52 = info.get("fiftyTwoWeekHigh", "N/A")
    lo52 = info.get("fiftyTwoWeekLow",  "N/A")
    mkt  = _b(info.get("marketCap"))
    beta = _f(info.get("beta", "N/A"))
    vol  = _b(info.get("averageVolume"))

    # 52주 위치 (%)
    pos_str = ""
    try:
        pos = (float(cur) - float(lo52)) / (float(hi52) - float(lo52)) * 100
        pos_str = f"52주 범위 내 위치: **{pos:.1f}%** (하단=0%, 상단=100%)"
    except: pass

    # YTD 수익률
    ytd_str = ""
    if not hist.empty:
        try:
            start_price = hist["Close"].iloc[0]
            ytd = (float(cur) - float(start_price)) / float(start_price) * 100
            ytd_str = f"1년 수익률: **{ytd:+.1f}%**"
        except: pass

    return f"""## 1. 종목 개요

| 항목 | 내용 | 항목 | 내용 |
|------|------|------|------|
| 종목명 | **{info.get('longName') or info.get('shortName','N/A')}** | 티커 | {info.get('symbol','N/A')} |
| 섹터 | {info.get('sector','N/A')} | 산업 | {info.get('industry','N/A')} |
| 거래소 | {info.get('exchange','N/A')} | 통화 | {info.get('currency','USD')} |
| 시가총액 | {mkt} | 베타 | {beta} |
| 현재가 | **{_f(cur)}** | 평균 거래량 | {vol} |
| 52주 최고 | {_f(hi52)} | 52주 최저 | {_f(lo52)} |

{pos_str}
{ytd_str}
"""


def _sec2_valuation(info) -> str:
    per   = info.get("trailingPE")
    fper  = info.get("forwardPE")
    pbr   = info.get("priceToBook")
    psr   = info.get("priceToSalesTrailing12Months")
    ev    = info.get("enterpriseToEbitda")
    div   = info.get("dividendYield")
    roe   = info.get("returnOnEquity")
    roa   = info.get("returnOnAssets")
    debt  = info.get("debtToEquity")
    cr    = info.get("currentRatio")
    opm   = info.get("operatingMargins")
    npm   = info.get("profitMargins")
    rev_g = info.get("revenueGrowth")
    eps_g = info.get("earningsGrowth")

    # 간단 밸류에이션 판단
    judgment = "N/A"
    if per:
        try:
            p = float(per)
            if p < 15:   judgment = "🟢 저평가"
            elif p < 25: judgment = "🟡 적정"
            elif p < 40: judgment = "🟡 다소 고평가"
            else:        judgment = "🔴 고평가"
        except: pass

    div_str = f"{float(div)*100:.2f}%" if div else "N/A"

    return f"""## 2. 핵심 투자 지표 (Valuation)

| 지표 | 값 | 해석 기준 |
|------|---|----------|
| PER (TTM) | {_f(per,'1')}x | <15 저평가 / 15-25 적정 / >25 고평가 |
| Forward PER | {_f(fper,'1')}x | 미래 성장 반영 |
| PBR | {_f(pbr,'2')}x | <1 자산 대비 저평가 |
| PSR | {_f(psr,'2')}x | <2 선호 |
| EV/EBITDA | {_f(ev,'1')}x | <10 선호 |
| ROE | {_f(roe*100 if roe else None,'1')}% | >15% 우수 |
| ROA | {_f(roa*100 if roa else None,'1')}% | >5% 우수 |
| 영업이익률 | {_f(opm*100 if opm else None,'1')}% | 섹터 비교 필요 |
| 순이익률 | {_f(npm*100 if npm else None,'1')}% | 섹터 비교 필요 |
| 부채비율(D/E) | {_f(debt,'1')}% | <100% 양호 |
| 유동비율 | {_f(cr,'2')}x | >1.5 양호 |
| 배당수익률 | {div_str} | — |
| 매출 성장률 | {_f(rev_g*100 if rev_g else None,'1')}% | — |
| EPS 성장률 | {_f(eps_g*100 if eps_g else None,'1')}% | — |

**밸류에이션 판단:** {judgment}
> PER {_f(per,'1')}x 기준 — Forward PER {_f(fper,'1')}x로 향후 이익 성장 기대 시 {
    '밸류에이션 부담 완화 가능' if fper and per and float(fper) < float(per) else '추가 확인 필요'}.
"""


def _sec3_financials(inc, bal, cf) -> str:
    years = _parse_fin_years(inc)
    if not years:
        return "## 3. 재무제표 분석\n\n> 재무제표 데이터 조회 불가\n"

    header_cols = " | ".join(years[:4])
    sep         = " | ".join(["---"]*4)

    # ── 손익계산서 핵심 항목
    rev   = _get(inc, "Total Revenue")
    op_in = _get(inc, "Operating Income")
    net   = _get(inc, "Net Income")
    ebitda= _get(inc, "Normalized EBITDA", "EBITDA")
    gross = _get(inc, "Gross Profit")

    def row4(label, series, div=1e9, sfx="B"):
        if series is None: return f"| {label} | N/A | N/A | N/A | N/A |"
        vals = [f"${_val(series,i)/div:.2f}{sfx}" if _val(series,i) else "N/A" for i in range(4)]
        return "| " + label + " | " + " | ".join(vals) + " |"

    def pct_row(label, num_s, den_s):
        if num_s is None or den_s is None: return f"| {label} | N/A | N/A | N/A | N/A |"
        vals = []
        for i in range(4):
            n, d = _val(num_s,i), _val(den_s,i)
            vals.append(f"{n/d*100:.1f}%" if n and d else "N/A")
        return "| " + label + " | " + " | ".join(vals) + " |"

    # 수익성 YoY
    rev_yoy = _chg(rev) if rev is not None else None
    net_yoy = _chg(net) if net is not None else None
    rev_yoy_str = f"{rev_yoy:+.1f}%" if rev_yoy else "N/A"
    net_yoy_str = f"{net_yoy:+.1f}%" if net_yoy else "N/A"

    # ── 재무상태표
    total_assets = _get(bal, "Total Assets")
    total_debt   = _get(bal, "Total Debt", "Long Term Debt")
    equity       = _get(bal, "Common Stock Equity", "Stockholders Equity")
    cash         = _get(bal, "Cash And Cash Equivalents")

    # ── 현금흐름
    op_cf  = _get(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex  = _get(cf, "Capital Expenditure")
    fcf    = _get(cf, "Free Cash Flow")
    div_cf = _get(cf, "Cash Dividends Paid")
    buyback= _get(cf, "Repurchase Of Capital Stock")

    # FCF 계산 (없으면 OCF - CapEx)
    if fcf is None and op_cf is not None and capex is not None:
        try:
            fcf_vals = [(_val(op_cf,i) or 0) + (_val(capex,i) or 0) for i in range(4)]
        except: fcf_vals = []
    else:
        fcf_vals = [_val(fcf,i) for i in range(4)] if fcf is not None else []

    fcf_str = " | ".join([f"${v/1e9:.2f}B" if v else "N/A" for v in fcf_vals[:4]])

    # 안정성
    debt_comment = "N/A"
    if total_debt is not None and equity is not None:
        d, e = _val(total_debt, 0), _val(equity, 0)
        if d and e and e != 0:
            de = d / e * 100
            debt_comment = f"D/E {de:.0f}% — {'양호' if de < 100 else '주의 필요'}"

    return f"""## 3. 재무제표 분석

### 3-1. 수익성 분석

| 항목 | {header_cols} |
|------|{sep}|
{row4('매출액 ($B)', rev)}
{row4('영업이익 ($B)', op_in)}
{row4('순이익 ($B)', net)}
{row4('EBITDA ($B)', ebitda)}
{pct_row('영업이익률', op_in, rev)}
{pct_row('순이익률', net, rev)}
{pct_row('매출총이익률', gross, rev)}

최근 YoY — 매출: **{rev_yoy_str}** | 순이익: **{net_yoy_str}**

### 3-2. 안정성 분석

| 항목 | {header_cols} |
|------|{sep}|
{row4('총자산 ($B)', total_assets)}
{row4('총부채 ($B)', total_debt)}
{row4('자기자본 ($B)', equity)}
{row4('현금 ($B)', cash)}

{debt_comment}

### 3-3. 현금흐름 & 주주환원

| 항목 | {header_cols} |
|------|{sep}|
{row4('영업현금흐름 ($B)', op_cf)}
{row4('자본지출 CapEx ($B)', capex)}
| 잉여현금흐름 FCF ($B) | {fcf_str} |
{row4('배당금 지급 ($B)', div_cf)}
{row4('자사주 매입 ($B)', buyback)}
"""


def _sec4_technical(tech: dict) -> str:
    price  = tech.get("현재가","N/A")
    sma20  = tech.get("SMA_20","N/A")
    sma60  = tech.get("SMA_60","N/A")
    sma120 = tech.get("SMA_120","N/A")
    macd   = tech.get("MACD","N/A")
    sig    = tech.get("MACD_Signal","N/A")
    hist   = tech.get("MACD_Histogram","N/A")
    rsi    = tech.get("RSI_14","N/A")
    gap    = tech.get("이격도_20","N/A")
    trend  = tech.get("추세","N/A")
    gc     = tech.get("골든크로스_20_60", False)
    dc     = tech.get("데드크로스_20_60", False)
    mbuy   = tech.get("MACD_매수시그널", False)
    msell  = tech.get("MACD_매도시그널", False)

    # MA 배열 판단
    try:
        p,s20,s60,s120 = float(price),float(sma20),float(sma60),float(sma120)
        if p > s20 > s60 > s120:
            ma_comment = "✅ **정배열** (현재가 > SMA20 > SMA60 > SMA120) — 강한 상승 추세"
        elif p < s20 < s60 < s120:
            ma_comment = "🔴 **역배열** — 하락 추세 지속"
        else:
            ma_comment = "⚠️ **혼조 배열** — 추세 전환 구간"
    except: ma_comment = "N/A"

    # RSI 판단
    try:
        r = float(rsi)
        rsi_label = "🔴 과매수 (>70) — 단기 조정 주의" if r > 70 \
               else "🟢 과매도 (<30) — 반등 가능성" if r < 30 \
               else f"✅ 중립 ({r:.1f}) — 추가 상승 여력"
    except: rsi_label = "N/A"

    # MACD 판단
    try:
        m, s = float(macd), float(sig)
        h     = float(hist)
        macd_comment = ("✅ MACD > Signal, Histogram 양수 — 강세" if m > s and h > 0
                   else "🔴 MACD < Signal, Histogram 음수 — 약세" if m < s and h < 0
                   else "⚠️ 크로스 전환 구간")
    except: macd_comment = "N/A"

    # 지지/저항선
    try:
        support    = min(float(sma20), float(sma60))
        resistance = float(price) * 1.05  # 임시
        sr_str = f"지지선: **${support:,.2f}** (SMA20/60 중 낮은 값) | 저항선: **${resistance:,.2f}** (현재가 +5%)"
    except: sr_str = ""

    # 종합 기술 판단
    try:
        above_sma20 = float(price) > float(sma20)
    except Exception:
        above_sma20 = False

    buy_signals  = sum([above_sma20, mbuy, gc, not dc and not msell])
    tech_verdict = ("✅ 매수 시그널" if buy_signals >= 3
               else "🔴 매도 시그널" if (dc or msell) and buy_signals <= 1
               else "⚠️ 중립")

    # 오실레이터 vs 이동평균 충돌 감지 → 초보자 해설
    try:
        rsi_val = float(rsi)
        osc_bullish = rsi_val < 50 and float(macd) > float(sig)   # RSI 중립 이하 + MACD 골든
        osc_bearish = rsi_val > 50 and float(macd) < float(sig)   # RSI 중립 이상 + MACD 데드
        ma_bullish  = above_sma20 and (float(price) > float(sma60) if sma60 != "N/A" else False)
        conflict_msg = ""
        if osc_bullish and not ma_bullish:
            conflict_msg = (
                "> 💡 **신호 충돌 해설:** MACD는 상승 전환 신호를 보내고 있지만, "
                "현재가가 SMA 이동평균선 아래에 있어 추세 회복이 아직 확인되지 않았습니다. "
                "단기 반등 가능성은 있으나, **이동평균선 위로 돌파 확인 후 진입**을 권장합니다."
            )
        elif not osc_bullish and ma_bullish:
            conflict_msg = (
                "> 💡 **신호 충돌 해설:** 주가는 이동평균선 위에서 상승 추세를 유지하고 있지만, "
                f"RSI({rsi_val:.0f})와 MACD가 모멘텀 약화를 나타내고 있습니다. "
                "**추세는 유효하지만 단기 과열 조정 가능성**에 유의하세요."
            )
        elif (dc or msell) and rsi_val < 35:
            conflict_msg = (
                f"> 💡 **신호 충돌 해설:** 이동평균·MACD는 약세 신호지만, "
                f"RSI({rsi_val:.0f})가 과매도 구간에 근접했습니다. "
                "단기 기술적 반등이 나올 수 있으나, **추세 전환 확인 전까지는 관망**을 권장합니다."
            )
    except Exception:
        conflict_msg = ""

    return f"""## 4. 기술적 분석 (최근 6개월 일봉)

### 4-1. 이동평균선

| 항목 | 값 | 현재가 대비 |
|------|---|------------|
| 현재가 | **{_f(price)}** | — |
| SMA 20일 | {_f(sma20)} | {f"{(float(price)/float(sma20)-1)*100:+.1f}%" if price!="N/A" and sma20!="N/A" else "N/A"} |
| SMA 60일 | {_f(sma60)} | {f"{(float(price)/float(sma60)-1)*100:+.1f}%" if price!="N/A" and sma60!="N/A" else "N/A"} |
| SMA 120일 | {_f(sma120)} | {f"{(float(price)/float(sma120)-1)*100:+.1f}%" if price!="N/A" and sma120!="N/A" else "N/A"} |
| 이격도 (SMA20) | {_f(gap)}% | — |

{ma_comment}
골든크로스: {'✅ 발생' if gc else '—'} | 데드크로스: {'🔴 발생' if dc else '—'}
{sr_str}

### 4-2. MACD 분석

| 항목 | 값 |
|------|---|
| MACD | {_f(macd,'4')} |
| Signal | {_f(sig,'4')} |
| Histogram | {_f(hist,'4')} |

{macd_comment}
MACD 매수 시그널: {'✅' if mbuy else '—'} | 매도 시그널: {'🔴' if msell else '—'}

### 4-3. RSI 분석

| RSI (14일) | {_f(rsi,'1')} |
|------------|---|

{rsi_label}

### 4-4. 종합 기술적 판단

**{tech_verdict}** (매수 시그널 {buy_signals}/4개 충족)

| 시그널 | 상태 |
|--------|------|
| MA 배열 | {ma_comment.split('—')[0].strip()} |
| MACD | {macd_comment.split('—')[0].strip()} |
| RSI | {rsi_label.split('—')[0].strip()} |
| 골든크로스 | {'✅ 발생' if gc else '미발생'} |

{conflict_msg}
"""


def _sec4b_tradingview(tv: dict) -> str:
    """TradingView 기술적 지표 보조 섹션"""
    if not tv or tv.get("error"):
        return ""

    # 타임프레임 등급 테이블 (TradingView는 종합만 제공)
    rec_all   = tv.get("recommend_all", "N/A")
    rec_ma    = tv.get("recommend_ma", "N/A")
    rec_osc   = tv.get("recommend_oscillators", "N/A")
    rsi_tv    = tv.get("rsi", "N/A")
    stoch_k   = tv.get("stoch_k", "N/A")
    stoch_d   = tv.get("stoch_d", "N/A")
    cci       = tv.get("cci", "N/A")
    williams  = tv.get("williams_r", "N/A")
    atr       = tv.get("atr", "N/A")
    bb_upper  = tv.get("bb_upper", "N/A")
    bb_lower  = tv.get("bb_lower", "N/A")
    sma50     = tv.get("sma50", "N/A")
    sma200    = tv.get("sma200", "N/A")
    ema20     = tv.get("ema20", "N/A")
    ema50     = tv.get("ema50", "N/A")

    return f"""### 4-5. TradingView 기술적 요약

| 구분 | 등급 |
|------|------|
| **종합 추천** | **{rec_all}** |
| 이동평균 추천 | {rec_ma} |
| 오실레이터 추천 | {rec_osc} |

| 오실레이터 지표 | 값 |
|----------------|-----|
| RSI (14) | {_f(rsi_tv, 2)} |
| Stochastic %K / %D | {_f(stoch_k, 2)} / {_f(stoch_d, 2)} |
| CCI (20) | {_f(cci, 2)} |
| Williams %R | {_f(williams, 2)} |
| ATR | {_f(atr, 4)} |

| 이동평균 | 값 |
|---------|-----|
| SMA 50 | {_f(sma50)} |
| SMA 200 | {_f(sma200)} |
| EMA 20 | {_f(ema20)} |
| EMA 50 | {_f(ema50)} |

| 볼린저 밴드 | 값 |
|-----------|-----|
| 상단 (Upper) | {_f(bb_upper)} |
| 하단 (Lower) | {_f(bb_lower)} |

> 출처: [TradingView]({tv.get('symbol','')})
"""


def _sec5_earnings(earnings_dates, q_inc, info, next_earn: str = "", next_earn_src: str = "") -> str:
    lines = ["## 5. 최근 실적 분석\n"]

    # 분기 실적
    if q_inc is not None and not q_inc.empty:
        def _fmt_quarter(c):
            if hasattr(c, 'month'):
                q = (c.month - 1) // 3 + 1
                return f"{q}Q{c.year}"
            s = str(c)[:7]
            return s
        q_years = [_fmt_quarter(c) for c in q_inc.columns[:4]]
        rev_q   = _get(q_inc, "Total Revenue")
        net_q   = _get(q_inc, "Net Income")

        lines.append("### 최근 분기 실적\n")
        header = " | ".join(q_years[:4])
        sep    = " | ".join(["---"]*4)
        lines.append(f"| 항목 | {header} |")
        lines.append(f"|------|{sep}|")

        def qrow(label, s, div=1e9, sfx="B"):
            if s is None: return f"| {label} | N/A | N/A | N/A | N/A |"
            vals = [f"${_val(s,i)/div:.2f}{sfx}" if _val(s,i) else "N/A" for i in range(4)]
            return "| " + label + " | " + " | ".join(vals) + " |"

        lines.append(qrow("매출액 ($B)", rev_q))
        lines.append(qrow("순이익 ($B)", net_q))
        lines.append("")

    # EPS 실제 vs 예상
    if earnings_dates is not None and not earnings_dates.empty:
        lines.append("### EPS 실적 vs 컨센서스\n")
        lines.append("| 날짜 | EPS 예상 | EPS 실제 | 서프라이즈 |")
        lines.append("|------|---------|---------|-----------|")
        for idx, row in earnings_dates.head(6).iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx,'strftime') else str(idx)[:10]
            est  = row.get("EPS Estimate", row.get("Estimated EPS", "N/A"))
            act  = row.get("Reported EPS", row.get("Actual EPS", "N/A"))
            try:
                surp = (float(act) - float(est)) / abs(float(est)) * 100
                surp_str = f"{surp:+.1f}% {'✅' if surp>0 else '🔴'}"
            except: surp_str = "N/A"
            lines.append(f"| {date_str} | {_f(est,'2')} | {_f(act,'2')} | {surp_str} |")
        lines.append("")

    # 다음 실적 발표일 — 미래 날짜만 표시 (generate_full_report에서 검증된 값 사용)
    if next_earn:
        src_badge = f" *({next_earn_src})*" if next_earn_src else ""
        lines.append(f"📅 **다음 실적 발표 예정:** {next_earn}{src_badge}\n")

    # 가이던스
    target_rev = info.get("revenueEstimates")
    target_eps = info.get("forwardEps")
    if target_eps:
        lines.append(f"**Forward EPS (컨센서스):** ${_f(target_eps,'2')}")

    if len(lines) == 1:
        lines.append("> 실적 데이터를 불러올 수 없습니다.")

    return "\n".join(lines)


def _sec6_industry(info) -> str:
    sector   = info.get("sector","N/A")
    industry = info.get("industry","N/A")
    country  = info.get("country","N/A")

    # 섹터별 주요 지표 기준 (일반적 기준값)
    benchmarks = {
        "Technology":          {"avg_per": 30, "avg_margin": 20},
        "Communication Services": {"avg_per": 22, "avg_margin": 15},
        "Healthcare":          {"avg_per": 25, "avg_margin": 12},
        "Financial Services":  {"avg_per": 14, "avg_margin": 25},
        "Consumer Cyclical":   {"avg_per": 20, "avg_margin": 8},
        "Consumer Defensive":  {"avg_per": 22, "avg_margin": 10},
        "Energy":              {"avg_per": 12, "avg_margin": 10},
        "Industrials":         {"avg_per": 20, "avg_margin": 10},
        "Basic Materials":     {"avg_per": 15, "avg_margin": 8},
        "Real Estate":         {"avg_per": 40, "avg_margin": 20},
        "Utilities":           {"avg_per": 18, "avg_margin": 15},
    }
    bm = benchmarks.get(sector, {"avg_per": 20, "avg_margin": 12})

    per = info.get("trailingPE")
    opm = info.get("operatingMargins")
    per_vs = ""
    opm_vs = ""
    if per:
        try:
            diff = float(per) - bm["avg_per"]
            per_vs = f" (섹터 평균 {bm['avg_per']}x 대비 {diff:+.1f}x)"
        except: pass
    if opm:
        try:
            diff = float(opm)*100 - bm["avg_margin"]
            opm_vs = f" (섹터 평균 {bm['avg_margin']}% 대비 {diff:+.1f}%p)"
        except: pass

    # 주요 경쟁사 (동종업종 yfinance 조회)
    competitors_str = ""
    try:
        comps = []
        for c_ticker in (info.get("competitors") or [])[:3]:
            ci = yf.Ticker(c_ticker).info
            comps.append((c_ticker, ci.get("longName",""), ci.get("marketCap"), ci.get("trailingPE")))
        if comps:
            competitors_str = "\n### 주요 경쟁사 비교\n\n| 티커 | 기업명 | 시가총액 | PER |\n|------|------|---------|-----|\n"
            competitors_str += "\n".join(f"| {t} | {n} | {_b(mc)} | {_f(pe,'1')}x |" for t,n,mc,pe in comps)
    except: pass

    return f"""## 6. 산업 분석 & 경쟁 환경

| 항목 | 내용 |
|------|------|
| 섹터 | {sector} |
| 산업 | {industry} |
| 국가 | {country} |
| 종업원 수 | {f"{info.get('fullTimeEmployees'):,}" if info.get('fullTimeEmployees') else 'N/A'} 명 |

### 섹터 내 상대 위치

| 지표 | 해당 종목 | 섹터 평균 |
|------|----------|----------|
| PER | {_f(per,'1')}x | {bm['avg_per']}x |
| 영업이익률 | {_f(opm*100 if opm else None,'1')}% | {bm['avg_margin']}% |

- PER{per_vs}
- 영업이익률{opm_vs}

{competitors_str}

> 상세 경쟁사 비교는 동일 산업({industry}) 내 주요 기업과의 분기별 실적 비교를 권장합니다.
"""


def _sec6b_macro(macro: dict, inv: dict) -> str:
    """Trading Economics 거시경제 + Investing.com 데이터 보조 섹션"""
    lines = ["### 거시경제 환경 (Trading Economics)\n"]

    macro_data = macro.get("data", {})
    country    = macro.get("country", "")
    if not macro_data:
        lines.append("> 거시경제 데이터를 불러올 수 없습니다.\n")
    else:
        lines.append("| 지표 | 현재값 | 이전값 | 단위 |")
        lines.append("|------|--------|--------|------|")
        priority = ["기준금리", "인플레이션", "소비자물가(CPI)", "CPI", "GDP 성장률(분기)",
                    "GDP 성장률(연간)", "실업률", "비농업고용(천명)", "증시", "환율"]
        shown = set()
        for key in priority:
            if key in macro_data and key not in shown:
                v = macro_data[key]
                lines.append(f"| {key} | {v.get('현재값','N/A')} | {v.get('이전값','N/A')} | {v.get('단위','')} |")
                shown.add(key)
        # 나머지
        for key, v in macro_data.items():
            if key not in shown:
                lines.append(f"| {key} | {v.get('현재값','N/A')} | {v.get('이전값','N/A')} | {v.get('단위','')} |")

        lines.append(f"\n> 출처: [Trading Economics — {country}]({macro.get('url','')})\n")

    # Investing.com 추가 fundamental
    fund = inv.get("fundamental", {})
    if fund and not inv.get("error"):
        yr = fund.get("one_year_return_pct")
        yr_str = f"{yr:+.1f}%" if yr is not None else "N/A"
        lines.append("\n### Investing.com 추가 지표\n")
        lines.append("| 항목 | 값 |")
        lines.append("|------|---|")
        lines.append(f"| 1년 수익률 | {yr_str} |")
        lines.append(f"| EPS | {_f(fund.get('eps'))} |")
        lines.append(f"| 배당금 | {_f(fund.get('dividend'))} |")
        lines.append(f"| 배당수익률 | {_f(fund.get('div_yield_pct'),'2')}% |")
        lines.append(f"| 타임프레임 일봉 기술 등급 | {inv.get('daily_rating','N/A')} |")
        lines.append(f"\n> 출처: [Investing.com]({inv.get('url','')})\n")

    return "\n".join(lines)


def _sec7_news(news: list) -> str:
    """통합 뉴스 포맷(미장/국장 공통) → 섹션 렌더링"""
    if not news:
        return "## 7. 뉴스 & 시장 센티먼트\n\n> 최신 뉴스를 불러올 수 없습니다.\n"

    source_label = {"yfinance": "🇺🇸 Yahoo Finance", "naver": "🇰🇷 네이버 금융"}.get(
        news[0].get("source", ""), "")

    lines = [
        "## 7. 뉴스 & 시장 센티먼트\n",
        f"### 최신 뉴스 ({source_label})\n",
    ]
    for n in news[:10]:
        title   = n.get("title", "—")
        pub     = n.get("publisher", "")
        date    = n.get("date", "")
        url     = n.get("url", "#")
        summary = n.get("summary", "")

        meta = " · ".join(filter(None, [pub, date]))
        lines.append(f"- **[{title}]({url})**")
        if meta:
            lines.append(f"  _{meta}_")
        if summary:
            # 요약이 너무 길면 잘라냄
            short = summary[:160] + "…" if len(summary) > 160 else summary
            lines.append(f"  > {short}")
        lines.append("")

    # 시장 센티먼트 간단 판단
    positive_kw = ["상승", "호실적", "매수", "급등", "신고가", "surged", "beat", "strong", "buy", "upgrade", "record"]
    negative_kw = ["하락", "급락", "매도", "적자", "손실", "실망", "fell", "miss", "weak", "sell", "downgrade", "cut"]
    all_text = " ".join(n.get("title","") + " " + n.get("summary","") for n in news).lower()
    pos = sum(1 for kw in positive_kw if kw in all_text)
    neg = sum(1 for kw in negative_kw if kw in all_text)

    if pos > neg + 1:
        sentiment = "🟢 **긍정적** — 뉴스 전반에서 호재 키워드 다수 감지"
    elif neg > pos + 1:
        sentiment = "🔴 **부정적** — 뉴스 전반에서 악재 키워드 다수 감지"
    else:
        sentiment = "🟡 **중립** — 긍·부정 혼재"

    lines.append(f"\n### 시장 센티먼트 판단\n\n{sentiment}\n")
    return "\n".join(lines)


def _sec8_risk(info, tech) -> str:
    beta = info.get("beta")
    debt = info.get("debtToEquity")
    short= info.get("shortRatio")
    country = info.get("country","")

    beta_risk = ""
    if beta:
        try:
            b = float(beta)
            beta_risk = (f"- **고베타 ({b:.2f}):** 시장 변동성 대비 {b:.1f}배 변동 — 시장 하락 시 낙폭 확대 위험"
                        if b > 1.5 else
                        f"- **저베타 ({b:.2f}):** 방어적 특성 — 시장 상승 시 수익률 제한 가능"
                        if b < 0.8 else
                        f"- 베타 {b:.2f} — 시장과 유사한 변동성")
        except: pass

    debt_risk = ""
    if debt:
        try:
            d = float(debt)
            if d > 150: debt_risk = f"- **높은 부채비율 ({d:.0f}%):** 금리 상승 시 이자 부담 증가 위험"
        except: pass

    short_risk = ""
    if short:
        try:
            s = float(short)
            if s > 5: short_risk = f"- **공매도 비율 높음 (Short Ratio {s:.1f}일):** 시장의 부정적 시각 반영"
        except: pass

    china_risk = "- **지정학적 리스크:** 미·중 무역 분쟁, 수출 규제 등 글로벌 공급망 영향 가능" if "China" in str(info.get("country","")) or info.get("sector","") == "Technology" else ""

    return f"""## 8. 리스크 요인

### 거시경제 리스크
- 금리 인상/고금리 지속 → 밸류에이션 압박 (고PER 종목 특히 취약)
- 달러 강세 → 해외 매출 환산 손실
- 경기 침체 우려 → 기업 IT·설비 투자 축소
{china_risk}

### 기업 고유 리스크
{beta_risk}
{debt_risk}
{short_risk}
- 실적 가이던스 하향 또는 예상 미달 시 급락 가능성
- 경영진 교체, M&A 불확실성

### 산업 리스크
- 기술 변화 가속으로 기존 제품·서비스 경쟁력 약화 위험
- 신규 경쟁사 진입 및 기존 경쟁 심화
- 규제 환경 변화 (데이터 보호, 반독점 등)

### 기술적 리스크
- {'⚠️ RSI 과매수 — 단기 조정 가능성' if isinstance(tech.get('RSI_14'), float) and tech['RSI_14'] > 70 else '현재 RSI 정상 범위'}
- {'🔴 데드크로스 발생 — 하락 추세 위험' if tech.get('데드크로스_20_60') else ''}
"""


def _sec9_outlook(info, analyst, earnings_dates, next_earn: str = "", next_earn_src: str = "", consensus: str = "") -> str:
    target_avg  = info.get("targetMeanPrice")
    target_high = info.get("targetHighPrice")
    target_low  = info.get("targetLowPrice")
    cur_price   = info.get("currentPrice") or info.get("regularMarketPrice")
    rec         = str(info.get("recommendationKey","")).upper()
    n_analysts  = info.get("numberOfAnalystOpinions", "N/A")
    rev_g       = info.get("revenueGrowth")
    eps_fwd     = info.get("forwardEps")

    upside = ""
    if target_avg and cur_price:
        try:
            u = (float(target_avg) - float(cur_price)) / float(cur_price) * 100
            upside = f" (+{u:.1f}% 상승 여력)" if u > 0 else f" ({u:.1f}%)"
        except: pass

    # 다음 실적 발표일 — generate_full_report에서 이미 미래 날짜 검증 완료
    next_ed_str = ""
    if next_earn:
        src_badge = f" *({next_earn_src})*" if next_earn_src else ""
        next_ed_str = f"- 📅 **다음 실적 발표:** {next_earn}{src_badge}"

    return f"""## 9. 향후 6개월 주가 영향 요인

### 상방 요인 (Catalyst)
- **애널리스트 목표가:** 평균 ${_f(target_avg,'0')}{upside} | 최고 ${_f(target_high,'0')}
- **Forward EPS:** ${_f(eps_fwd,'2')} — 이익 성장 시 밸류에이션 정상화
- **매출 성장률:** {_f(rev_g*100 if rev_g else None,'1')}% 성장 궤도 유지 시 주가 지지
- 업종 전반의 긍정적 사이클 진입 시 섹터 자금 유입
- 자사주 매입·배당 증가 등 주주환원 확대

### 하방 요인 (Risk)
- 목표가 하단: ${_f(target_low,'0')} — 실적 미달 시 하방 지지선
- 금리 상승 지속 시 성장주 밸류에이션 재평가
- 시장 전반 위험회피 심리 강화 시 성장주 약세

### 주요 일정
{next_ed_str}
- 배당 지급일 — 정기 주주환원 확인 필요
- 업계 주요 컨퍼런스 및 제품 발표 일정 주시

### 애널리스트 컨센서스
- 추천 의견: **{consensus if consensus else rec}** ({n_analysts}명 참여)
- 목표가 범위: ${_f(target_low,'0')} ~ ${_f(target_high,'0')} (평균 ${_f(target_avg,'0')})
"""


def _sec10_verdict(info, val, tech, analyst, tv: dict = None, inv: dict = None, consensus: str = "") -> str:
    # ── 점수 계산
    # 1) 기본적 분석 (40점)
    score_fund = 20  # 기본 베이스
    per = info.get("trailingPE")
    roe = info.get("returnOnEquity")
    opm = info.get("operatingMargins")
    rev_g = info.get("revenueGrowth")
    eps_g = info.get("earningsGrowth")

    if per:
        try:
            p = float(per)
            score_fund += 8 if p < 15 else (6 if p < 25 else (3 if p < 40 else 0))
        except: pass
    if roe:
        try:
            r = float(roe) * 100
            score_fund += 6 if r > 20 else (4 if r > 10 else 2)
        except: pass
    if opm:
        try:
            o = float(opm) * 100
            score_fund += 4 if o > 20 else (3 if o > 10 else 1)
        except: pass
    if rev_g:
        try:
            g = float(rev_g) * 100
            score_fund += 2 if g > 10 else (1 if g > 0 else 0)
        except: pass

    score_fund = min(40, score_fund)

    # 2) 기술적 분석 (25점)
    score_tech = 12
    rsi = tech.get("RSI_14")
    if rsi and rsi != "N/A":
        try:
            r = float(rsi)
            score_tech += 5 if 40 < r < 65 else (2 if 30 <= r <= 70 else 0)
        except: pass
    macd_h = tech.get("MACD_Histogram")
    if macd_h and macd_h != "N/A":
        try: score_tech += 4 if float(macd_h) > 0 else 0
        except: pass
    if tech.get("골든크로스_20_60"): score_tech += 4
    if tech.get("데드크로스_20_60"): score_tech -= 4
    score_tech = max(0, min(25, score_tech))

    # 3) 산업·경쟁력 (20점) — 마진으로 추정
    score_ind = 10
    if opm:
        try:
            o = float(opm) * 100
            score_ind += 8 if o > 30 else (6 if o > 15 else (3 if o > 5 else 0))
        except: pass
    score_ind = min(20, score_ind)

    # 4) 센티먼트·뉴스 (15점)
    score_sent = 8
    # consensus 우선 (NONE 폴백 적용된 값)
    rec = (consensus or str(info.get("recommendationKey","") or "")).lower()
    score_sent += (5 if "strong_buy" in rec or "strong buy" in rec or rec == "buy"
                  else 4 if "moderate buy" in rec
                  else 3 if "hold" in rec
                  else 0)
    target_avg = info.get("targetMeanPrice")
    cur_price  = info.get("currentPrice") or info.get("regularMarketPrice")
    if target_avg and cur_price:
        try:
            u = (float(target_avg) - float(cur_price)) / float(cur_price) * 100
            score_sent += 2 if u > 10 else (1 if u > 0 else 0)
        except: pass
    score_sent = min(15, score_sent)

    # ── TradingView 점수 보정 (기술 점수에 최대 ±3 가산)
    tv_bonus = 0
    tv_rating_str = ""
    if tv and not (tv or {}).get("error"):
        raw = (tv or {}).get("recommend_all_raw")
        tv_rating_str = (tv or {}).get("recommend_all", "")
        if raw is not None:
            try:
                rv = float(raw)
                tv_bonus = 3 if rv >= 0.5 else (2 if rv >= 0.1 else (-2 if rv <= -0.5 else 0))
            except: pass
    score_tech = min(25, score_tech + tv_bonus)

    # ── Investing.com 점수 보정 (센티먼트 점수에 최대 ±2 가산)
    inv_bonus = 0
    inv_rating_str = ""
    if inv and not (inv or {}).get("error"):
        inv_rating_str = (inv or {}).get("daily_rating", "")
        if "강한 매수" in inv_rating_str:   inv_bonus =  2
        elif "매수" in inv_rating_str:      inv_bonus =  1
        elif "매도" in inv_rating_str:      inv_bonus = -1
        elif "강한 매도" in inv_rating_str: inv_bonus = -2
    score_sent = min(15, score_sent + inv_bonus)

    total = score_fund + score_tech + score_ind + score_sent

    # 멀티 소스 등급 요약
    multi_rating = ""
    if tv_rating_str or inv_rating_str:
        rows = []
        if tv_rating_str:  rows.append(f"| TradingView | {tv_rating_str} |")
        if inv_rating_str: rows.append(f"| Investing.com | {inv_rating_str} |")
        multi_rating = "\n### 멀티 소스 기술 등급\n\n| 소스 | 등급 |\n|------|------|\n" + "\n".join(rows) + "\n"

    # 투자 의견
    if total >= 80:
        st_op, mt_op, lt_op = "**매수**", "**매수**", "**강력 매수**"
    elif total >= 65:
        st_op, mt_op, lt_op = "**매수**", "**매수**", "**매수**"
    elif total >= 50:
        st_op, mt_op, lt_op = "**보유**", "**보유**", "**매수 검토**"
    else:
        st_op, mt_op, lt_op = "**보유/매도**", "**보유**", "**보유**"

    return f"""## 10. 투자 판단 종합

### 🎯 종합 점수 (100점 만점)

| 항목 | 점수 | 비중 | 가중점수 |
|------|------|------|---------|
| 기본적 분석 (재무·실적) | {score_fund}/40 | 40% | {score_fund:.0f} |
| 기술적 분석 (차트) | {score_tech}/25 | 25% | {score_tech:.0f} |
| 산업·경쟁력 | {score_ind}/20 | 20% | {score_ind:.0f} |
| 시장 센티먼트·뉴스 | {score_sent}/15 | 15% | {score_sent:.0f} |
| **종합** | **{total}/100** | | **{total}점** |

{'🟢 매수 우위' if total >= 65 else '🟡 중립' if total >= 50 else '🔴 신중 접근'}
{multi_rating}
### 📌 투자 의견

| 기간 | 의견 | 근거 |
|------|------|------|
| 단기 (1~3개월) | {st_op} | 기술적 모멘텀 + 단기 이벤트 |
| 중기 (6개월) | {mt_op} | 실적 사이클 + 산업 동향 |
| 장기 (1년+) | {lt_op} | 펀더멘털 + 경쟁 우위 |

### 핵심 투자 포인트 요약

- **강점:** ROE {_f(info.get('returnOnEquity',0)*100 if info.get('returnOnEquity') else None,'1')}% | 영업이익률 {_f(info.get('operatingMargins',0)*100 if info.get('operatingMargins') else None,'1')}% | 애널리스트 의견 {consensus or str(info.get('recommendationKey','N/A')).upper()}
- **리스크:** PER {_f(info.get('trailingPE'),'1')}x 밸류에이션 | 시장 변동성 | 거시경제 불확실성
- **주목 일정:** 다음 실적 발표 / 배당 지급

---

> ⚠️ **면책 조항:** 본 분석은 공개 데이터(yfinance) 기반 자동 생성 리포트로, **투자 권유가 아닙니다.**
> 모든 투자 판단과 그에 따른 손익은 **투자자 본인의 책임**이며, 중요한 투자 결정 전 **전문 투자자문사 상담**을 권장합니다.
"""


# ──────────────────────────────────────────────
#  메인 엔트리포인트
# ──────────────────────────────────────────────
def _sec0_takeaways(ticker: str, info: dict, tech: dict, tv: dict, inv: dict,
                    consensus: str, next_earn: str, next_earn_src: str) -> str:
    """
    핵심 요약 (Key Takeaways) — 리포트 최상단에 배치
    모바일 최적화: 특수문자 최소화, 핵심만 3~5줄 요약
    """
    name      = info.get("longName") or info.get("shortName", ticker)
    price     = info.get("currentPrice") or info.get("regularMarketPrice")
    chg_pct   = info.get("regularMarketChangePercent")
    sector    = info.get("sector", "")
    mktcap    = info.get("marketCap")
    target    = info.get("targetMeanPrice")
    rec_key   = str(info.get("recommendationKey","") or "").upper()

    # 등락률
    chg_str = ""
    if chg_pct is not None:
        try:
            chg_str = f" ({float(chg_pct)*100:+.2f}%)"
        except Exception:
            pass

    # 상승여력
    upside_str = ""
    if target and price:
        try:
            u = (float(target) - float(price)) / float(price) * 100
            upside_str = f"  목표가 ${_f(target,'0')} (상승여력 {u:+.1f}%)"
        except Exception:
            pass

    # 시총
    mktcap_str = ""
    if mktcap:
        try:
            m = float(mktcap)
            mktcap_str = f"${m/1e12:.2f}T" if m >= 1e12 else f"${m/1e9:.1f}B"
        except Exception:
            pass

    # TV / Investing 종합 등급
    tv_rating  = tv.get("recommend_all", "") if tv and not tv.get("error") else ""
    inv_rating = inv.get("daily_rating", "") if inv and not inv.get("error") else ""
    rating_parts = [r for r in [tv_rating, inv_rating] if r and r != "N/A"]
    rating_str = " / ".join(rating_parts) if rating_parts else (consensus or rec_key or "N/A")

    # 다음 실적일
    earn_str = f"  다음 실적: {next_earn}" if next_earn else ""

    lines = [
        f"## 핵심 요약",
        "",
        f"| 항목 | 내용 |",
        f"|------|------|",
        f"| 종목 | {name} ({ticker}) |",
        f"| 현재가 | ${_f(price,'2')}{chg_str} |",
        f"| 시가총액 | {mktcap_str} |",
        f"| 섹터 | {sector} |",
        f"| 기술적 등급 | {rating_str} |",
        f"| 애널리스트 의견 | {consensus or rec_key or 'N/A'}{upside_str} |",
    ]
    if earn_str:
        lines.append(f"| 다음 실적 발표 | {next_earn} ({next_earn_src}) |")

    # 한줄 투자 포인트
    rsi_val = tech.get("RSI_14", "")
    trend   = tech.get("추세", "")
    try:
        r = float(rsi_val)
        rsi_note = "과매수 주의" if r > 70 else ("과매도 반등 가능" if r < 30 else f"RSI 중립({r:.0f})")
    except Exception:
        rsi_note = ""

    summary_parts = [p for p in [
        f"추세 {trend}" if trend else "",
        rsi_note,
        f"목표가 대비 {upside_str.strip()}" if upside_str else "",
    ] if p]
    if summary_parts:
        lines += ["", f"> {' | '.join(summary_parts)}"]

    lines += ["", "---", ""]
    return "\n".join(lines)


def _resolve_analyst_consensus(info: dict, recs_summary) -> str:
    """
    recommendationKey 가 'none'/None 일 때 recommendations_summary DataFrame 으로 폴백.
    반환: 'STRONG BUY' | 'BUY' | 'HOLD' | 'SELL' | 'N/A' + 상세 (예: 'BUY (강수:9 / 매수:27 / 보유:9)')
    """
    key = str(info.get("recommendationKey", "") or "").strip().lower()
    if key and key != "none":
        return key.upper()

    # recommendations_summary 폴백
    try:
        if recs_summary is not None and not recs_summary.empty:
            row = recs_summary[recs_summary["period"] == "0m"].iloc[0]
            sb   = int(row.get("strongBuy", 0)   or 0)
            b    = int(row.get("buy", 0)          or 0)
            h    = int(row.get("hold", 0)         or 0)
            s    = int(row.get("sell", 0)         or 0)
            ss   = int(row.get("strongSell", 0)   or 0)
            total = sb + b + h + s + ss
            if total == 0:
                return "N/A"
            buy_ratio = (sb + b) / total
            if buy_ratio >= 0.6:
                label = "STRONG BUY" if sb > b else "BUY"
            elif buy_ratio >= 0.4:
                label = "MODERATE BUY"
            elif (s + ss) / total >= 0.4:
                label = "SELL"
            else:
                label = "HOLD"
            return f"{label} (강수:{sb} / 매수:{b} / 보유:{h} / 매도:{s+ss}, 총{total}명)"
    except Exception:
        pass
    return "N/A"


def _resolve_next_earnings(info: dict, earnings_dates, next_earn_inv: str) -> str:
    """
    다음 실적 발표일을 확정. Investing.com > yfinance earningsTimestamp (미래만) > N/A
    """
    # 1순위: Investing.com (신뢰도 가장 높음)
    if next_earn_inv:
        try:
            dt = datetime.strptime(next_earn_inv[:10], "%Y-%m-%d")
            if dt > datetime.now():
                return next_earn_inv[:10], "Investing.com"
        except Exception:
            pass

    # 2순위: yfinance earningsTimestamp — 미래 날짜만 허용
    ts = info.get("earningsTimestamp")
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts))
            if dt > datetime.now():
                return dt.strftime("%Y-%m-%d"), "yfinance"
        except Exception:
            pass

    # 3순위: earnings_dates DataFrame 에서 미래 날짜 탐색
    if earnings_dates is not None and not earnings_dates.empty:
        try:
            now = datetime.now()
            future = [idx for idx in earnings_dates.index
                      if hasattr(idx, "to_pydatetime") and idx.to_pydatetime() > now]
            if future:
                return min(future).strftime("%Y-%m-%d"), "yfinance"
        except Exception:
            pass

    return "", ""


def generate_full_report(ticker: str, tech: dict, data: dict) -> str:
    info         = data["info"]
    inc          = data["inc"]
    bal          = data["bal"]
    cf           = data["cf"]
    q_inc        = data["q_inc"]
    hist         = data.get("hist", pd.DataFrame())
    news         = data.get("news", [])
    edf          = data.get("earnings_dates")
    tv           = data.get("tv", {})
    inv          = data.get("inv", {})
    macro        = data.get("macro", {})
    recs_summary = data.get("recs_summary")

    today = datetime.today().strftime("%Y-%m-%d")
    name  = info.get("longName") or info.get("shortName", ticker)

    # 데이터 소스 배지
    sources = []
    if tv and not tv.get("error"):   sources.append("TradingView")
    if inv and not inv.get("error"): sources.append("Investing.com")
    if macro and macro.get("data"):  sources.append("Trading Economics")
    source_str = " · ".join(["yfinance"] + sources) if sources else "yfinance"

    # ② 애널리스트 컨센서스 (NONE 폴백)
    consensus = _resolve_analyst_consensus(info, recs_summary)

    # ③ 다음 실적 발표일 (미래 날짜만, Investing.com 우선)
    next_earn_inv = inv.get("next_earnings", "")
    next_earn, next_earn_src = _resolve_next_earnings(info, edf, next_earn_inv)

    header = f"""# 📊 {name} ({ticker}) 종합 주식 분석 리포트

> 분석일: {today} | 데이터 소스: {source_str}

---
"""

    # 섹션 4: yfinance 기술분석 + TradingView 보조
    sec4_str = _sec4_technical(tech)
    tv_sec   = _sec4b_tradingview(tv)
    if tv_sec:
        sec4_str = sec4_str.rstrip() + "\n\n" + tv_sec

    # 섹션 6: 산업분석 + 거시경제
    sec6_str  = _sec6_industry(info)
    macro_sec = _sec6b_macro(macro, inv)
    if macro_sec:
        sec6_str = sec6_str.rstrip() + "\n\n" + macro_sec

    takeaways = _sec0_takeaways(
        ticker, info, tech, tv, inv, consensus, next_earn, next_earn_src
    )

    sections = [
        header,
        takeaways,
        _sec1_overview(info, hist),
        _sec2_valuation(info),
        _sec3_financials(inc, bal, cf),
        sec4_str,
        _sec5_earnings(edf, q_inc, info, next_earn, next_earn_src),
        sec6_str,
        _sec7_news(news),
        _sec8_risk(info, tech),
        _sec9_outlook(info, {}, edf, next_earn, next_earn_src, consensus),
        _sec10_verdict(info, {}, tech, {}, tv, inv, consensus),
    ]

    return "\n\n".join(sections)
