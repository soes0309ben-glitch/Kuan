# 📒 LINE 記帳本（expense-app）

在 LINE 聊天室傳一句「午餐 120」就記好一筆帳；網頁版看圖表、編輯明細、管理分類與預算、匯出 CSV。

```
你：午餐 120            → ✅ 已記錄 🍱 餐飲 -$120（今日支出 $185・本期支出 $8,450）
你：昨天 計程車 250     → ✅ 已記錄 🚌 交通（日期自動設為昨天）
你：+50000 薪水         → ✅ 已記錄 💼 薪水 +$50,000
你：本月                → 📊 收支、分類排行、預算使用狀況（Flex 卡片）
```

---

## 1. 功能總覽

### LINE 聊天機器人（Messaging API）

| 功能 | 說明 |
|---|---|
| **一句話記帳** | 「內容 金額」或「金額 內容」，空格可省略（`計程車250`），全形半形都可以 |
| **自動分類** | 依關鍵字自動歸類（午餐→餐飲、捷運→交通、蝦皮→購物…），取「最長命中」的關鍵字；可用 `#分類` 指定 |
| **自動判斷收支** | `+金額`、`收入 …` 一定算收入；內容命中收入關鍵字（薪水、獎金、股息、退款…）也自動算收入 |
| **日期** | `昨天`、`前天`、`10/3`、`2026/1/2`、`3月5日`；沒寫年份又比今天晚，視為去年（一月初補記 12/30） |
| **金額寫法** | `$65`、`65元`、`1,200`、`1.2k`、`1.5萬`；備註裡的數字不會被當成金額（`7-11 咖啡 45`、`iPhone 16 32900`） |
| **一次記多筆** | 一則訊息多行，每行一筆；看不懂的行會列出來，其他照記 |
| **記完立即修正** | 回覆卡片下方的快速按鈕：改分類、支出⇄收入、↩️ 復原 |
| **查詢** | `今天` `昨天` `本週` `本月` `上月` `明細`（最近 10 筆，可點按鈕刪除） |
| **預算** | `預算 20000`（總預算）、`預算 餐飲 6000`（分類預算）、`預算`（查看）、金額 0 為取消 |
| **預算警示** | 某筆支出讓預算跨過 80% 或 100% 時，記帳回覆裡直接提醒（不額外推播，不耗訊息額度） |
| **每日提醒** | `提醒 開`／`提醒 關`／`提醒 21`：指定整點若當天還沒記帳就推播提醒 |
| **月報** | 開啟提醒的人，每期第一天早上 9 點收到上一期月報 |
| **網頁登入** | 傳 `網頁` 取得 10 分鐘內有效、只能用一次的登入連結 |
| **安全** | 驗證 `X-Line-Signature`；只處理一對一聊天（群組訊息忽略）；所有操作都檢查紀錄屬於本人 |

### 網頁版

- **總覽**：本期支出／收入／結餘、與上月比較、日均支出、本期預估支出；預算進度條（🟢 正常／🟡 ≥80%／🔴 超支）；支出分類排行（點分類跳到明細）；每日支出直條圖；近 6 個月收支直條圖。圖表皆可 hover 看數字、切換成表格。
- **明細**：依日期分組、收支篩選、分類篩選、關鍵字搜尋；點一筆即可編輯或刪除。
- **記一筆**：底部「＋」按鈕，選收支、金額、分類、備註、日期。
- **預算**：總預算＋每個支出分類的預算一次設定。
- **設定**：每日提醒開關與時間、**月結日**（例如 25 號發薪就設 25 日，統計和預算都從 25 日起算）、分類管理（新增、改名、改圖示、編輯自動分類關鍵字、排序、刪除）、匯出 CSV（本月／全部，Excel 開啟不亂碼）、登出。
- 手機優先的版面、深色模式。

---

## 2. 系統架構

```
 LINE App ──訊息──▶ LINE Platform ──Webhook（簽章）──▶ POST /line/webhook
    ▲                      │                                │
    │                      │                                ▼
    └──── Reply / Push ◀───┘◀──── app/line_api.py ◀──── app/bot.py（指令、Flex 卡片）
                                                            │
 瀏覽器 ──▶ /auth/line/login（LINE Login） ┐                ▼
        ──▶ /auth/magic?token=…（機器人連結）├─ session ─▶ app/ledger.py（記帳、統計、預算）
        ──▶ /api/*（JSON）               ┘                 │
                                                            ▼
 排程（每小時）──▶ POST /cron/hourly ──▶ 每日提醒、月報     SQLAlchemy ─▶ SQLite / PostgreSQL
```

