"""
외부 금융 사이트 스크래퍼
- TradingView  : Scanner API  → 기술적 지표 & 추천 요약
- Investing.com: __NEXT_DATA__ → Fundamental / 타임프레임 기술 등급 / 실적일
- Trading Economics: HTML 스크래핑 → 거시경제 지표
"""

import re, json, warnings
from datetime import datetime

import requests as _req

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────
#  공통 헬퍼
# ─────────────────────────────────────────────────
def _is_korean(ticker: str) -> bool:
    t = ticker.upper()
    return t.endswith(".KS") or t.endswith(".KQ")

def _kr_code(ticker: str) -> str:
    return ticker.split(".")[0]

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ═════════════════════════════════════════════════
#  1. TRADINGVIEW  — Scanner API
# ═════════════════════════════════════════════════
_TV_US_EXCHANGE = {          # 주요 미장 거래소 매핑 (yfinance exchange → TV prefix)
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
    "NYQ": "NYSE",   "NYS": "NYSE",
    "ASE": "AMEX",
    "PCX": "NYSE",
}
_TV_COLUMNS = [
    "name", "close", "change",
    "Recommend.All", "Recommend.MA", "Recommend.Other",
    "RSI", "RSI[1]",
    "MACD.macd", "MACD.signal",
    "Mom", "AO",
    "BB.upper", "BB.lower",
    "Stoch.K", "Stoch.D",
    "CCI20",
    "W.R",
    "ATR",
    "SMA20", "SMA50", "SMA200",
    "EMA20", "EMA50",
    "High.All", "Low.All",
    "volume",
    "market_cap_basic",
]

def _tv_recommend_label(val) -> str:
    """Recommend.All 수치 → 텍스트 레이블"""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if   v >=  0.5: return "🟢 강한 매수"
        elif v >=  0.1: return "🟢 매수"
        elif v >= -0.1: return "🟡 중립"
        elif v >= -0.5: return "🔴 매도"
        else:           return "🔴 강한 매도"
    except Exception:
        return str(val)

def fetch_tradingview(ticker: str, yf_exchange: str = "") -> dict:
    """
    TradingView Scanner API → 기술적 지표 dict 반환
    반환 키: recommend_all, recommend_ma, recommend_oscillators,
             rsi, macd, macd_signal, stoch_k, stoch_d, cci, momentum,
             bb_upper, bb_lower, williams_r, atr,
             sma20, sma50, sma200, ema20, ema50,
             raw (원본 dict)
    """
    # ── 거래소 결정
    if _is_korean(ticker):
        market  = "korea"
        tv_sym  = f"KRX:{_kr_code(ticker)}"
    else:
        market  = "america"
        prefix  = _TV_US_EXCHANGE.get(yf_exchange, "NASDAQ")
        tv_sym  = f"{prefix}:{ticker}"

    url     = f"https://scanner.tradingview.com/{market}/scan"
    payload = {
        "symbols": {"tickers": [tv_sym], "query": {"types": []}},
        "columns": _TV_COLUMNS,
    }
    try:
        r = _req.post(url, json=payload, timeout=10,
                      headers={"User-Agent": "Mozilla/5.0",
                                "Content-Type": "application/json"})
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            return {}
        vals = rows[0]["d"]
        d    = dict(zip(_TV_COLUMNS, vals))
    except Exception as e:
        return {"error": str(e)}

    rec_all = d.get("Recommend.All")
    return {
        "source":               "TradingView",
        "symbol":               tv_sym,
        "recommend_all":        _tv_recommend_label(rec_all),
        "recommend_all_raw":    rec_all,
        "recommend_ma":         _tv_recommend_label(d.get("Recommend.MA")),
        "recommend_oscillators":_tv_recommend_label(d.get("Recommend.Other")),
        "rsi":                  _safe(lambda: round(float(d["RSI"]), 2)),
        "rsi_prev":             _safe(lambda: round(float(d["RSI[1]"]), 2)),
        "macd":                 _safe(lambda: round(float(d["MACD.macd"]), 4)),
        "macd_signal":          _safe(lambda: round(float(d["MACD.signal"]), 4)),
        "momentum":             _safe(lambda: round(float(d["Mom"]), 4)),
        "awesome_osc":          _safe(lambda: round(float(d["AO"]), 4)),
        "stoch_k":              _safe(lambda: round(float(d["Stoch.K"]), 2)),
        "stoch_d":              _safe(lambda: round(float(d["Stoch.D"]), 2)),
        "cci":                  _safe(lambda: round(float(d["CCI20"]), 2)),
        "williams_r":           _safe(lambda: round(float(d["W.R"]), 2)),
        "atr":                  _safe(lambda: round(float(d["ATR"]), 4)),
        "bb_upper":             _safe(lambda: round(float(d["BB.upper"]), 2)),
        "bb_lower":             _safe(lambda: round(float(d["BB.lower"]), 2)),
        "sma20":                _safe(lambda: round(float(d["SMA20"]), 2)),
        "sma50":                _safe(lambda: round(float(d["SMA50"]), 2)),
        "sma200":               _safe(lambda: round(float(d["SMA200"]), 2)),
        "ema20":                _safe(lambda: round(float(d["EMA20"]), 2)),
        "ema50":                _safe(lambda: round(float(d["EMA50"]), 2)),
        "volume":               _safe(lambda: int(d["volume"])),
        "raw":                  d,
    }


