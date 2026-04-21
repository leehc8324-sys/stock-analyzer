"""
Pinterest Board Image Downloader — Streamlit App
쿠키 세션 로그인 → 내 보드 목록 → 선택 다운로드
"""

import subprocess
import sys
import shutil
import zipfile
import json
import tempfile
import time
from pathlib import Path
from datetime import datetime

import requests
import streamlit as st
import streamlit.components.v1 as components

# ── 경로 ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "pinterest_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

# ── 쿠키 파일 파싱 ──────────────────────────────────────
def parse_cookie_file(content: str) -> dict:
    """Netscape cookies.txt → {name: value} dict"""
    cookies = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies

# ── 쿠키 파일로 로그인 ──────────────────────────────────
def login_with_cookie(cookie_content: str):
    """cookies.txt 전체 내용으로 인증된 세션 생성"""
    cookies = parse_cookie_file(cookie_content)

    if "_pinterest_sess" not in cookies:
        return None, None, "_pinterest_sess 쿠키를 찾을 수 없습니다."

    session = requests.Session()
    session.headers.update(HEADERS)

    # 모든 쿠키 세션에 등록
    for name, value in cookies.items():
        domain = ".pinterest.com"
        session.cookies.set(name, value, domain=domain)

    # 로그인 확인 — 홈 페이지에서 username 추출
    try:
        resp = session.get(
            "https://www.pinterest.com/resource/UserResource/get/",
            params={
                "source_url": "/",
                "data": json.dumps({"options": {"field_set_key": "unambiguous_minimal"}, "context": {}}),
                "_": str(int(time.time() * 1000)),
            },
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200 and resp.text.strip():
            data = resp.json().get("resource_response", {})
            username = (data.get("data") or {}).get("username", "")
            if username:
                return session, username, None
    except Exception:
        pass

    # 대안: 메인 페이지 HTML에서 username 추출
    try:
        resp = session.get("https://www.pinterest.com/", timeout=15)
        import re
        match = re.search(r'"username"\s*:\s*"([^"]+)"', resp.text)
        if match:
            return session, match.group(1), None
    except Exception:
        pass

    return None, None, "로그인 확인 실패. 쿠키가 만료되었을 수 있습니다."


# ── 보드 목록 조회 ──────────────────────────────────────
def get_boards(session: requests.Session, username: str) -> list[dict]:
    boards = []
    bookmark = None
    while True:
        options = {
            "username": username,
            "field_set_key": "profile_grid_item",
            "group_by": "visibility",
            "filter_stories": False,
            "page_size": 50,
        }
        if bookmark:
            options["bookmarks"] = [bookmark]

        resp = session.get(
            "https://www.pinterest.com/resource/BoardsResource/get/",
            params={
                "source_url": f"/{username}/",
                "data": json.dumps({"options": options, "context": {}}),
                "_": str(int(time.time() * 1000)),
            },
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json().get("resource_response", {})
        boards += data.get("data", [])
        bookmark = data.get("bookmark")
        if not bookmark or bookmark == "-end-":
            break
    return boards


# ── 쿠키 파일 저장 (gallery-dl용) ──────────────────────
def save_cookies(session: requests.Session) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w")
    tmp.write("# Netscape HTTP Cookie File\n")
    for c in session.cookies:
        domain = c.domain if c.domain.startswith(".") else f".{c.domain}"
        secure = "TRUE" if c.secure else "FALSE"
        expires = int(c.expires) if c.expires else 0
        tmp.write(f"{domain}\tTRUE\t{c.path}\t{secure}\t{expires}\t{c.name}\t{c.value}\n")
    tmp.flush()
    return tmp.name


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

ARCHIVE_DIR = BASE_DIR / "pinterest_archives"
ARCHIVE_DIR.mkdir(exist_ok=True)

def archive_path_for(url: str) -> Path:
    """보드 URL → 고유 archive 파일 경로 (재실행 시 중복 방지)"""
    import hashlib
    key = hashlib.md5(url.rstrip("/").encode()).hexdigest()[:12]
    return ARCHIVE_DIR / f"{key}.sqlite3"

def run_download(url: str, out_dir: Path, cookie_path: str):
    archive = archive_path_for(url)
    cmd = gallery_dl_cmd() + [
        "--cookies", cookie_path,
        "--destination", str(out_dir),
        "--no-mtime",
        "--retries", "5",
        "--sleep", "0.3",
        "--download-archive", str(archive),  # 이미 받은 파일 스킵
        url,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)

def archive_count(url: str) -> int:
    """아카이브에 기록된 기존 다운로드 수"""
    p = archive_path_for(url)
    if not p.exists():
        return 0
    try:
        import sqlite3
        con = sqlite3.connect(str(p))
        count = con.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0


# ── 유틸 ────────────────────────────────────────────────
def folder_from_url(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/")
             if p and "pinterest" not in p and "http" not in p]
    return "_".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "board")

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

for key, val in [("logged_in", False), ("pinterest_session", None),
                 ("username", ""), ("boards", []), ("cookie_path", "")]:
    if key not in st.session_state:
        st.session_state[key] = val


# ════════════════════════════════════════════════════════
# 로그인 화면
# ════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.title("📌 Pinterest Downloader")

    col, _ = st.columns([1.4, 1])
    with col:
        st.markdown("### Pinterest 로그인")
        st.markdown("Google 로그인 포함, 모든 방식 지원")
        st.divider()

        st.markdown("#### 방법: 쿠키 파일 업로드")

        components.html("""
        <div style="font-family:-apple-system,sans-serif;line-height:1.7;color:#222;">
          <p style="margin:0 0 8px 0"><b>① Chrome 확장 설치</b> (한 번만)</p>
          <a href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
             target="_blank"
             style="display:inline-block;padding:9px 18px;background:#4285F4;color:white;
                    border-radius:7px;text-decoration:none;font-weight:bold;font-size:14px;">
            🔧 Get cookies.txt LOCALLY 설치
          </a>
          <br><br>
          <p style="margin:0 0 4px 0"><b>② Pinterest 접속</b> — 로그인 상태 확인</p>
          <p style="margin:0 0 4px 0"><b>③ 확장 아이콘 클릭</b> → <b>Export</b> 버튼 클릭</p>
          <p style="margin:0 0 4px 0"><b>④ 저장된 <code>pinterest.com_cookies.txt</code> 파일을 아래에 업로드</b></p>
        </div>
        """, height=185)

        uploaded = st.file_uploader(
            "cookies.txt 파일 업로드",
            type=["txt"],
            label_visibility="collapsed",
        )

        login_btn = st.button("로그인", use_container_width=True, type="primary",
                              disabled=uploaded is None)

        if login_btn and uploaded:
            content = uploaded.read().decode("utf-8", errors="ignore")

            with st.spinner("로그인 확인 중..."):
                sess, username, err = login_with_cookie(content)

            if err or not sess:
                st.error(f"로그인 실패: {err}")
            else:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w")
                tmp.write(content)
                tmp.flush()
                cookie_path = tmp.name

                with st.spinner(f"@{username} 보드 불러오는 중..."):
                    boards = get_boards(sess, username)

                st.session_state.logged_in = True
                st.session_state.pinterest_session = sess
                st.session_state.username = username
                st.session_state.boards = boards
                st.session_state.cookie_path = cookie_path
                st.rerun()
    st.stop()


# ════════════════════════════════════════════════════════
# 메인 화면
# ════════════════════════════════════════════════════════
col_title, col_user, col_logout = st.columns([4, 2, 1])
with col_title:
    st.title("📌 Pinterest Downloader")
with col_user:
    st.markdown(f"<br>**@{st.session_state.username}**", unsafe_allow_html=True)
with col_logout:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("로그아웃"):
        for k in ["logged_in", "pinterest_session", "username", "boards", "cookie_path"]:
            st.session_state[k] = False if k == "logged_in" else ([] if k == "boards" else "")
        st.rerun()

st.divider()

boards: list[dict] = st.session_state.boards
tab1, tab2 = st.tabs(["📋 내 보드", "🔗 URL로 다운로드"])

# ── 탭1: 내 보드 ────────────────────────────────────────
with tab1:
    if not boards:
        st.info("보드가 없거나 불러오지 못했습니다.")
    else:
        col_info, col_btn = st.columns([3, 1])
        with col_info:
            st.markdown(f"**총 {len(boards)}개 보드**")
        with col_btn:
            batch_btn = st.button("📥 선택 보드 일괄 다운로드", use_container_width=True, type="primary")

        select_all = st.checkbox("전체 선택")
        st.markdown("---")

        selected_boards = []
        cols_per_row = 4
        rows = [boards[i:i+cols_per_row] for i in range(0, len(boards), cols_per_row)]

        for row in rows:
            cols = st.columns(cols_per_row)
            for col, board in zip(cols, row):
                with col:
                    bname = board.get("name", "")
                    pin_count = board.get("pin_count", 0)
                    burl = f"https://www.pinterest.com{board.get('url', '')}"
                    cover = (board.get("image_cover_url") or
                             board.get("cover_images", {}).get("736x", {}).get("url", ""))
                    if cover:
                        try:
                            st.image(cover, use_container_width=True)
                        except Exception:
                            st.markdown("🖼️")
                    else:
                        st.markdown("🖼️")

                    cached = archive_count(burl)
                    label = (f"**{bname}**  \n핀 {pin_count}개"
                             + (f" · 캐시 {cached}개" if cached else ""))
                    checked = st.checkbox(
                        label,
                        value=select_all,
                        key=f"board_{board.get('id', bname)}",
                    )
                    if checked:
                        selected_boards.append((bname, burl, pin_count))

        if batch_btn:
            if not selected_boards:
                st.warning("보드를 선택하세요.")
            else:
                st.markdown(f"### 다운로드 ({len(selected_boards)}개 보드)")
                for idx, (bname, burl, bpins) in enumerate(selected_boards):
                    st.markdown(f"**[{idx+1}/{len(selected_boards)}] {bname}** ({bpins}핀)")
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_dir = DOWNLOAD_DIR / f"{bname}_{ts}"
                    out_dir.mkdir(parents=True, exist_ok=True)

                    log_box = st.empty()
                    status = st.empty()
                    log_lines: list[str] = []

                    with st.spinner(f"{bname} 다운로드 중..."):
                        proc = run_download(burl, out_dir, st.session_state.cookie_path)
                        for line in proc.stdout:
                            line = line.rstrip()
                            if not line:
                                continue
                            log_lines.append(line)
                            if len(log_lines) > 50:
                                log_lines = log_lines[-50:]
                            log_box.code("\n".join(log_lines), language="")
                            n = len(count_images(out_dir))
                            if n:
                                status.markdown(f"다운로드됨: {n}장")
                        proc.wait()

                    all_imgs = count_images(out_dir)
                    total = len(all_imgs)
                    log_box.empty()
                    status.empty()

                    if total > 0:
                        cached_after = archive_count(burl)
                        with st.spinner("ZIP 압축 중..."):
                            zip_path = zip_directory(out_dir)
                        size_mb = zip_path.stat().st_size // 1024 // 1024
                        with open(zip_path, "rb") as zf:
                            st.download_button(
                                f"📦 {bname} ZIP ({total}장 / {size_mb}MB)",
                                data=zf, file_name=zip_path.name,
                                mime="application/zip", use_container_width=True,
                                key=f"zip_{bname}_{ts}",
                            )
                        st.success(f"✅ {bname}: {total}장 완료 (누적 캐시: {cached_after}개)")
                    else:
                        cached_n = archive_count(burl)
                        if cached_n > 0:
                            st.info(f"✅ {bname}: 새 이미지 없음 (기존 캐시 {cached_n}개 — 이미 최신)")
                        else:
                            st.error(f"❌ {bname}: 실패")

# ── 탭2: URL 직접 입력 ──────────────────────────────────
with tab2:
    board_url = st.text_input(
        "Pinterest URL",
        placeholder="https://www.pinterest.com/username/boardname/",
        label_visibility="collapsed",
    )
    dl_btn = st.button("📥 다운로드", use_container_width=True, type="primary")

    if dl_btn:
        url = board_url.strip()
        if not url:
            st.error("URL을 입력하세요.")
        elif "pinterest" not in url and "pin.it" not in url:
            st.error("Pinterest URL을 입력하세요.")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = DOWNLOAD_DIR / f"{folder_from_url(url)}_{ts}"
            out_dir.mkdir(parents=True, exist_ok=True)
            log_box = st.empty()
            status = st.empty()
            log_lines = []

            with st.spinner("다운로드 중..."):
                proc = run_download(url, out_dir, st.session_state.cookie_path)
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    log_lines.append(line)
                    if len(log_lines) > 80:
                        log_lines = log_lines[-80:]
                    log_box.code("\n".join(log_lines), language="")
                    n = len(count_images(out_dir))
                    if n:
                        status.markdown(f"**다운로드됨: {n}장**")
                proc.wait()

            all_imgs = count_images(out_dir)
            total = len(all_imgs)
            log_box.empty()

            if total > 0:
                st.success(f"✅ 총 **{total}장** 완료!")
                with st.expander("미리보기", expanded=True):
                    pcols = st.columns(4)
                    for i, img in enumerate(sorted(all_imgs)[:16]):
                        with pcols[i % 4]:
                            try:
                                st.image(str(img), use_container_width=True)
                            except Exception:
                                st.text(img.name)
                with st.spinner("ZIP 압축 중..."):
                    zip_path = zip_directory(out_dir)
                size_mb = zip_path.stat().st_size // 1024 // 1024
                with open(zip_path, "rb") as zf:
                    st.download_button(
                        f"📦 ZIP 다운로드 ({total}장 / {size_mb}MB)",
                        data=zf, file_name=zip_path.name,
                        mime="application/zip", use_container_width=True,
                    )
            else:
                st.error("이미지를 가져오지 못했습니다.")
                st.code("\n".join(log_lines))
