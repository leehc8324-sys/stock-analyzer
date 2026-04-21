"""
Pinterest Board Image Downloader — Streamlit App
cookies.txt 업로드 → 보드 URL 입력 → 전체 다운로드
"""

import subprocess
import sys
import shutil
import zipfile
import re
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

# ── 경로 ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "pinterest_downloads"
ARCHIVE_DIR  = BASE_DIR / "pinterest_archives"
DOWNLOAD_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)

# ── 쿠키 파일 파싱 ──────────────────────────────────────
def parse_cookie_file(content: str) -> dict:
    cookies = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies

def get_username_from_cookies(content: str) -> str:
    """쿠키 파일에서 Pinterest 사용자명 추출 시도"""
    cookies = parse_cookie_file(content)
    # _pinterest_sess에 base64로 username이 인코딩돼 있는 경우 있음
    # fallback: 알 수 없음
    return cookies.get("username", "")

# ── gallery-dl ──────────────────────────────────────────
def check_gallery_dl() -> bool:
    if shutil.which("gallery-dl"):
        return True
    r = subprocess.run([sys.executable, "-m", "gallery_dl", "--version"], capture_output=True)
    return r.returncode == 0

def gallery_dl_cmd() -> list[str]:
    return ["gallery-dl"] if shutil.which("gallery-dl") else [sys.executable, "-m", "gallery_dl"]