# ═════════════════════════════════════════════════
#  2. INVESTING.COM  — __NEXT_DATA__ 파싱
# ═════════════════════════════════════════════════
_INV_TIMEFRAME_LABELS = {
    "PT1M": "1분", "PT5M": "5분", "PT15M": "15분", "PT30M": "30분",
    "PT1H": "1시간", "PT5H": "5시간",
    "P1D": "일봉", "P1W": "주봉", "P1M": "월봉",
}
_INV_RATING_KO = {
    "strong_buy": "🟢 강한 매수", "buy": "🟢 매수",
    "neutral": "🟡 중립",
    "sell": "🔴 매도", "strong_sell": "🔴 강한 매도",
}

def _inv_search(query: str):
    """티커/종목명으로 Investing.com instrument 검색 → {id, url, description}"""
    try:
        from curl_cffi import requests as cf
        r = cf.get(
            f"https://api.investing.com/api/search/v2/search?q={query}&domain_id=1&lang_id=18",
            impersonate="chrome120",
            headers={"Accept": "application/json", "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=10,
        )
        quotes = r.json().get("quotes", [])
        # EQUITY 우선, 거래소 일치 우선
        for q in quotes:
            if q.get("type", "").startswith("Stock"):
                return q
        return quotes[0] if quotes else None
    except Exception:
        return None

def fetch_investing(ticker: str) -> dict:
    """
    Investing.com __NEXT_DATA__ 파싱
    반환 키: price_last, change, fundamental{eps,dividend,yield,pe,revenue,mktcap,1yr_return},
             technical_summary{timeframe:rating}, next_earnings, beta
    """
    try:
        from curl_cffi import requests as cf
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "curl_cffi/beautifulsoup4 미설치"}

    # 검색 쿼리 결정
    query = _kr_code(ticker) if _is_korean(ticker) else ticker
    inst  = _inv_search(query)
    if not inst:
        return {"error": f"Investing.com 에서 {ticker} 를 찾을 수 없음"}

    url = "https://kr.investing.com" + inst["url"]
    try:
        r = cf.get(url, impersonate="chrome120",
                   headers={"Accept-Language": "ko-KR,ko;q=0.9"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return {"error": "NEXT_DATA 없음"}
        nd  = json.loads(script.string)
        eq  = nd["props"]["pageProps"]["state"]["equityStore"]["instrument"]
    except Exception as e:
        return {"error": str(e)}

    price   = eq.get("price", {})
    fund    = eq.get("fundamental", {})
    tech    = eq.get("technical", {})
    perf    = eq.get("performance", {})
    earn    = eq.get("earnings", {})

    # 타임프레임별 기술 등급
    tech_summary = {}
    for tf_key, tf_label in _INV_TIMEFRAME_LABELS.items():
        raw = tech.get("summary", {}).get(tf_key)
        if raw:
            tech_summary[tf_label] = _INV_RATING_KO.get(raw, raw)

    # 다음 실적 날짜 포맷
    next_earn = ""
    if earn.get("nextReport"):
        try:
            dt = datetime.fromisoformat(str(earn["nextReport"]).replace(" ", "T"))
            next_earn = dt.strftime("%Y-%m-%d")
        except Exception:
            next_earn = str(earn.get("nextReport", ""))[:10]

    return {
        "source":         "Investing.com",
        "name":           inst.get("description", ""),
        "exchange":       inst.get("exchange", ""),
        "url":            url,
        "price_last":     _safe(lambda: float(price["last"])),
        "change":         _safe(lambda: float(price["change"])),
        "fundamental": {
            "eps":          _safe(lambda: float(fund["eps"])),
            "dividend":     _safe(lambda: float(fund["dividend"])),
            "div_yield_pct":_safe(lambda: float(fund["yield"])),
            "pe_ratio":     _safe(lambda: float(fund["ratio"])),
            "revenue":      _safe(lambda: float(fund["revenueRaw"])),
            "market_cap":   _safe(lambda: float(fund["marketCapRaw"])),
            "shares_out":   _safe(lambda: int(fund["sharesOutstanding"])),
            "one_year_return_pct": _safe(lambda: float(fund["oneYearReturn"])),
        },
        "technical_summary": tech_summary,
        "daily_rating":   tech_summary.get("일봉", "N/A"),
        "beta":           _safe(lambda: float(perf["beta"])),
        "next_earnings":  next_earn,
    }


# ═════════════════════════════════════════════════
#  3. TRADING ECONOMICS  — 거시경제 지표
# ═════════════════════════════════════════════════
_TE_COUNTRY_MAP = {
    "United States": "united-states",
    "USA":           "united-states",
    "US":            "united-states",
    "South Korea":   "south-korea",
    "Korea":         "south-korea",
    "China":         "china",
    "Japan":         "japan",
    "Germany":       "germany",
    "United Kingdom":"united-kingdom",
    "UK":            "united-kingdom",
}
# 화이트리스트: 페이지 표시 텍스트 → 리포트 표시 이름
# 주가와 상관관계 높은 거시지표만 엄선
_TE_WHITELIST = {
    # 금리
    "이자율":                    "기준금리",
    "금리":                      "기준금리",
    "유효 연방기금 금리":         "실효 기준금리",
    # 물가
    "물가상승률":                "CPI(소비자물가)",
    "인플레이션율":              "인플레이션",
    "인플레이션율(월별)":        "인플레이션(월별)",
    "소비자 물가 지수":          "CPI",
    "핵심 소비자 물가":          "근원 CPI",
    "핵심 PCE 물가 지수 연간 변화": "근원 PCE(연간)",
    # GDP
    "GDP 성장률":                "GDP 성장률(분기)",
    "GDP 연간 성장률":           "GDP 성장률(연간)",
    "국내 총생산":               "GDP(십억달러)",
    # 고용
    "실업률":                    "실업률",
    "비 농장 급여":              "비농업고용(천명)",
    "주간신규실업수당신청건수":   "신규실업수당청구",
    "ADP 고용변화":              "ADP 고용변화",
    # 경기선행·심리
    "제조업 PMI":                "제조업 PMI",
    "복합 구매관리자지수(PMI)":  "복합 PMI",
    "소비자 신뢰지수":           "소비자신뢰지수",
    # 시장·환율
    "통화":                      "환율",
    "주식 시장":                 "증시지수",
    # 무역·재정
    "무역수지":                  "무역수지",
    "경상수지":                  "경상수지",
    "GDP 대비 정부 부채":        "국가부채(%GDP)",
    "정부 부채":                 "국가부채(%GDP)",
}

# BBL 등 단위 오번역 방지
_UNIT_SANITIZE = {
    "BBL/D/1K": "천 배럴/일",
    "BBL":      "배럴",
    "암살":     "배럴",      # 번역 오류 방지
}

def _clean_unit(unit: str) -> str:
    for bad, good in _UNIT_SANITIZE.items():
        unit = unit.replace(bad, good)
    return unit

def fetch_trading_economics(country: str = "United States") -> dict:
    """
    Trading Economics /indicators 페이지 스크래핑
    반환: {지표명: {"현재값": ..., "이전값": ..., "단위": ..., "업데이트": ...}}
    """
    slug = _TE_COUNTRY_MAP.get(country, country.lower().replace(" ", "-"))
    url  = f"https://ko.tradingeconomics.com/{slug}/indicators"
    hdrs = {
        "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        r = _req.get(url, headers=hdrs, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return {"error": str(e)}

    result = {}
    for table in soup.select("table"):
        rows = table.select("tr")
        if not rows:
            continue
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells:
                continue
            name = cells[0] if cells else ""
            # 화이트리스트에 있는 지표만 수집
            if name not in _TE_WHITELIST:
                continue
            label = _TE_WHITELIST[name]
            if label in result:          # 중복 방지 (첫 번째 값 유지)
                continue
            result[label] = {
                "현재값":   cells[1] if len(cells) > 1 else "N/A",
                "이전값":   cells[2] if len(cells) > 2 else "N/A",
                "단위":     _clean_unit(cells[-2]) if len(cells) > 4 else "",
                "업데이트": cells[-1] if len(cells) > 3 else "",
            }

    return {
        "source":   "Trading Economics",
        "country":  country,
        "url":      url,
        "data":     result,
    }


# ═════════════════════════════════════════════════
#  통합 수집 함수
# ═════════════════════════════════════════════════
def fetch_external_data(ticker: str, yf_exchange: str = "", country: str = "") -> dict:
    """
    세 소스를 병렬로 수집 → 통합 dict 반환
    {tradingview: {...}, investing: {...}, macro: {...}}
    """
    import concurrent.futures

    # 국가 결정
    if not country:
        country = "South Korea" if _is_korean(ticker) else "United States"

    def _tv():
        return fetch_tradingview(ticker, yf_exchange)

    def _inv():
        return fetch_investing(ticker)

    def _te():
        return fetch_trading_economics(country)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        fut_tv  = ex.submit(_tv)
        fut_inv = ex.submit(_inv)
        fut_te  = ex.submit(_te)
        tv   = fut_tv.result(timeout=20)
        inv  = fut_inv.result(timeout=20)
        macro= fut_te.result(timeout=20)

    return {"tradingview": tv, "investing": inv, "macro": macro}
