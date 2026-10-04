# 🎀 知識大挑戰（quiz-app）

七大主題（動漫動畫、生活常識、歷史、旅遊地理、猜謎、動物生活、冷知識）× 三種難度（簡單／中等／困難）× 四種題型（單選、圖片、簡答、問答）的線上測驗網站。

- **Google 帳號登入**才能挑戰
- **每個「主題 × 難度」每人只能挑戰一次**：按下開始就算使用機會，中途離開可以回來繼續，但不能重來
- 答案只存在伺服器，判分也在伺服器，瀏覽器拿不到正解
- **登入即可免費挑戰與瀏覽題庫總覽**（篩選、搜尋）
- **答案為付費內容**：Stripe 月訂閱（預設 NT$399）可看全部答案與解說、**匯出含答案的 PDF**；免費會員只看得到自己已挑戰完成的組合的答案，不能匯出 PDF
- 節目感作答：揭曉懸念、答對彩帶與音效、答錯搖晃、連對計數、冷知識小卡
- 管理後台（`ADMIN_EMAILS` 內的帳號）：匯入題庫、看統計、重設某人的挑戰

## 題庫

題庫（含答案）**不放進 git**，存放在本機 `seed/*.json`，部署後再匯入資料庫。
目前共 687 題，格式範例：

```json
{"cat": "animal", "type": "single", "difficulty": "easy",
 "q": "長頸鹿的舌頭是什麼顏色？", "options": ["深紫黑色", "粉紅色", "白色", "綠色"],
 "answer": "深紫黑色", "explain": "冷知識解說（選填）"}
```

| 欄位 | 說明 |
|---|---|
| `cat` | `anime` `life` `history` `travel` `riddle` `animal` `trivia` |
| `type` | `single` 單選、`image` 圖片（需 `img` 或 `emoji`）、`short` 簡答（需 `accept` 可接受答案清單）、`qa` 問答（需 `ref` 參考答案） |
| `difficulty` | `easy` `medium` `hard` |
| `img` | `app/static/images/` 裡的檔名（圖片來源見 `credits.json`，皆為 Wikimedia 自由授權） |

匯入方式（二選一）：
1. 用管理者帳號登入網站 → 右上「管理」→ 選擇 `seed/` 裡的 JSON 檔（可多選）
2. 指令：`DATABASE_URL=<資料庫網址> python -m app.seed seed/*.json`

匯入以「主題＋題目內容」比對，相同的題目會更新、新題目會新增，不會刪除舊題。

## 本機開發

```bash
cd quiz-app
uv venv .venv && uv pip install -p .venv/bin/python -e ".[dev]"
cp .env.example .env          # 填入金鑰（.env 不會進 git）
.venv/bin/python -m app.seed seed/*.json
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest    # 執行測試
```

## 部署到 Render，並從 WordPress.com 連過來

1. **Render**：Dashboard → New → Blueprint → 選這個 GitHub repo，會讀取根目錄的 `render.yaml` 建立 `quiz-app` 服務。
2. **Google 登入**：到 [Google Cloud Console](https://console.cloud.google.com/apis/credentials) 建立「OAuth 用戶端 ID」（網頁應用程式），
   已授權的重新導向 URI 填 `https://<你的服務>.onrender.com/auth/google/callback`。
3. **Stripe**：建議先用沙盒（測試環境）的金鑰；建立 webhook 端點 `https://<你的服務>.onrender.com/stripe/webhook`，
   事件選 `checkout.session.completed`、`customer.subscription.*`、`invoice.paid`、`invoice.payment_failed`；
   並在 Stripe 後台啟用 Customer Portal（讓會員自行取消訂閱）。
4. **在 Render 填環境變數**：`SECRET_KEY`、`BASE_URL`（服務網址）、`DATABASE_URL`、`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、
   `STRIPE_SECRET_KEY`（建議用受限金鑰 `rk_...`）、`STRIPE_WEBHOOK_SECRET`、`ADMIN_EMAILS`。
5. 用管理者帳號登入，從「管理」頁匯入 `seed/` 題庫。
6. **WordPress.com**：外觀 → 選單（或在頁面加「按鈕」區塊）新增連結到 `https://<你的服務>.onrender.com`。
   不建議用 iframe 嵌入：Google 不允許在 iframe 內登入。

> Render 免費方案閒置約 15 分鐘會休眠，下一位訪客要等約 1 分鐘喚醒。

## 測試涵蓋

`tests/test_quiz.py`：未登入不能作答、題目不含答案、每組合只能挑戰一次、同題不能答兩次、不能看別人的挑戰、
簡答比對、題庫登入即可瀏覽、免費會員只看已挑戰組合的答案、訂閱會員看全部答案、選項順序不洩漏答案、PDF 僅限訂閱會員、Google 回呼網址、Stripe webhook 簽章與訂閱同步、管理權限。
