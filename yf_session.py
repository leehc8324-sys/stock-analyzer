"""
yfinance 캐시 헬퍼 (pickle 파일 기반, requests-cache 미사용)
- yfinance >= 0.2.x 는 내부적으로 curl_cffi 사용 → 외부 session 주입 불가
- 대신 .info 결과를 pickle 파일로 캐시 (TTL 30분)
- ~/.yf_cache/{TICKER}_info.pkl
"""
import pickle, time, yfinance as yf
from pathlib import Path

_CACHE_DIR = Path.home() / ".yf_cache"
_CACHE_DIR.mkdir(exist_ok=True)
_DEFAULT_TTL = 1800   # 30분


def make_ticker(ticker: str) -> yf.Ticker:
    """session 없이 yf.Ticker 반환 — curl_cffi 호환"""
    return yf.Ticker(ticker)


def get_cached_info(ticker: str, ttl: int = _DEFAULT_TTL) -> dict:
    """
    yfinance .info 결과를 파일 캐시에서 반환.
    캐시 미스 or TTL 초과 시 yfinance 호출 후 저장.
    """
    safe_name  = ticker.replace("/", "_").replace(".", "_")
    cache_file = _CACHE_DIR / f"{safe_name}_info.pkl"

    # ── 캐시 히트 확인
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < ttl:
            try:
                with open(cache_file, "rb") as f:
                    data = pickle.load(f)
                if data:          # 빈 dict 제외
                    return data
            except Exception:
                pass              # 파일 손상 → 새로 fetch

    # ── 실제 fetch (retry 포함)
    info = _fetch_with_retry(ticker)

    # ── 파일에 저장
    try:
        with open(cache_file, "wb") as f:
            pickle.dump(info, f)
    except Exception:
        pass

    return info


def _fetch_with_retry(ticker: str, retries: int = 3, base_wait: float = 5.0) -> dict:
    last_err = None
    for i in range(retries):
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info
            if info:
                return info
        except Exception as e:
            last_err = e
            msg = str(e)
            if "Too Many Requests" in msg or "Rate" in msg or "429" in msg:
                if i < retries - 1:
                    time.sleep(base_wait * (i + 1))   # 5s → 10s → 15s
                    continue
            raise
    raise RuntimeError(
        f"Yahoo Finance 레이트 리밋 ({retries}회 재시도 실패). "
        f"1~2분 후 다시 시도해주세요. 마지막 오류: {last_err}"
    )


def clear_cache(ticker: str = None):
    """캐시 파일 삭제 (ticker=None 이면 전체 삭제)"""
    if ticker:
        safe = ticker.replace("/", "_").replace(".", "_")
        f = _CACHE_DIR / f"{safe}_info.pkl"
        if f.exists():
            f.unlink()
    else:
        for f in _CACHE_DIR.glob("*.pkl"):
            f.unlink()
