"""
Pinterest Board Image Downloader — Streamlit App
Pinterest 로그인 → 내 보드 목록 → 선택 다운로드
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

# ── Pinterest 인증 ───────────────────────────────────────
def pinterest_login(email: str, password: str):
    session = requests.Session()
    session.headers.update(HEADERS)

    # CSRF 토큰 획득
    session.get("https://www.pinterest.com/", timeout=15)
    csrf = session.cookies.get("csrftoken", "")

    resp = session.post(
        "https://www.pinterest.com/resource/UserSessionResource/create/",
        headers={**HEADERS, "X-CSRFToken": csrf, "Referer": "https://www.pinterest.com/login/"},
        data={
            "source_url": "/login/",
            "data": json.dumps({
                "options": {"username_or_email": email, "password": password},
                "context": {},
            }),
        },
        timeout=20,
    )

    result = resp.json()
    err = result.get("resource_response", {}).get("error")
    if err:
        return None, None, str(err)

    user = result.get("resource_response", {}).get("data", {})
    username = user.get("username", "")
    return session, username, None


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


# ── 쿠키 → Netscape 형식 저장 ───────────────────────────
def save_cookies(session: requests.Session) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w")
    tmp.write("# Netscape HTTP Cookie File\n")
    for c in session.cookies:
        secure = "TRUE" if c.secure else "FALSE"
        expires = int(c.expires) if c.expires else 0
        domain = c.domain if c.domain.startswith(".") else f".{c.domain}"
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

def run_download(board_url: str, out_dir: Path, cookie_path: str):
    cmd = gallery_dl_cmd() + [
        "--cookies", cookie_path,
        "--destination", str(out_dir),
        "--no-mtime",
        "--retries", "5",
        "--sleep", "0.3",
        "--sleep-request", "0.2",
        board_url,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)


# ════════════════════════════════════════════════════════
# 페이지 설정
# ════════════════════════════════════════════════════════
st.set_page_config(page_title="Pinterest Downloader", page_icon="📌", layout="wide")

# gallery-dl 설치 확인
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

# 세션 초기화
for key, val in [("logged_in", False), ("pinterest_session", None),
                 ("username", ""), ("boards", []), ("cookie_path", "")]:
    if key not in st.session_state:
        st.session_state[key] = val


# ════════════════════════════════════════════════════════
# 로그인 화면
# ════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.title("📌 Pinterest Downloader")

    col, _ = st.columns([1.2, 1])
    with col:
        st.markdown("### 로그인")
        with st.form("login_form"):
            email = st.text_input("이메일", placeholder="example@email.com")
            password = st.text_input("비밀번호", type="password")
            login_btn = st.form_submit_button("로그인", use_container_width=True)

        if login_btn:
            if not email or not password:
                st.error("이메일과 비밀번호를 입력하세요.")
            else:
                with st.spinner("로그인 중..."):
                    sess, username, err = pinterest_login(email, password)

                if err or not sess:
                    st.error(f"로그인 실패: {err or '알 수 없는 오류'}")
                else:
                    with st.spinner("보드 목록 불러오는 중..."):
                        boards = get_boards(sess, username)
                        cookie_path = save_cookies(sess)

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
        for key in ["logged_in", "pinterest_session", "username", "boards", "cookie_path"]:
            st.session_state[key] = False if key == "logged_in" else ([] if key == "boards" else "")
        st.rerun()

st.divider()

boards: list[dict] = st.session_state.boards
tab1, tab2 = st.tabs(["📋 내 보드", "🔗 URL로 다운로드"])

# ── 탭1: 내 보드 목록 ───────────────────────────────────
with tab1:
    if not boards:
        st.info("보드가 없거나 불러오지 못했습니다.")
    else:
        st.markdown(f"**총 {len(boards)}개 보드**")

        # 전체 선택
        col_all, col_dl = st.columns([3, 1])
        with col_all:
            select_all = st.checkbox("전체 선택")
        with col_dl:
            batch_btn = st.button("📥 선택 보드 일괄 다운로드", use_container_width=True, type="primary")

        st.markdown("---")

        # 보드 그리드 (4열)
        selected_boards = []
        cols_per_row = 4
        rows = [boards[i:i+cols_per_row] for i in range(0, len(boards), cols_per_row)]

        for row in rows:
            cols = st.columns(cols_per_row)
            for col, board in zip(cols, row):
                with col:
                    board_name = board.get("name", "")
                    pin_count = board.get("pin_count", 0)
                    board_url = f"https://www.pinterest.com{board.get('url', '')}"

                    # 커버 이미지
                    cover = (board.get("image_cover_url") or
                             board.get("cover_images", {}).get("736x", {}).get("url", ""))
                    if cover:
                        try:
                            st.image(cover, use_container_width=True)
                        except Exception:
                            st.markdown("🖼️")
                    else:
                        st.markdown("🖼️")

                    checked = st.checkbox(
                        f"**{board_name}**  \n핀 {pin_count}개",
                        value=select_all,
                        key=f"board_{board.get('id', board_name)}",
                    )
                    if checked:
                        selected_boards.append((board_name, board_url, pin_count))

        # 일괄 다운로드
        if batch_btn:
            if not selected_boards:
                st.warning("보드를 선택하세요.")
            else:
                st.markdown(f"### 다운로드 시작 ({len(selected_boards)}개 보드)")
                cookie_path = st.session_state.cookie_path

                for idx, (bname, burl, bpins) in enumerate(selected_boards):
                    st.markdown(f"**[{idx+1}/{len(selected_boards)}] {bname}** ({bpins}핀)")
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out_dir = DOWNLOAD_DIR / f"{bname}_{ts}"
                    out_dir.mkdir(parents=True, exist_ok=True)

                    log_box = st.empty()
                    status = st.empty()
                    log_lines: list[str] = []

                    with st.spinner(f"{bname} 다운로드 중..."):
                        proc = run_download(burl, out_dir, cookie_path)
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

                    if total > 0:
                        with st.spinner("ZIP 압축 중..."):
                            zip_path = zip_directory(out_dir)
                        size_mb = zip_path.stat().st_size // 1024 // 1024
                        with open(zip_path, "rb") as zf:
                            st.download_button(
                                f"📦 {bname} ZIP ({total}장 / {size_mb}MB)",
                                data=zf,
                                file_name=zip_path.name,
                                mime="application/zip",
                                use_container_width=True,
                                key=f"zip_dl_{bname}_{ts}",
                            )
                        st.success(f"✅ {bname}: {total}장 완료")
                    else:
                        st.error(f"❌ {bname}: 이미지를 가져오지 못했습니다.")


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
                        data=zf,
                        file_name=zip_path.name,
                        mime="application/zip",
                        use_container_width=True,
                    )
            else:
                st.error("이미지를 가져오지 못했습니다.")
                st.code("\n".join(log_lines))