def install_gallery_dl():
    r = subprocess.run([sys.executable, "-m", "pip", "install", "gallery-dl"],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr

# ── 보드 목록: gallery-dl로 URL 수집 ───────────────────
def list_boards(cookie_path: str, username: str) -> list[dict]:
    """gallery-dl로 프로필에서 보드 URL 목록 추출"""
    cmd = gallery_dl_cmd() + [
        "--cookies", cookie_path,
        "--print", "{board[url]}\t{board[name]}\t{board[pin_count]}",
        "--range", "1-1",   # 보드당 1개만 probe
        f"https://www.pinterest.com/{username}/",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        boards = {}
        for line in r.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 1 and parts[0].startswith("/"):
                url = f"https://www.pinterest.com{parts[0]}"
                name = parts[1] if len(parts) > 1 else parts[0].split("/")[-2]
                pin_count = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                boards[url] = {"name": name, "url": url, "pin_count": pin_count}
        return list(boards.values())
    except Exception:
        return []

# ── 다운로드 ────────────────────────────────────────────
def archive_path(url: str) -> Path:
    import hashlib
    key = hashlib.md5(url.rstrip("/").encode()).hexdigest()[:12]
    return ARCHIVE_DIR / f"{key}.sqlite3"

def archive_count(url: str) -> int:
    p = archive_path(url)
    if not p.exists():
        return 0
    try:
        import sqlite3
        con = sqlite3.connect(str(p))
        n = con.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0

def run_download(url: str, out_dir: Path, cookie_path: str):
    cmd = gallery_dl_cmd() + [
        "--cookies", cookie_path,
        "--destination", str(out_dir),
        "--no-mtime",
        "--retries", "5",
        "--sleep", "0.3",
        "--download-archive", str(archive_path(url)),
        url,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)

# ── 유틸 ────────────────────────────────────────────────
def count_images(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    return [f for f in folder.rglob("*") if f.suffix.lower() in exts]

def zip_directory(folder: Path) -> Path:
    zip_path = folder.parent / f"{folder.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(folder))
    return zip_path

def do_download(url: str, label: str, cookie_path: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[^\w가-힣-]', '_', label)[:40]
    out_dir = DOWNLOAD_DIR / f"{safe}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cached_before = archive_count(url)
    log_box = st.empty()
    status   = st.empty()
    log_lines: list[str] = []

    with st.spinner(f"{label} 다운로드 중..."):
        proc = run_download(url, out_dir, cookie_path)
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            log_lines.append(line)
            if len(log_lines) > 60:
                log_lines = log_lines[-60:]
            log_box.code("\n".join(log_lines), language="")
            n = len(count_images(out_dir))
            if n:
                status.markdown(f"다운로드됨: **{n}장**")
        proc.wait()

    log_box.empty()
    status.empty()

    all_imgs = count_images(out_dir)
    total = len(all_imgs)
    cached_after = archive_count(url)

    if total > 0:
        with st.spinner("ZIP 압축 중..."):
            zip_path = zip_directory(out_dir)
        size_mb = zip_path.stat().st_size // 1024 // 1024
        with open(zip_path, "rb") as zf:
            st.download_button(
                f"📦 {label} ZIP 다운로드 ({total}장 / {size_mb}MB)",
                data=zf, file_name=zip_path.name,
                mime="application/zip", use_container_width=True,
                key=f"zip_{safe}_{ts}",
            )
        st.success(f"✅ {label}: {total}장 완료 (누적 {cached_after}개)")
    else:
        if cached_before > 0:
            st.info(f"✅ {label}: 새 이미지 없음 — 이미 최신 (캐시 {cached_before}개)")
        else:
            st.error(f"❌ {label}: 이미지를 가져오지 못했습니다.")
            if log_lines:
                st.code("\n".join(log_lines[-20:]))


# ════════════════════════════════════════════════════════
# 페이지 설정
# ════════════════════════════════════════════════════════
st.set_page_config(page_title="Pinterest Downloader", page_icon="📌", layout="wide")

if not check_gallery_dl():
    st.warning("`gallery-dl`이 필요합니다.")
    if st.button("📦 설치"):
        with st.spinner("설치 중..."):
            ok, log = install_gallery_dl()
        if ok:
            st.success("완료! 새로고침하세요.")
        else:
            st.error("설치 실패")
            st.code(log)
    st.stop()

for k, v in [("logged_in", False), ("username", ""), ("cookie_path", ""), ("boards", [])]:
    if k not in st.session_state:
        st.session_state[k] = v


# ════════════════════════════════════════════════════════
# 로그인 화면
# ════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.title("📌 Pinterest Downloader")

    col, _ = st.columns([1.4, 1])
    with col:
        st.markdown("### 로그인 (cookies.txt 업로드)")

        components.html("""
        <div style="font-family:-apple-system,sans-serif;line-height:1.8;color:#ddd;
                    background:#1e1e1e;padding:16px;border-radius:8px;">
          <b>① Chrome 확장 설치</b> (한 번만)<br>
          <a href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
             target="_blank"
             style="color:#4af;font-weight:bold;">
            🔧 Get cookies.txt LOCALLY 설치하기 →
          </a><br><br>
          <b>② Pinterest 접속</b> (로그인 상태 확인)<br>
          <b>③ 확장 아이콘 클릭 → Export 버튼 클릭</b><br>
          <b>④ 저장된 .txt 파일을 아래에 업로드</b>
        </div>
        """, height=155)

        st.markdown("")
        uploaded = st.file_uploader("cookies.txt 업로드", type=["txt"],
                                    label_visibility="collapsed")

        username_input = st.text_input(
            "Pinterest 사용자명 (영문, @ 제외)",
            placeholder="예: heechang123",
        )

        login_btn = st.button("로그인", use_container_width=True, type="primary",
                              disabled=uploaded is None)

        if login_btn and uploaded:
            content = uploaded.read().decode("utf-8", errors="ignore")
            cookies = parse_cookie_file(content)

            if "_pinterest_sess" not in cookies:
                st.error("Pinterest 쿠키를 찾을 수 없습니다. pinterest.com 탭에서 Export 하세요.")
            else:
                # 쿠키 파일 임시 저장
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w")
                tmp.write(content)
                tmp.flush()

                username = username_input.strip().lstrip("@") or "me"

                with st.spinner("보드 목록 불러오는 중..."):
                    boards = list_boards(tmp.name, username)

                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.cookie_path = tmp.name
                st.session_state.boards = boards
                st.rerun()
    st.stop()


# ════════════════════════════════════════════════════════
# 메인 화면
# ════════════════════════════════════════════════════════
col_t, col_u, col_lo = st.columns([4, 2, 1])
with col_t:
    st.title("📌 Pinterest Downloader")
with col_u:
    st.markdown(f"<br>**@{st.session_state.username}**", unsafe_allow_html=True)
with col_lo:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("로그아웃"):
        for k in ["logged_in", "username", "cookie_path", "boards"]:
            st.session_state[k] = False if k == "logged_in" else ([] if k == "boards" else "")
        st.rerun()

st.divider()

cookie_path: str = st.session_state.cookie_path
boards: list[dict] = st.session_state.boards
username: str = st.session_state.username

tab1, tab2 = st.tabs(["📋 내 보드", "🔗 URL로 다운로드"])

# ── 탭1: 내 보드 ────────────────────────────────────────
with tab1:
    col_refresh, col_all_dl = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 보드 목록 새로고침"):
            with st.spinner("불러오는 중..."):
                st.session_state.boards = list_boards(cookie_path, username)
            st.rerun()
    with col_all_dl:
        all_dl = st.button("📥 내 전체 보드 일괄 다운로드", type="primary", use_container_width=True)

    if all_dl:
        profile_url = f"https://www.pinterest.com/{username}/"
        st.markdown(f"#### 전체 보드 다운로드 — @{username}")
        do_download(profile_url, f"{username}_all", cookie_path)

    if not boards:
        st.info(f"보드 목록을 불러오려면 **보드 목록 새로고침**을 클릭하세요.\n\n"
                f"또는 URL 탭에서 직접 입력하세요: `https://www.pinterest.com/{username}/보드명/`")
    else:
        st.markdown(f"**총 {len(boards)}개 보드**")
        select_all = st.checkbox("전체 선택")

        selected = []
        rows = [boards[i:i+4] for i in range(0, len(boards), 4)]
        for row in rows:
            cols = st.columns(4)
            for col, b in zip(cols, row):
                with col:
                    cached = archive_count(b["url"])
                    label = f"**{b['name']}**\n핀 {b['pin_count']}개" + (f" · 캐시 {cached}" if cached else "")
                    if st.checkbox(label, value=select_all, key=f"b_{b['url']}"):
                        selected.append(b)

        if st.button("📥 선택 보드 다운로드", type="primary", use_container_width=True):
            if not selected:
                st.warning("보드를 선택하세요.")
            else:
                for b in selected:
                    st.markdown(f"**{b['name']}** ({b['pin_count']}핀)")
                    do_download(b["url"], b["name"], cookie_path)

# ── 탭2: URL 직접 입력 ──────────────────────────────────
with tab2:
    url_input = st.text_input(
        "Pinterest URL",
        value=f"https://www.pinterest.com/{username}/",
        label_visibility="collapsed",
    )
    if st.button("📥 다운로드", type="primary", use_container_width=True):
        url = url_input.strip()
        if not url or ("pinterest" not in url and "pin.it" not in url):
            st.error("올바른 Pinterest URL을 입력하세요.")
        else:
            label = url.rstrip("/").split("/")[-1] or username
            do_download(url, label, cookie_path)