| 檔案 | 職責 |
|---|---|
| `app/parser.py` | 把一句話解析成「記帳」或「指令」（純函式，易於測試） |
| `app/categories.py` | 預設分類與關鍵字、自動分類 |
| `app/ledger.py` | 新增紀錄、期間計算（含月結日）、統計、預算與警示 |
| `app/bot.py` | 機器人邏輯：處理文字與 postback，組出 Flex 訊息 |
| `app/line_api.py` | LINE Messaging API：簽章驗證、reply、push、profile |
| `app/users.py` | 建立使用者（含預設分類）、一次性登入連結 |
| `app/routers/line_webhook.py` | Webhook：follow / unfollow / message / postback |
| `app/routers/auth.py` | LINE Login（OAuth 2.1 + OIDC，含 state / nonce）、魔法連結、登出 |
| `app/routers/api.py` | 網頁版 JSON API |
| `app/routers/cron.py` | 每日提醒、月報推播 |
| `app/static/` | 單頁前端（原生 JS，無建置步驟） |

### 帳號串接的關鍵

LINE 的 `userId` 是「每個 Provider 一組」。**Messaging API channel 與 LINE Login channel 建在同一個 Provider 底下**，
使用者在聊天室記的帳，用 LINE Login 登入網頁後就會自動看到，不需要任何綁定步驟。
另外也可以不設定 LINE Login，只靠機器人發的一次性連結登入網頁。

---

## 3. 資料模型

| 資料表 | 欄位重點 |
|---|---|
| `users` | `line_user_id`（唯一）、顯示名稱、頭像、`bot_friend`（是否為好友，封鎖後不推播）、`reminder_enabled`、`reminder_hour`、`month_start_day` |
| `categories` | `user_id`、`kind`（expense / income）、名稱、圖示、`keywords`（逗號分隔）、排序、`archived`（刪除＝封存，舊紀錄保留） |
| `transactions` | `user_id`、`kind`、`amount`（整數元）、`category_id`、`note`、`occurred_on`（日期）、`source`（line / web） |
| `budgets` | `user_id`、`category_id`（空＝總預算）、`amount`（每期） |
| `login_tokens` | 一次性登入連結，只存 SHA-256 雜湊、10 分鐘過期、用過即失效 |
| `reminder_logs` | （使用者, 種類, 日期）唯一，確保排程重跑也不會重複推播 |

---

## 4. API

