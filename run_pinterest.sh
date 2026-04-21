#!/bin/bash
# Pinterest 이미지 다운로더 실행
cd "$(dirname "$0")"

# gallery-dl 없으면 설치
python3 -c "import gallery_dl" 2>/dev/null || pip install gallery-dl

streamlit run pinterest_downloader.py --server.port 8502
