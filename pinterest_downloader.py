"""
Pinterest Board Image Downloader — Streamlit App
gallery-dl 기반으로 핀터레스트 보드/프로필/섹션 이미지 전체 다운로드
"""

import subprocess
import sys
import shutil
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st

# ── 경로 설정 ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "pinterest_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ── gallery-dl 유틸 ─────────────────────────────────────
def check_gallery_dl() -> bool:
    if shutil.which("gallery-dl"):
        return True
    r = subprocess.run([sys.executable, "-m", "gallery_dl", "--version"], capture_output=True)
    return r.returncode == 0

def gallery_dl_cmd() -> list[str]:
    if shutil.which("gallery-dl"):
        return ["gallery-dl"]
    return [sys.executable, "-m", "gallery_dl"]

def install_gallery_dl():
    r = subprocess.run([sys.executable, "-m", "pip", "install", "gallery-dl"],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr

def get_version() -> str:
    try:
        r = subprocess.run(gallery_dl_cmd() + ["--version"], capture_output=True, text=True)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return "알 수 없음"

# ── 유틸 함수 ───────────────────────────────────────────
def folder_from_url(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p and "pinterest" not in p and "http" not in p]
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

# ── UI 설정 ─────────────────────────────────────────────
st.set_page_config(page_title="Pinterest Downloader", page_icon="📌", layout="wide")

st.title("📌 Pinterest 이미지 다운로더")
st.caption("gallery-dl 기반 | 보드 · 섹션 · 프로필 · 핀 전체 다운로드")

# ── gallery-dl 설치 체크 ────────────────────────────────
if not check_gallery_dl():
    st.warning("`gallery-dl`이 설치되어 있지 않습니다.")
    if st.button("📦 자동 설치"):
        with st.spinner("설치 중..."):
            ok, log = install_gallery_dl()
        if ok:
            st.success("설치 완료! 새로고침하세요.")
        else:
            st.error("설치 실패.")
            st.code(log)
    st.stop()

# ── 사이드바 ────────────────────────────────────────────
with st.sidebar:
    st.subheader(f"gallery-dl {get_version()}")
    st.markdown("**지원 URL**")
    st.markdown("""
- `pinterest.com/user/board/` — 보드
- `pinterest.com/user/` — 전체 프로필
- `pinterest.com/pin/12345/` — 단일 핀
- `pin.it/xxxxx` — 단축 링크
""")
    st.divider()
    st.subheader("쿠키 파일 만드는 법")
    st.markdown("""
**전체 이미지를 가져오려면 로그인 쿠키가 필요합니다.**

1. Chrome에 **[Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** 확장 설치
2. Pinterest에 로그인한 상태에서 `pinterest.com` 접속
3. 확장 아이콘 클릭 → **Export** → `pinterest.com_cookies.txt` 저장
4. 아래 업로더에 해당 파일 업로드
""")

# ── 입력 폼 ────────────────────────────────────────────
with st.form("dl_form"):
    board_url = st.text_input(
        "Pinterest 보드 URL",
        placeholder="https://www.pinterest.com/username/boardname/",
    )

    cookies_file = st.file_uploader(
        "cookies.txt 업로드 (전체 이미지 다운로드에 필수)",
        type=["txt"],
        help="없으면 일부 이미지만 다운로드됩니다.",
    )

    col1, col2 = st.columns(2)
    with col1:
        limit = st.number_input(
            "최대 다운로드 수 (0=전체)",
            min_value=0, max_value=9999, value=0, step=50,
        )
    with col2:
        sleep_sec = st.slider(
            "요청 간격 (초) — 너무 빠르면 차단됨",
            min_value=0.0, max_value=3.0, value=0.5, step=0.1,
        )

    submitted = st.form_submit_button("🚀 다운로드 시작", use_container_width=True)

# ── 다운로드 실행 ───────────────────────────────────────
if submitted:
    url = board_url.strip()
    if not url:
        st.error("URL을 입력하세요.")
        st.stop()
    if "pinterest" not in url and "pin.it" not in url:
        st.error("Pinterest URL을 입력하세요.")
        st.stop()

    if cookies_file is None:
        st.warning("쿠키 파일 없이 실행합니다. 전체 이미지가 다운로드되지 않을 수 있습니다.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = DOWNLOAD_DIR / f"{folder_from_url(url)}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 쿠키 임시 파일로 저장
    tmp_cookie = None
    if cookies_file:
        tmp_cookie = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb")
        tmp_cookie.write(cookies_file.read())
        tmp_cookie.flush()
        tmp_cookie_path = tmp_cookie.name
    else:
        tmp_cookie_path = None

    # gallery-dl 명령 조합
    cmd = gallery_dl_cmd() + [
        "--destination", str(out_dir),
        "--no-mtime",
        "--retries", "5",
        "--sleep", str(sleep_sec),
        "--sleep-request", "0.3",
    ]

    if limit > 0:
        cmd += ["--range", f"1-{limit}"]

    if tmp_cookie_path:
        cmd += ["--cookies", tmp_cookie_path]

    cmd.append(url)

    st.info(f"저장 위치: `{out_dir.name}`")

    log_box = st.empty()
    status_text = st.empty()
    log_lines: list[str] = []

    with st.spinner("다운로드 중... 창을 닫지 마세요."):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            log_lines.append(line)
            if len(log_lines) > 100:
                log_lines = log_lines[-100:]
            log_box.code("\n".join(log_lines), language="")
            saved = count_images(out_dir)
            if saved:
                status_text.markdown(f"**다운로드됨: {len(saved)}장**")
        proc.wait()

    # 임시 쿠키 파일 삭제
    if tmp_cookie_path:
        try:
            Path(tmp_cookie_path).unlink()
        except Exception:
            pass

    all_imgs = count_images(out_dir)
    total = len(all_imgs)

    if total > 0:
        st.success(f"✅ 완료! 총 **{total}장** 저장됨")

        # 미리보기
        st.subheader("미리보기 (최대 16장)")
        preview = sorted(all_imgs)[:16]
        cols = st.columns(4)
        for i, img in enumerate(preview):
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
                label=f"📥 ZIP 다운로드 ({total}장 / {size_mb}MB)",
                data=zf,
                file_name=zip_path.name,
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.error("이미지를 가져오지 못했습니다. 로그를 확인하세요.")
        if log_lines:
            st.code("\n".join(log_lines))

# ── 이전 다운로드 목록 ──────────────────────────────────
st.divider()
st.subheader("📁 이전 다운로드")

sessions = sorted(
    [s for s in DOWNLOAD_DIR.iterdir() if s.is_dir()],
    key=lambda p: p.stat().st_mtime,
    reverse=True,
) if DOWNLOAD_DIR.exists() else []

if not sessions:
    st.caption("아직 다운로드 기록이 없습니다.")
else:
    for session in sessions[:15]:
        imgs = count_images(session)
        size_mb = sum(f.stat().st_size for f in imgs) // 1024 // 1024
        zip_path = session.parent / f"{session.name}.zip"

        col1, col2, col3, col4 = st.columns([5, 1, 1, 1])
        with col1:
            st.text(f"{session.name}  |  {len(imgs)}장  |  {size_mb}MB")
        with col2:
            if zip_path.exists():
                with open(zip_path, "rb") as zf:
                    st.download_button("📥 ZIP", data=zf, file_name=zip_path.name,
                                       mime="application/zip", key=f"dl_{session.name}")
            elif st.button("ZIP", key=f"zip_{session.name}"):
                with st.spinner("압축 중..."):
                    zip_directory(session)
                st.rerun()
        with col3:
            if st.button("👁️", key=f"prev_{session.name}"):
                st.session_state[f"show_{session.name}"] = not st.session_state.get(f"show_{session.name}", False)
        with col4:
            if st.button("🗑️", key=f"del_{session.name}"):
                shutil.rmtree(session)
                if zip_path.exists():
                    zip_path.unlink()
                st.rerun()

        if st.session_state.get(f"show_{session.name}"):
            preview = sorted(imgs)[:8]
            pcols = st.columns(4)
            for i, img in enumerate(preview):
                with pcols[i % 4]:
                    try:
                        st.image(str(img), use_container_width=True)
                    except Exception:
                        st.text(img.name)
