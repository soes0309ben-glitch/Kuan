# 🐱 隨手記帳本（手機 App 版）

招財貓「財財」陪你記帳。用 [Capacitor](https://capacitorjs.com/) 把網頁版包成 iOS 與 Android 原生 App：

- 資料存在手機裡（Capacitor Preferences），不用登入、不上網也能用
- 字型已內建（`www/fonts/`），離線也是可愛的圓體字
- 匯出 CSV、備份資料都走系統分享面板，可存到雲端硬碟或傳給自己；也能從備份檔還原

```
cat-ledger-app/
├── web-source/index.html    網頁版原始檔（claude.ai 上的「隨手記帳本」）
├── www/                     App 實際載入的網頁（由 scripts/build_www.py 產生）
├── assets/                  App icon 與啟動畫面原圖（1024／2732）
├── android/  ios/           原生專案（Capacitor 產生）
├── store/                   上架文案、隱私權政策、商店截圖
└── scripts/                 產生 www、icon、截圖的腳本
```

App ID 是 `com.kuan.catledger`（在 `capacitor.config.json`）。**上架後就不能改**，想換成自己的（例如 `com.你的名字.catledger`）請在第一次上架前改，並重新執行 `npx cap sync`，Android 的 `android/app/build.gradle` 裡的 `namespace`、`applicationId` 也要一起改。

---

## 0. 先準備

| 項目 | 費用 | 說明 |
|---|---|---|
| [Apple Developer Program](https://developer.apple.com/programs/enroll/) | 每年 US$99 | 上架 App Store 必備；個人用 Apple ID 申請即可，審核約 1～2 天 |
| [Google Play Console](https://play.google.com/console/signup) | 一次 US$25 | 上架 Google Play 必備，需要身分驗證 |
| Mac 電腦＋ Xcode | — | **iOS 只能在 Mac 上打包送審**。沒有 Mac 可以用 [Codemagic](https://codemagic.io/) 等雲端服務 |
| 公開的隱私權政策網址 | 免費 | 兩邊商店都要求，見下方第 3 步 |

> ⚠️ Google Play 規定：2023 年 11 月後註冊的**個人**開發者帳號，正式上架前必須先做「封閉測試」，至少 **12 位測試人員連續 14 天**參與，才能申請正式版。可以先邀請親朋好友加入測試。

---

## 1. 在自己電腦上跑起來

```bash
cd cat-ledger-app
npm install
npx cap sync           # 把 www/ 複製進 android/ 與 ios/
npx cap open android   # 用 Android Studio 開啟，按 ▶ 在模擬器或手機上執行
npx cap open ios       # （Mac）用 Xcode 開啟，按 ▶ 執行
```

網頁版有更新時，把新的 HTML 存到 `web-source/index.html`，再執行：

```bash
python3 scripts/build_www.py web-source/index.html
npx cap sync
```

---

## 2. Google Play 上架

### 2-1 建立上傳金鑰（只做一次，金鑰要永久保存）

```bash
keytool -genkeypair -v -keystore upload.jks -alias upload \
  -keyalg RSA -keysize 2048 -validity 10000
```

照提示設定密碼。**`upload.jks` 和密碼一定要備份好**（例如存進密碼管理器）。遺失的話要向 Google 申請重設，很麻煩。這個檔案已被 `.gitignore` 排除，不會進 git。

### 2-2 讓 GitHub 自動打包

1. 把金鑰轉成文字：`base64 -w0 upload.jks`（Mac 用 `base64 -i upload.jks`），複製輸出。
2. 到 GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**，新增 4 個：

   | 名稱 | 內容 |
   |---|---|
   | `ANDROID_KEYSTORE_BASE64` | 上一步複製的那串文字 |
   | `ANDROID_KEYSTORE_PASSWORD` | 金鑰庫密碼 |
   | `ANDROID_KEY_ALIAS` | `upload` |
   | `ANDROID_KEY_PASSWORD` | 金鑰密碼 |

3. 到 **Actions → 隨手記帳本 Android → Run workflow**。約 5 分鐘後，在那次執行頁面最下方的 **Artifacts** 下載 `cat-ledger-android`，裡面有：
   - `app-release.aab`：上傳到 Google Play 用
   - `app-release.apk`：可以直接裝到 Android 手機測試

也可以在自己電腦打包：設定好上面 4 個環境變數（`ANDROID_KEYSTORE_PATH` 指向 `upload.jks`），在 `android/` 執行 `./gradlew bundleRelease`。

### 2-3 在 Play Console 建立應用程式

1. **建立應用程式**：名稱「隨手記帳本－招財貓陪你記帳」、預設語言「中文（台灣）」、應用程式、免費。
2. **設定應用程式**（資訊主頁上的待辦清單）：
   - 隱私權政策：填第 3 步的網址
   - 應用程式存取權：所有功能都不需要特殊存取權
   - 廣告：不含廣告
   - 內容分級：填問卷（財經工具，全部選否）→ 普遍級
   - 目標對象：18 歲以上（或 13 歲以上）
   - 資料安全性：**不收集、不分享任何使用者資料**
   - 政府應用程式／金融功能：否（只是記帳，不是金融服務）
3. **商店資訊**：文案從 `store/listing.md` 複製；圖片上傳 `store/googleplay-icon-512.png`、`store/screenshots/googleplay-feature-graphic.png`、`store/screenshots/googleplay-*.png`。
4. **測試 → 封閉測試**：建立測試群組（加入測試人員的 Gmail）→ 建立新版本 → 上傳 `app-release.aab` → 送審。第一次會請你啟用「Play 應用程式簽署」，選 Google 管理的金鑰即可。
5. 封閉測試滿 14 天、12 人以上後，到 **正式版** 申請上架。

之後每次更新：把 `android/app/build.gradle` 的 `versionCode` 加 1（`versionName` 改成新版號），重新打包上傳。

---

## 3. 隱私權政策網址

`store/privacy-policy.html` 已經寫好，先把最下方的「（請填入你的聯絡信箱）」改成你的信箱，再放到任何公開網址，例如：

- **GitHub Pages**：把這個檔案放到另一個公開 repo，在 Settings → Pages 開啟，網址會是 `https://你的帳號.github.io/repo名稱/privacy-policy.html`
- 或放到 Google 協作平台、Notion 公開頁面等

---

## 4. App Store 上架（需要 Mac）

1. **加入 Apple Developer Program** 後，到 [App Store Connect](https://appstoreconnect.apple.com/) → 我的 App → ＋ 新增 App：
   - 平台 iOS、名稱「隨手記帳本－招財貓陪你記帳」、主要語言「繁體中文」
   - 套裝識別碼：選 `com.kuan.catledger`（沒有的話先到 developer.apple.com → Identifiers 建立）
   - SKU：任意，例如 `catledger001`
2. **在 Mac 上打包**：
   ```bash
   npm install && npx cap sync ios && npx cap open ios
   ```
   - Xcode 左側點 **App** → **Signing & Capabilities** → 勾選 Automatically manage signing，Team 選你的開發者帳號
   - **General** → Version 填 `1.0.0`、Build 填 `1`
   - 上方裝置選 **Any iOS Device (arm64)** → 選單 **Product → Archive**
   - 完成後在 Organizer 按 **Distribute App → App Store Connect → Upload**
3. **在 App Store Connect 填資料**：
   - 文案、關鍵字、分類從 `store/listing.md` 複製
   - 截圖上傳 `store/screenshots/appstore-6.9-*.png`（6.9 吋，其他尺寸會自動縮放）
   - **App 隱私權**：選「不收集資料」
   - 隱私權政策網址：第 3 步的網址
   - 年齡分級：問卷全部選「無」→ 4+
   - 加密：已在 `Info.plist` 設定不使用非豁免加密，不用另外回答
   - 選剛剛上傳的建置版本 → **提交審查**（通常 1～3 天）

> 💡 審查備註可以寫：「這是一個單機記帳 App，所有資料只存在裝置上，不需要帳號或網路。在輸入框輸入『午餐 120』後按 Enter 即可新增一筆紀錄；也可以在空白時按『先載入範例資料看看』體驗所有功能。」

---

## 5. 重新產生圖片

```bash
pip install playwright && playwright install chromium   # 只需第一次
python3 scripts/render_assets.py        # icon 與啟動畫面原圖 → assets/
npm run assets                          # 產生 iOS／Android 各尺寸 icon 與啟動畫面
python3 scripts/render_screenshots.py   # 商店截圖 → store/screenshots/
```
