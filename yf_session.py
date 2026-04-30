"""
yfinance 공유 캐시 세션 — requests_cache 기반
- 동일 URL 30분 이내 재요청 시 HTTP 호출 없이 캐시 반환
- 여러 모듈에서 같은 Ticker 데이터 중복 조회 방지
- SQLite 캐시 파일: ~/.yf_cache/yf_cache.sqlite
"""
import os
from pathlib import Path

_session = None   # 모듈 레벨 싱글톤

def get_yf_session(ttl_seconds: int = 1800):
    """
    requests_cache.CachedSession 싱글톤 반환.
    requests-cache 미설치 시 일반 requests.Session 반환 (graceful fallback).
    """
    global _session
    if _session is not None:
        return _session

    cache_dir = Path.home() / ".yf_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = str(cache_dir / "yf_cache")

    try:
        import requests_cache
        _session = requests_cache.CachedSession(
            cache_path,
            expire_after=ttl_seconds,
            # Yahoo Finance 429 응답도 캐시하지 않도록
            allowable_codes=[200, 404],
        )
    except ImportError:
        import requests
        _session = requests.Session()

    # 브라우저처럼 보이게 User-Agent 설정
    _session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return _session


def make_ticker(ticker: str):
    """캐시 세션을 사용하는 yf.Ticker 생성"""
    import yfinance as yf
    return yf.Ticker(ticker, session=get_yf_session())
