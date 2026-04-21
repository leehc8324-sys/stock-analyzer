"""
Pinterest Board Image Downloader — Streamlit App
gallery-dl 기반으로 핀터레스트 보드/프로필/섹션 이미지 전체 다운로드
"""

import subprocess
import sys
import shutil
import zipfile
from pathlib import Path
from datetime import datetime

import streamlit as st

# ── 경로 설정 ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "pinterest_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ── gallery-dl 설치 확인 ────────────────────────────────
def check_gallery_dl() -> bool:
    return shutil.which("gallery-dl") is not None or _pip_gallery_dl_installed()

def _pip_gallery_dl_installed() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "gallery_dl", "--version"],
        capture_output=True, text=True
    )
    return result.returncode == 0

def gallery_dl_cmd() -> list[str]:
    if shutil.which("gallery-dl"):
        return ["gallery-dl"]
    return [sys.executable, "-m", "gallery_dl"]

def install_gallery_dl():
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "gallery-dl"],
        capture_output=True, text=True
    )
    return result.returncode == 0, result.stdout + result.stderr

def get_version() -> str:
    try:
        r = subprocess.run(gallery_dl_cmd() + ["--version"], capture_output=True, text=True)
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return "알 수 없음"

# ── URL에서 폴더명 추출 ─────────────────────────────────
def folder_from_url(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p and "pinterest" not in p and "http" not in p]
    return "_".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "board")

# ── ZIP 압축 ────────────────────────────────────────────
def zip_directory(folder: Path) -> Path:
    zip_path = folder.parent / f"{folder.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(folder))
    return zip_path

def count_images(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    return [f for f in folder.rglob("*") if f.suffix.lower() in exts]

# ── UI 설정 ─────────────────────────────────────────────
st.set_page_config(
    page_title="Pinterest Downloader",
    page_icon="📌",
    layout="wide",
)

st.title("📌 Pinterest 이미지 다운로더")
st.caption("gallery-dl 기반 | 보드 · 섹션 · 프로필 · 핀 전체 다운로드 지원")

# ── gallery-dl 설치 체크 ────────────────────────────────
if not check_gallery_dl():
    st.warning("`gallery-dl`이 설치되어 있지 않습니다.")
    if st.button("📦 gallery-dl 자동 설치"):
        with st.spinner("설치 중..."):
            ok, log = install_gallery_dl()
        if ok:
            st.success("설치 완료! 페이지를 새로고침하세요.")
        else:
            st.error("설치 실패. 터미널에서 `pip install gallery-dl` 을 직접 실행하세요.")
            st.code(log)
    st.stop()

with st.sidebar:
    st.subheader("ℹ️ 정보")
    st.code(get_version(), language="")
    st.markdown("""
**지원 URL 형식**
- `pinterest.com/user/board/`
- `pinterest.com/user/` (전체 프로필)
- `pinterest.com/pin/12345/`
- `pin.it/xxxxx`
- `pinterest.com/search/pins/?q=keyword`
""")
    st.markdown("---")
    st.markdown("**쿠키 설정** (비공개 보드용)")
    st.markdown("""
1. Chrome → F12 → Application → Cookies → `pinterest.com`
2. `_auth`, `_pinterest_sess` 등 쿠키 복사
3. Netscape 형식 cookies.txt 파일로 저장
""")

# ── 입력 폼 ────────────────────────────────────────────
with st.form("dl_form"):
    board_url = st.text_input(
        "Pinterest URL",
        placeholder="https://www.pinterest.com/username/boardname/",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        limit = st.number_input(
            "최대 다운로드 수 (0=전체)",
            min_value=0, max_value=9999, value=0, step=100,
        )
    with col2:
        rate_limit = st.text_input(
            "속도 제한 (예: 500k, 2M, 0=무제한)",
            value="0",
        )
    with col3:
        cookies_path = st.text_input(
            "cookies.txt 경로 (선택)",
            placeholder="/path/to/cookies.txt",
        )

    filename_fmt = st.text_input(
        "파일명 형식 (기본값 사용 권장)",
        placeholder="{category}/{user}/{board}/{filename}.{extension}",
    )

    extra_args = st.text_input(
        "추가 gallery-dl 옵션 (고급)",
        placeholder="--no-skip --write-info-json",
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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = folder_from_url(url)
    out_dir = DOWNLOAD_DIR / f"{folder_name}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # gallery-dl 명령 조합
    cmd = gallery_dl_cmd() + [
        "--destination", str(out_dir),
        "--no-mtime",
    ]

    if limit > 0:
        cmd += ["--range", f"1-{limit}"]

    rate = rate_limit.strip()
    if rate and rate != "0":
        cmd += ["--rate", rate]

    cookies = cookies_path.strip()
    if cookies:
        if not Path(cookies).exists():
            st.error(f"쿠키 파일 없음: {cookies}")
            st.stop()
        cmd += ["--cookies", cookies]

    fmt = filename_fmt.strip()
    if fmt:
        cmd += ["--filename", fmt]

    if extra_args.strip():
        import shlex
        cmd += shlex.split(extra_args.strip())

    cmd.append(url)

    st.info(f"실행 명령: `{' '.join(cmd)}`")

    log_box = st.empty()
    progress_text = st.empty()
    log_lines: list[str] = []

    with st.spinner("다운로드 중... (창을 닫지 마세요)"):
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
                progress_text.markdown(f"**현재까지 다운로드: {len(saved)}장**")

        proc.wait()

    all_imgs = count_images(out_dir)
    total = len(all_imgs)

    if proc.returncode == 0 or total > 0:
        st.success(f"✅ 완료! 총 **{total}장** 저장됨 → `{out_dir}`")

        # 미리보기
        if total > 0:
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
        if total > 0:
            with st.spinner("ZIP 압축 중..."):
                zip_path = zip_directory(out_dir)
            with open(zip_path, "rb") as zf:
                st.download_button(
                    label=f"📥 ZIP 다운로드 ({total}장, {zip_path.stat().st_size // 1024 // 1024}MB)",
                    data=zf,
                    file_name=zip_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )
    else:
        st.error("다운로드 실패. 아래 로그와 URL을 확인하세요.")
        if log_lines:
            st.code("\n".join(log_lines))

# ── 이전 다운로드 목록 ──────────────────────────────────
st.divider()
st.subheader("📁 이전 다운로드 목록")

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
        total_mb = sum(f.stat().st_size for f in imgs) // 1024 // 1024
        zip_path = session.parent / f"{session.name}.zip"

        col1, col2, col3, col4 = st.columns([5, 1, 1, 1])
        with col1:
            st.text(f"{session.name}  |  {len(imgs)}장  |  {total_mb}MB")
        with col2:
            if zip_path.exists():
                with open(zip_path, "rb") as zf:
                    st.download_button(
                        "📥 ZIP",
                        data=zf,
                        file_name=zip_path.name,
                        mime="application/zip",
                        key=f"dl_{session.name}",
                    )
            else:
                if st.button("ZIP", key=f"zip_{session.name}"):
                    with st.spinner("압축 중..."):
                        zip_directory(session)
                    st.rerun()
        with col3:
            # 미리보기 토글
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
