# 🧠 知識大挑戰（Quiz Site）

七大主題 × 四種題型的線上測驗網站。純前端，不需要安裝任何套件。

🌐 **線上網址：https://soes0309ben-glitch.github.io/Kuan/**

部署方式是 GitHub Pages（`gh-pages` 分支）。修改網站並 commit 到 `main` 之後，在 repo 根目錄執行下面這行即可更新線上版（約 1 分鐘生效）：

```bash
git subtree push --prefix quiz-site origin gh-pages
```

## 怎麼開

- **最簡單**：直接雙擊 `index.html` 用瀏覽器開啟。
- **本機伺服器**（建議，線上題庫功能更穩定）：
  ```bash
  cd quiz-site
  python3 -m http.server 8000
  # 打開 http://localhost:8000
  ```
- **放上網**：整個資料夾可直接部署到 GitHub Pages、Netlify、Render Static Site 等靜態主機。

## 題庫內容（共 182 題）

| 主題 | 單選 | 圖片 | 簡答 | 問答 |
|---|---|---|---|---|
| 🎬 動漫動畫 | 14 | 5 | 5 | 3 |
| 🏠 生活常識 | 12 | 4 | 5 | 3 |
| 📜 歷史 | 12 | 7 | 4 | 3 |
| ✈️ 旅遊地理 | 11 | 9 | 4 | 2 |
| 🎵 猜歌 | 16 | 4 | 4 | 2 |
| 🧩 猜謎 | 11 | 6 | 5 | 2 |
| 🐾 動物生活 | 12 | 10 | 4 | 3 |

### 題型
- **單選題**：四選一，選項每次自動打亂。
- **圖片題**：看照片（景點、古蹟、動物）或表情符號圖謎（猜動漫、成語、節日、兒歌）作答。
- **簡答題**：輸入短答案自動判分，可接受多種寫法（例：首爾／漢城、魯夫／路飛），會忽略空白、標點、全半形、「臺／台」差異。
- **問答題**：開放式回答，作答後顯示參考答案，由作答者自評（答對 1 分、部分 0.5 分）。

### 猜歌怎麼做的
網站用瀏覽器內建的 Web Audio 即時合成旋律來播放，全部是**公有領域**的歌曲（童謠、民謠、古典樂，例如小星星、歡樂頌、給愛麗絲、茉莉花、驪歌），不使用有版權的錄音。

### 題庫來源
- 本機中文題庫為原創撰寫，內容依據公開的常識與史實。
- 照片來自 Wikimedia Commons／Wikipedia（自由授權），各圖來源頁記錄在 `images/credits.json`。
- 出題設定可勾選「線上擴充題庫」，即時從 [Open Trivia DB](https://opentdb.com/)（CC BY-SA 4.0，英文）額外抓 5 題。其他可參考的免費題庫：[The Trivia API](https://the-trivia-api.com/)（僅限非商業使用）。

## 其他功能
- 每個主題記錄最佳成績（存在瀏覽器裡）。
- 結果頁可「重練錯題」。
- 「題庫總覽」可依主題／題型篩選、搜尋、看答案，並能**匯出整份題庫 JSON**。
- 支援手機版與深色模式。
- 粉彩可愛風介面，吉祥物是原創的蝴蝶結小雲朵「問問」（未使用任何三麗鷗官方角色）。

## 新增題目
編輯 `js/questions.js` 裡的 `QUESTIONS` 陣列，照現有格式加一行即可：

```js
// 單選題（options 要包含 answer）
{ cat: "animal", type: "single", q: "題目？", options: ["正解", "錯1", "錯2", "錯3"], answer: "正解", explain: "補充說明（可省略）" },
// 圖片題：img 放 images/ 裡的檔名，或用 emoji
{ cat: "travel", type: "image", q: "這是哪裡？", img: "fuji.jpg", options: [...], answer: "..." },
// 簡答題：accept 列出所有可接受的答案
{ cat: "history", type: "short", q: "題目？", accept: ["答案", "另一種寫法"] },
// 問答題：ref 為參考答案
{ cat: "life", type: "qa", q: "題目？", ref: "參考答案" },
// 猜歌：加 melody，對應 MELODIES 裡的旋律
{ cat: "song", type: "single", q: "聽旋律猜歌名：", melody: "twinkle", options: [...], answer: "小星星" },
```

主題 `cat` 可用：`anime`、`life`、`history`、`travel`、`song`、`riddle`、`animal`。
