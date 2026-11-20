# ChordPro Studio

本機 ChordPro (`.cho`) 編輯、Capo 自動移調與 A4 正式吉他和弦譜 PDF 輸出工具。

## 功能列表

- 本機 `.cho` 檔案讀取、編輯與即時格式驗證
- JSON / ChordPro (`.cho`) 雙向轉換
- 12 平均律 Capo 0–12 自動移調（含 Slash Chord、`N.C.` 與純和弦行空白保留）
- 原檔儲存（SHA-256 版本衝突防護）與另存新檔
- A4 直向兩句一行 PDF 排版（Chromium Headless）與 Web UI 即時預覽／下載
- 完整日文與 Unicode（含全形空白）支援

## 系統需求（已驗證環境）

- Linux（Ubuntu / Debian）
- Python `>= 3.11` 與 `uv`
- Google Chrome 或 Chromium（PDF 輸出用）
- 日文字型（建議安裝 `Noto Sans JP`）

## 安裝與測試

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

## 使用方式

1. **啟動本機 Web 編輯器**（將您的 `.cho` 檔案放入 `outputs/` 目錄）：

```bash
uv run python -m chordpro_studio.web_api --dir outputs/ --port 8000
```

啟動後於瀏覽器開啟 `http://127.0.0.1:8000`，即可載入 `.cho`、修改歌詞與和弦、選擇目標 Capo 預覽／另存，並預覽或下載 A4 PDF。

2. **ChordPro CLI 工具**：

```bash
# JSON <-> .cho 雙向轉換
uv run python -m chordpro_studio.chordpro json2cho fixtures/sample_song.json outputs/sample.cho
uv run python -m chordpro_studio.chordpro cho2json outputs/sample.cho outputs/sample.json

# .cho 直接輸出 A4 PDF
uv run python -m chordpro_studio.pdf_renderer outputs/sample.cho -o outputs/sample.pdf
```

## 授權與第三方內容聲明

- **MIT License**：本專案之原創程式碼與排版範本依 [LICENSE](LICENSE)（MIT License）授權。
- **第三方內容聲明**：本專案**不包含**任何歌曲搜尋或網頁擷取功能，亦**不提供或分發**任何歌曲歌詞或樂譜資料。使用者需自行提供具有適當使用權限的 `.cho` 檔案；本專案之 MIT 授權**不適用於**任何第三方歌詞、樂譜或網站內容，且本工具未獲任何第三方音樂網站認可。

## 已知限制

- 瀏覽器 JavaScript 非同步競態目前依賴人工驗收，未於 `pytest` 中啟動瀏覽器自動化測試。