所有改變資料的請求都要 `Content-Type: application/json`（搭配 SameSite=Lax cookie 防 CSRF）。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/config` | 是否啟用 LINE Login、加好友連結 |
| GET | `/api/me` | 目前使用者與設定、目前期間 |
| POST | `/api/me/settings` | `reminder_enabled`、`reminder_hour`、`month_start_day` |
| GET / POST | `/api/categories` | 列出／新增分類 |
| PUT / DELETE | `/api/categories/{id}` | 修改／封存分類 |
| POST | `/api/categories/reorder` | `{ids: [...]}` 排序 |
| GET | `/api/transactions?month=&kind=&category_id=&q=` | 明細 |
| POST | `/api/transactions` | 新增 |
| PUT / DELETE | `/api/transactions/{id}` | 修改／刪除 |
| GET | `/api/summary?month=YYYY-MM` | 總額、分類、每日、預算、上月比較、日均與預估 |
| GET | `/api/trend?months=6` | 近 N 期收支 |
| GET / POST | `/api/budgets` | 預算狀態／設定（`amount: 0` 為刪除） |
| GET | `/api/export.csv?month=` | 匯出 CSV（不帶 month 為全部） |
| POST | `/line/webhook` | LINE Webhook |
| POST | `/cron/hourly` | 排程（需 `X-Cron-Token`） |

---

## 5. 設定 LINE

1. 到 [LINE Developers Console](https://developers.line.biz/console/) 建立一個 **Provider**。
2. **Messaging API channel**（聊天機器人）
   - 「Basic settings」→ 複製 **Channel secret** → `LINE_CHANNEL_SECRET`
   - 「Messaging API」→ 發行 **Channel access token (long-lived)** → `LINE_CHANNEL_ACCESS_TOKEN`
   - **Webhook URL** 填 `https://你的網址/line/webhook`，按 Verify，並開啟 **Use webhook**
   - 到 [LINE Official Account Manager](https://manager.line.biz/) → 回應設定：**關閉「自動回應訊息」**、**關閉「加入好友的歡迎訊息」**（改由程式回覆）
   - 加好友連結（例如 `https://line.me/R/ti/p/@xxxx`）填到 `LINE_BOT_ADD_FRIEND_URL`
3. **LINE Login channel**（網頁登入，選用；**必須在同一個 Provider**）
   - Channel ID → `LINE_LOGIN_CHANNEL_ID`、Channel secret → `LINE_LOGIN_CHANNEL_SECRET`
   - 「LINE Login」→ **Callback URL** 填 `https://你的網址/auth/line/callback`
   - 「Basic settings」→ **Linked LINE Official Account** 選上面的官方帳號（登入時會邀請加好友）
   - 記得把 channel 狀態從 Developing 改為 **Published**，否則只有開發者能登入
4. **圖文選單（建議）**：在 Official Account Manager → 圖文選單，建立 6 格，動作都選「文字」：
   `本月`｜`今天`｜`明細`｜`預算`｜`網頁`｜`說明`

### 訊息額度

回覆（reply）不計費；只有每日提醒與月報用到推播（push），且只推給自己開啟提醒的人、每天最多一次。
免費方案每月有固定推播額度，使用者多時請留意。

---

## 6. 本機開發

```bash
cd expense-app
uv venv .venv && uv pip install -p .venv/bin/python -e ".[dev]"
cp .env.example .env              # 填入金鑰；本機可設 DEV_LOGIN=true 不經 LINE 直接登入
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest        # 執行測試
```

本機測試 LINE Webhook：用 [ngrok](https://ngrok.com/) 或 `cloudflared tunnel` 把 8000 port 對外，
把產生的 https 網址填到 Webhook URL 與 `BASE_URL`。

## 7. 部署到 Render

1. Render Dashboard → New → Blueprint → 選這個 repo，會讀取根目錄 `render.yaml` 建立 `expense-app` 服務。
2. 建一個 Render PostgreSQL，把 Internal Database URL 填到 `DATABASE_URL`（免費方案的 SQLite 檔案在重新部署時會消失）。
3. 填入 `BASE_URL`（例如 `https://expense-app.onrender.com`）與上面 LINE 的各項金鑰。
4. 排程：任一外部排程服務每小時呼叫一次（例如 [cron-job.org](https://cron-job.org/) 免費），
   同時也能喚醒休眠中的免費方案：

   ```bash
   curl -X POST -H "X-Cron-Token: $CRON_TOKEN" https://你的網址/cron/hourly
   ```

   或用 GitHub Actions：

   ```yaml
   on:
     schedule: [{ cron: "0 * * * *" }]
   jobs:
     ping:
       runs-on: ubuntu-latest
       steps:
         - run: curl -fsS -X POST -H "X-Cron-Token: ${{ secrets.EXPENSE_CRON_TOKEN }}" ${{ secrets.EXPENSE_BASE_URL }}/cron/hourly
   ```

> Render 免費方案閒置會休眠，第一則 LINE 訊息可能要等 30 秒以上才回覆；LINE 的 reply token 約 1 分鐘內有效，通常來得及。
> 要穩定回應建議改用付費方案，或用上面的排程定期喚醒。

---

## 8. 未來可擴充

- **LIFF**：把網頁版包成 LINE 內開啟的 LIFF App，免登入直接使用
- **收據拍照記帳**：接 OCR（例如 Claude 的影像辨識）解析發票、收據照片
- **電子發票載具**：串財政部電子發票 API 自動匯入
- **多帳戶／信用卡**：現金、銀行、信用卡分開記，含轉帳
- **共同帳本**：情侶、室友、旅遊分帳（LINE 群組中記帳並計算誰該付誰）
- **固定收支**：房租、訂閱每月自動記
- **多幣別**：旅遊時記外幣並自動換算
