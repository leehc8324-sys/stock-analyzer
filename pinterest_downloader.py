"""
Pinterest Board Image Downloader — Streamlit App
gallery-dl 기반 | Pinterest 로그인 + 보드 전체 다운로드
"""

import subprocess
import sys
import shutil
import zipfile
import json
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st

# ── 경로 ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "pinterest_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

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

def make_config(username: str, password: str) -> str:
    """gallery-dl 임시 설정 파일 생성 (로그인 정보 포함)"""
    config = {
        "extractor": {
            "pinterest": {
                "username": username,
                "password": password,
            }
        }
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
    json.dump(config, tmp)
    tmp.flush()
    return tmp.name

# ── 페이지 설정 ─────────────────────────────────────────
st.set_page_config(page_title="Pinterest Downloader", page_icon="📌", layout="centered")

# ── gallery-dl 설치 체크 ────────────────────────────────
if not check_gallery_dl():
    st.warning("`gallery-dl`이 필요합니다.")
    if st.button("📦 설치"):
        with st.spinner("설치 중..."):
            ok, log = install_gallery_dl()
        if ok:
            st.success("설치 완료! 새로고침하세요.")
        else:
            st.error("설치 실패")
            st.code(log)
    st.stop()

# ── 세션 상태 초기화 ────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "pinterest_user" not in st.session_state:
    st.session_state.pinterest_user = ""
if "pinterest_pass" not in st.session_state:
    st.session_state.pinterest_pass = ""

# ════════════════════════════════════════════════════════
# 로그인 화면
# ════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    st.title("📌 Pinterest Downloader")
    st.markdown("### Pinterest 로그인")
    st.caption("로그인하면 보드의 모든 이미지를 다운로드할 수 있습니다.")

    with st.form("login_form"):
        email = st.text_input("이메일", placeholder="example@email.com")
        password = st.text_input("비밀번호", type="password")
        login_btn = st.form_submit_button("로그인", use_container_width=True)

    if login_btn:
        if not email or not password:
            st.error("이메일과 비밀번호를 입력하세요.")
        else:
            # gallery-dl로 로그인 테스트
            with st.spinner("로그인 확인 중..."):
                cfg_path = make_config(email, password)
                test_cmd = gallery_dl_cmd() + [
                    "--config", cfg_path,
                    "--username", email,
                    "--password", password,
                    "--simulate",
                    "--range", "1",
                    "https://www.pinterest.com/",
                ]
                r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)
                Path(cfg_path).unlink(missing_ok=True)

            # 로그인 실패 여부는 에러 메시지로 판단
            if "Login failed" in (r.stdout + r.stderr) or "AuthenticationError" in (r.stdout + r.stderr):
                st.error("로그인 실패. 이메일/비밀번호를 확인하세요.")
            else:
                st.session_state.logged_in = True
                st.session_state.pinterest_user = email
                st.session_state.pinterest_pass = password
                st.rerun()

    st.stop()

# ════════════════════════════════════════════════════════
# 메인 화면 (로그인 후)
# ════════════════════════════════════════════════════════
col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title("📌 Pinterest Downloader")
with col_logout:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("로그아웃"):
        st.session_state.logged_in = False
        st.session_state.pinterest_user = ""
        st.session_state.pinterest_pass = ""
        st.rerun()

st.caption(f"로그인: {st.session_state.pinterest_user}")
st.divider()

# ── URL 입력 + 다운로드 ─────────────────────────────────
board_url = st.text_input(
    "보드 URL 입력",
    placeholder="https://www.pinterest.com/username/boardname/",
    label_visibility="collapsed",
)

download_btn = st.button("📥 보드 전체 다운로드", use_container_width=True, type="primary")

# ── 다운로드 실행 ───────────────────────────────────────
if download_btn:
    url = board_url.strip()
    if not url:
        st.error("URL을 입력하세요.")
        st.stop()
    if "pinterest" not in url and "pin.it" not in url:
        st.error("Pinterest URL을 입력하세요.")
        st.stop()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = DOWNLOAD_DIR / f"{folder_from_url(url)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = make_config(
        st.session_state.pinterest_user,
        st.session_state.pinterest_pass,
    )

    cmd = gallery_dl_cmd() + [
        "--config", cfg_path,
        "--username", st.session_state.pinterest_user,
        "--password", st.session_state.pinterest_pass,
        "--destination", str(out_dir),
        "--no-mtime",
        "--retries", "5",
        "--sleep", "0.3",
        "--sleep-request", "0.2",
        url,
    ]

    log_box = st.empty()
    status = st.empty()
    log_lines: list[str] = []

    with st.spinner("다운로드 중..."):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
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

    Path(cfg_path).unlink(missing_ok=True)

    all_imgs = count_images(out_dir)
    total = len(all_imgs)

    if total > 0:
        st.success(f"✅ 총 **{total}장** 완료!")

        # 미리보기
        with st.expander("미리보기", expanded=True):
            cols = st.columns(4)
            for i, img in enumerate(sorted(all_imgs)[:16]):
                with cols[i % 4]:
                    try:
                        st.image(str(img), use_container_width=True)
                    except Exception:
                        st.text(img.name)

        # ZIP 다운로드
        with st.spinner("ZIP 압축 중..."):
            zip_path = zip_directory(out_dir)
        size_mb = zip_path.stat().st_size // 1024 // 1024
        with open(zip_path, "rb") as zf:
            st.download_button(
                label=f"📦 ZIP 다운로드 ({total}장 / {size_mb}MB)",
                data=zf,
                file_name=zip_path.name,
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.error("이미지를 가져오지 못했습니다.")
        st.code("\n".join(log_lines))

# ── 이전 다운로드 목록 ──────────────────────────────────
st.divider()
sessions = sorted(
    [s for s in DOWNLOAD_DIR.iterdir() if s.is_dir()],
    key=lambda p: p.stat().st_mtime, reverse=True,
) if DOWNLOAD_DIR.exists() else []

if sessions:
    st.subheader("이전 다운로드")
    for session in sessions[:10]:
        imgs = count_images(session)
        size_mb = sum(f.stat().st_size for f in imgs) // 1024 // 1024
        zip_path = session.parent / f"{session.name}.zip"

        c1, c2, c3 = st.columns([6, 1, 1])
        with c1:
            st.text(f"{session.name}  |  {len(imgs)}장  |  {size_mb}MB")
        with c2:
            if zip_path.exists():
                with open(zip_path, "rb") as zf:
                    st.download_button("📥", data=zf, file_name=zip_path.name,
                                       mime="application/zip", key=f"dl_{session.name}")
            elif st.button("ZIP", key=f"zip_{session.name}"):
                zip_directory(session)
                st.rerun()
        with c3:
            if st.button("🗑️", key=f"del_{session.name}"):
                shutil.rmtree(session)
                if zip_path.exists():
                    zip_path.unlink()
                st.rerun()
