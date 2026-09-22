# 日本旅遊行程規劃網站

日本景點與美食探索、搜尋篩選、收藏、每日行程規劃，以及依住宿等級付費解鎖的多天數行程規劃書。

## 安裝

```bash
cd japan-travel
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 設定

```bash
cp .env.example .env
```

`.env` 不會被 git 追蹤，請把 Stripe／Unsplash 的金鑰填在這裡，不要寫進任何會進版控的檔案。沒有金鑰時網站仍可正常瀏覽：圖片會顯示佔位圖，付費解鎖會回傳「金流尚未設定」的提示。

- **Stripe 測試金鑰**：<https://dashboard.stripe.com/test/apikeys>（先用 `sk_test_...` / `pk_test_...`，之後要正式收款再自行申請正式帳號換成 live 金鑰）
- **Unsplash Access Key**：<https://unsplash.com/developers>（建立一個 App 即可取得，免審核）

## 啟動

```bash
uvicorn app.main:app --reload
```

開啟 <http://127.0.0.1:8000>。

## 本機測試 Stripe Webhook

```bash
stripe listen --forward-to localhost:8000/webhooks/stripe
```

會印出一組 `whsec_...`，填入 `.env` 的 `STRIPE_WEBHOOK_SECRET`。付款可用 Stripe 測試卡號 `4242 4242 4242 4242`（任意未來日期、任意 CVC）。

## 測試

```bash
pytest
```

## 部署到 Render（免費子域名）

專案根目錄（`/Applications/AI-agent`）已經有一份 `render.yaml`，用 Render 的 Blueprint 功能一次建立好 web service。步驟：

1. **把這個 repo 推上 GitHub**：在 github.com 建一個新的空 repo（private 即可），照畫面指示把 `/Applications/AI-agent` 推上去。
2. 到 [dashboard.render.com](https://dashboard.render.com) 註冊/登入，點 **New → Blueprint**，選擇剛剛那個 GitHub repo，Render 會自動讀到 `render.yaml`。
3. Render 會列出 `render.yaml` 裡標記 `sync: false` 的環境變數，逐一貼上：
   - `SECRET_KEY`：**不要**用 `.env` 裡開發用的那組，正式站要用一組真的隨機字串（已幫你產生一組在下方，直接貼上即可）。
   - `DATABASE_URL`：免費方案沒有持久化磁碟，SQLite 每次重新部署／重啟都會清空。建議在 Render 另外加一個免費 Postgres（New → PostgreSQL），把它給的 Internal Database URL 貼進這裡；程式已經支援 Postgres（`psycopg2-binary` 已加入依賴），不用改程式碼。
   - `BASE_URL`：填 Render 給的網址，例如 `https://japan-travel-xxxx.onrender.com`。
   - `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` / `STRIPE_WEBHOOK_SECRET`、`UNSPLASH_ACCESS_KEY`、`NEWSAPI_KEY`、`RESEND_API_KEY`、`NOTIFY_EMAIL`、`NOTIFY_FROM_EMAIL`、`ADMIN_EMAILS`：跟本機 `.env` 內容一樣即可，沒申請到的先留空，網站會優雅降級。
4. 部署完成後，用 Render 網址實際打開網站確認正常運作。
5. **讓 Google 找得到**：到 [Google Search Console](https://search.google.com/search-console) 用「網址前置字元」新增 Render 給的網址、完成驗證（Render 提供的 HTML 驗證檔或 DNS 驗證都可以），再送出網址讓 Google 收錄。這一步完成後，Google 通常要幾天到幾週才會真的把頁面爬進搜尋結果，沒辦法加快。

**本次已產生一組正式用 `SECRET_KEY`（僅供這次部署使用，只在這裡出現一次，之後你自己在 Render 後台可以隨時重新產生換掉）：**

```
2a1a5927f92041f91f76f6917562cf5dd99bd12a325f1288ec11f0e1160cffe0
```
