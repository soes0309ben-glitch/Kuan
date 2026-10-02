/* 知識大挑戰 —— 前端邏輯（不需後端，題庫在 questions.js） */
(() => {
  "use strict";

  const $app = document.getElementById("app");
  const catById = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));
  QUESTIONS.forEach((q, i) => (q.id = "q" + i));

  // Open Trivia DB（CC BY-SA 4.0）英文線上題庫的分類對應
  const OPENTDB_CATEGORY = { anime: 31, life: 9, history: 23, travel: 22, song: 12, animal: 27 };

  /* ---------- 小工具 ---------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const shuffle = (arr) => {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };
  const store = {
    get(key, fallback) {
      try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 無痕模式等情況忽略 */ }
    },
  };

  // 簡答題比對：去空白標點、全形轉半形、臺→台、英文小寫
  const normalize = (s) =>
    String(s)
      .replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
      .toLowerCase()
      .replace(/臺/g, "台")
      .replace(/[\s·・．.,，。、!?！？「」『』《》〈〉()（）'"“”‘’\-—:：;；~～]/g, "");
  const checkShort = (input, accept) => {
    const n = normalize(input);
    if (!n) return false;
    return accept.some((a) => {
      const na = normalize(a);
      return n === na || (na.length >= 2 && n.length <= na.length + 4 && n.includes(na));
    });
  };

  /* ---------- 旋律播放（Web Audio） ---------- */
  let audioCtx = null;
  let stopTimer = null;
  const NOTE_INDEX = { C: 0, "C#": 1, D: 2, "D#": 3, E: 4, F: 5, "F#": 6, G: 7, "G#": 8, A: 9, "A#": 10, B: 11 };
  const freqOf = (name) => {
    const m = /^([A-G]#?)(\d)$/.exec(name);
    if (!m) return null;
    const midi = 12 * (Number(m[2]) + 1) + NOTE_INDEX[m[1]];
    return 440 * Math.pow(2, (midi - 69) / 12);
  };
  function playMelody(key, btn) {
    const mel = MELODIES[key];
    if (!mel) return;
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume();
    const beat = 60 / mel.bpm;
    let t = audioCtx.currentTime + 0.05;
    mel.notes.split(/\s+/).forEach((tok) => {
      const [name, dur = "1"] = tok.split(":");
      const len = parseFloat(dur) * beat;
      const f = freqOf(name);
      if (f) {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.value = f;
        gain.gain.setValueAtTime(0, t);
        gain.gain.linearRampToValueAtTime(0.3, t + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, t + len * 0.95);
        osc.connect(gain).connect(audioCtx.destination);
        osc.start(t);
        osc.stop(t + len);
      }
      t += len;
    });
    if (btn) {
      btn.disabled = true;
      btn.textContent = "🎶 播放中…";
      clearTimeout(stopTimer);
      stopTimer = setTimeout(() => {
        btn.disabled = false;
        btn.textContent = "🔁 再聽一次";
      }, (t - audioCtx.currentTime) * 1000);
    }
  }

  /* ---------- Open Trivia DB ---------- */
  async function fetchOpenTdb(catId, amount) {
    const cat = OPENTDB_CATEGORY[catId];
    if (!cat) return [];
    const url = `https://opentdb.com/api.php?amount=${amount}&category=${cat}&type=multiple&encode=url3986`;
    const res = await fetch(url);
    const data = await res.json();
    if (data.response_code !== 0) return [];
    return data.results.map((r, i) => {
      const answer = decodeURIComponent(r.correct_answer);
      return {
        id: `otdb-${catId}-${Date.now()}-${i}`,
        cat: catId,
        type: "single",
        q: decodeURIComponent(r.question),
        options: [answer, ...r.incorrect_answers.map(decodeURIComponent)],
        answer,
        source: "Open Trivia DB（英文）",
      };
    });
  }

  /* ---------- 狀態 ---------- */
  let quiz = null; // { title, catKey, list, index, results: [{q, score, given}] }

  /* ---------- 頁面：首頁 ---------- */
  function renderHome() {
    const best = store.get("quiz-best", {});
    const cards = CATEGORIES.map((c) => {
      const qs = QUESTIONS.filter((q) => q.cat === c.id);
      const b = best[c.id];
      return `
        <button class="cat-card" data-cat="${c.id}">
          <span class="cat-icon">${c.icon}</span>
          <span class="cat-name">${esc(c.name)}</span>
          <span class="cat-desc">${esc(c.desc)}</span>
          <span class="cat-meta">${qs.length} 題${b != null ? ` · 最佳 ${b}%` : ""}</span>
        </button>`;
    }).join("");
    $app.innerHTML = `
      <section class="hero">
        <h1>知識大挑戰</h1>
        <p>七大主題、四種題型，共 <strong>${QUESTIONS.length}</strong> 題。選一個主題開始吧！</p>
      </section>
      <section class="cat-grid">
        ${cards}
        <button class="cat-card mix" data-cat="all">
          <span class="cat-icon">🎲</span>
          <span class="cat-name">綜合挑戰</span>
          <span class="cat-desc">從所有主題隨機出題</span>
          <span class="cat-meta">${QUESTIONS.length} 題${best.all != null ? ` · 最佳 ${best.all}%` : ""}</span>
        </button>
      </section>`;
    $app.querySelectorAll(".cat-card").forEach((el) => el.addEventListener("click", () => renderSetup(el.dataset.cat)));
  }

  /* ---------- 頁面：出題設定 ---------- */
  function renderSetup(catKey) {
    const pool = catKey === "all" ? QUESTIONS : QUESTIONS.filter((q) => q.cat === catKey);
    const title = catKey === "all" ? "🎲 綜合挑戰" : `${catById[catKey].icon} ${catById[catKey].name}`;
    const typeBoxes = Object.entries(TYPES).map(([t, info]) => {
      const n = pool.filter((q) => q.type === t).length;
      return `<label class="chip ${n ? "" : "disabled"}"><input type="checkbox" name="type" value="${t}" ${n ? "checked" : "disabled"}> ${info.icon} ${info.name} <small>${n}</small></label>`;
    }).join("");
    const canOnline = catKey === "all" || OPENTDB_CATEGORY[catKey];
    $app.innerHTML = `
      <section class="panel setup">
        <button class="link back">← 回首頁</button>
        <h2>${title}</h2>
        <form id="setup-form">
          <fieldset>
            <legend>題型</legend>
            <div class="chips">${typeBoxes}</div>
          </fieldset>
          <fieldset>
            <legend>題數</legend>
            <div class="chips">
              ${[5, 10, 20].map((n, i) => `<label class="chip"><input type="radio" name="count" value="${n}" ${i === 1 ? "checked" : ""}> ${n} 題</label>`).join("")}
              <label class="chip"><input type="radio" name="count" value="999"> 全部</label>
            </div>
          </fieldset>
          ${canOnline ? `
          <fieldset>
            <legend>線上擴充題庫</legend>
            <label class="chip wide"><input type="checkbox" name="online"> 🌐 另外加入 5 題 Open Trivia DB 英文單選題（需網路）</label>
          </fieldset>` : ""}
          <p class="hint" id="setup-hint"></p>
          <button class="btn primary big" type="submit">開始作答 →</button>
        </form>
      </section>`;
    $app.querySelector(".back").addEventListener("click", renderHome);
    const form = $app.querySelector("#setup-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const types = [...form.querySelectorAll("input[name=type]:checked")].map((i) => i.value);
      const hint = form.querySelector("#setup-hint");
      if (!types.length) {
        hint.textContent = "請至少選一種題型。";
        return;
      }
      const count = Number(form.querySelector("input[name=count]:checked").value);
      let list = shuffle(pool.filter((q) => types.includes(q.type))).slice(0, count);
      if (form.online?.checked) {
        hint.textContent = "正在從 Open Trivia DB 取得題目…";
        try {
          const cat = catKey === "all" ? shuffle(Object.keys(OPENTDB_CATEGORY))[0] : catKey;
          list = list.concat(await fetchOpenTdb(cat, 5));
        } catch {
          hint.textContent = "線上題庫連線失敗，先用本機題庫開始。";
          await new Promise((r) => setTimeout(r, 900));
        }
      }
      startQuiz(title, catKey, shuffle(list));
    });
  }

  /* ---------- 作答 ---------- */
  function startQuiz(title, catKey, list) {
    quiz = { title, catKey, list, index: 0, results: [] };
    renderQuestion();
  }

  function renderQuestion() {
    const q = quiz.list[quiz.index];
    const total = quiz.list.length;
    const type = TYPES[q.type];
    const cat = catById[q.cat];
    const score = quiz.results.reduce((s, r) => s + r.score, 0);

    let media = "";
    if (q.img) media = `<figure class="q-img"><img src="images/${esc(q.img)}" alt="題目圖片"></figure>`;
    if (q.emoji) media = `<div class="q-emoji" aria-label="表情符號圖謎">${esc(q.emoji)}</div>`;
    if (q.melody) media += `<button class="btn melody" type="button">▶️ 播放旋律</button>`;

    let body = "";
    if (q.type === "single" || q.type === "image") {
      body = `<div class="options">${shuffle(q.options).map((o) => `<button class="option" data-v="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
    } else if (q.type === "short") {
      body = `<form class="short-form"><input class="text-input" name="ans" autocomplete="off" placeholder="輸入你的答案" autofocus><button class="btn primary" type="submit">送出</button></form>`;
    } else if (q.type === "qa") {
      body = `<textarea class="text-input area" placeholder="寫下你的想法（可以只在心裡想好）"></textarea>
              <button class="btn primary reveal" type="button">看參考答案</button>`;
    }

    $app.innerHTML = `
      <section class="panel quiz">
        <header class="quiz-head">
          <button class="link quit">✕ 結束</button>
          <span>${esc(quiz.title)}</span>
          <span class="score-pill">得分 ${fmt(score)}</span>
        </header>
        <div class="progress"><div style="width:${(quiz.index / total) * 100}%"></div></div>
        <div class="q-meta">
          <span class="badge">${type.icon} ${type.name}</span>
          <span class="badge soft">${cat.icon} ${cat.name}</span>
          ${q.source ? `<span class="badge soft">${esc(q.source)}</span>` : ""}
          <span class="q-count">${quiz.index + 1} / ${total}</span>
        </div>
        <h2 class="q-text">${esc(q.q)}</h2>
        ${media}
        <div class="answer-area">${body}</div>
        <div class="feedback" hidden></div>
      </section>`;

    $app.querySelector(".quit").addEventListener("click", () => (quiz.results.length ? renderResult() : renderHome()));
    const melBtn = $app.querySelector(".melody");
    if (melBtn) melBtn.addEventListener("click", () => playMelody(q.melody, melBtn));

    if (q.type === "single" || q.type === "image") {
      $app.querySelectorAll(".option").forEach((btn) =>
        btn.addEventListener("click", () => {
          const ok = btn.dataset.v === q.answer;
          $app.querySelectorAll(".option").forEach((b) => {
            b.disabled = true;
            if (b.dataset.v === q.answer) b.classList.add("correct");
          });
          if (!ok) btn.classList.add("wrong");
          finish(q, ok ? 1 : 0, btn.dataset.v);
        })
      );
    } else if (q.type === "short") {
      const form = $app.querySelector(".short-form");
      form.ans.focus();
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const v = form.ans.value.trim();
        if (!v) return;
        form.ans.disabled = true;
        form.querySelector("button").disabled = true;
        const ok = checkShort(v, q.accept);
        form.ans.classList.add(ok ? "correct" : "wrong");
        finish(q, ok ? 1 : 0, v);
      });
    } else if (q.type === "qa") {
      $app.querySelector(".reveal").addEventListener("click", (e) => {
        const area = $app.querySelector("textarea");
        area.readOnly = true;
        e.target.remove();
        const fb = $app.querySelector(".feedback");
        fb.hidden = false;
        fb.className = "feedback neutral";
        fb.innerHTML = `
          <h3>📖 參考答案</h3><p>${esc(q.ref)}</p>
          <p class="self-label">對照一下，你覺得自己答得如何？</p>
          <div class="self-grade">
            <button class="btn" data-s="1">😎 大致答對</button>
            <button class="btn" data-s="0.5">🤔 答對一部分</button>
            <button class="btn" data-s="0">😅 沒答出來</button>
          </div>`;
        fb.querySelectorAll(".self-grade button").forEach((b) =>
          b.addEventListener("click", () => {
            quiz.results.push({ q, score: Number(b.dataset.s), given: area.value.trim() });
            next();
          })
        );
      });
    }
  }

  function finish(q, score, given) {
    quiz.results.push({ q, score, given });
    const fb = $app.querySelector(".feedback");
    fb.hidden = false;
    fb.className = "feedback " + (score ? "good" : "bad");
    const answerText = q.type === "short" ? q.accept[0] : q.answer;
    fb.innerHTML = `
      <h3>${score ? "✅ 答對了！" : `❌ 正確答案：${esc(answerText)}`}</h3>
      ${q.explain ? `<p>${esc(q.explain)}</p>` : ""}
      <button class="btn primary next">${quiz.index + 1 < quiz.list.length ? "下一題 →" : "看結果 →"}</button>`;
    const nextBtn = fb.querySelector(".next");
    nextBtn.addEventListener("click", next);
    nextBtn.focus();
  }

  function next() {
    quiz.index++;
    if (quiz.index < quiz.list.length) renderQuestion();
    else renderResult();
  }

  const fmt = (n) => (Number.isInteger(n) ? n : n.toFixed(1));

  /* ---------- 結果 ---------- */
  function renderResult() {
    const { results } = quiz;
    const score = results.reduce((s, r) => s + r.score, 0);
    const pct = results.length ? Math.round((score / results.length) * 100) : 0;
    const best = store.get("quiz-best", {});
    const isRecord = best[quiz.catKey] == null || pct > best[quiz.catKey];
    if (isRecord && results.length >= 5) {
      best[quiz.catKey] = pct;
      store.set("quiz-best", best);
    }
    const msg = pct >= 90 ? "太強了，知識王！🏆" : pct >= 70 ? "表現很棒！🎉" : pct >= 50 ? "不錯喔，再接再厲！💪" : "多玩幾次就會進步！📚";
    const wrong = results.filter((r) => r.score < 1).map((r) => r.q);

    const rows = results.map((r, i) => {
      const q = r.q;
      const correct = q.type === "short" ? q.accept[0] : q.type === "qa" ? "（自評）" : q.answer;
      const mark = r.score === 1 ? "✅" : r.score > 0 ? "🟡" : "❌";
      return `<li class="review-item">
        <span class="mark">${mark}</span>
        <div><p class="rq">${i + 1}. ${esc(q.q)} ${q.emoji ? esc(q.emoji) : ""}</p>
        <p class="ra">你的答案：${esc(r.given || "—")}　｜　正解：${esc(correct)}</p></div></li>`;
    }).join("");

    $app.innerHTML = `
      <section class="panel result">
        <div class="score-ring" style="--pct:${pct}"><span>${pct}<small>%</small></span></div>
        <h2>${msg}</h2>
        <p>${esc(quiz.title)}：${results.length} 題中得到 ${fmt(score)} 分${isRecord && results.length >= 5 ? "　🌟 新紀錄！" : ""}</p>
        <div class="actions">
          ${wrong.length ? `<button class="btn primary retry-wrong">🔁 重練錯題（${wrong.length}）</button>` : ""}
          <button class="btn again">再玩一次</button>
          <button class="btn home">回首頁</button>
        </div>
        <h3>答題回顧</h3>
        <ol class="review">${rows}</ol>
      </section>`;
    $app.querySelector(".retry-wrong")?.addEventListener("click", () => startQuiz(quiz.title + "（錯題）", quiz.catKey + "-retry", shuffle(wrong)));
    $app.querySelector(".again").addEventListener("click", () => renderSetup(quiz.catKey.replace(/-retry$/, "")));
    $app.querySelector(".home").addEventListener("click", renderHome);
  }

  /* ---------- 題庫瀏覽 ---------- */
  function renderBank() {
    const catOpts = CATEGORIES.map((c) => `<option value="${c.id}">${c.icon} ${c.name}</option>`).join("");
    const typeOpts = Object.entries(TYPES).map(([k, t]) => `<option value="${k}">${t.icon} ${t.name}</option>`).join("");
    $app.innerHTML = `
      <section class="panel bank">
        <h2>📚 題庫總覽</h2>
        <div class="stats">${CATEGORIES.map((c) => {
          const qs = QUESTIONS.filter((q) => q.cat === c.id);
          return `<div class="stat"><b>${c.icon} ${c.name}</b>${Object.keys(TYPES).map((t) => `<span>${TYPES[t].name} ${qs.filter((q) => q.type === t).length}</span>`).join("")}</div>`;
        }).join("")}</div>
        <div class="filters">
          <select id="f-cat"><option value="">全部主題</option>${catOpts}</select>
          <select id="f-type"><option value="">全部題型</option>${typeOpts}</select>
          <input id="f-q" class="text-input" placeholder="搜尋題目關鍵字">
          <button class="btn" id="export">⬇️ 匯出 JSON</button>
        </div>
        <p class="hint" id="bank-count"></p>
        <ol class="bank-list"></ol>
        <p class="credits">圖片來源：Wikimedia Commons／Wikipedia（各圖授權見 <code>images/credits.json</code>）。線上擴充題目來自 <a href="https://opentdb.com/" target="_blank" rel="noopener">Open Trivia DB</a>（CC BY-SA 4.0）。旋律皆為公有領域童謠、民謠與古典樂。</p>
      </section>`;
    const list = $app.querySelector(".bank-list");
    const draw = () => {
      const c = $app.querySelector("#f-cat").value;
      const t = $app.querySelector("#f-type").value;
      const kw = $app.querySelector("#f-q").value.trim();
      const qs = QUESTIONS.filter((q) => (!c || q.cat === c) && (!t || q.type === t) && (!kw || JSON.stringify(q).includes(kw)));
      $app.querySelector("#bank-count").textContent = `共 ${qs.length} 題`;
      list.innerHTML = qs.map((q) => {
        const ans = q.type === "short" ? q.accept.join("／") : q.type === "qa" ? q.ref : q.answer;
        return `<li>
          <div class="q-meta"><span class="badge">${TYPES[q.type].icon} ${TYPES[q.type].name}</span><span class="badge soft">${catById[q.cat].icon} ${catById[q.cat].name}</span>${q.melody ? `<button class="link play" data-m="${q.melody}">▶️ 旋律</button>` : ""}</div>
          <p class="rq">${esc(q.q)} ${q.emoji ? `<span class="inline-emoji">${esc(q.emoji)}</span>` : ""}</p>
          ${q.img ? `<img class="thumb" src="images/${esc(q.img)}" alt="" loading="lazy">` : ""}
          ${q.options ? `<p class="ra">選項：${q.options.map(esc).join("、")}</p>` : ""}
          <details><summary>看答案</summary><p>${esc(ans)}</p>${q.explain ? `<p class="ra">${esc(q.explain)}</p>` : ""}</details>
        </li>`;
      }).join("");
      list.querySelectorAll(".play").forEach((b) => b.addEventListener("click", () => playMelody(b.dataset.m)));
    };
    ["#f-cat", "#f-type", "#f-q"].forEach((s) => $app.querySelector(s).addEventListener("input", draw));
    $app.querySelector("#export").addEventListener("click", () => {
      const data = { categories: CATEGORIES, types: TYPES, melodies: MELODIES, questions: QUESTIONS.map(({ id, ...q }) => q) };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "quiz-bank.json" });
      a.click();
      URL.revokeObjectURL(a.href);
    });
    draw();
  }

  /* ---------- 導覽 ---------- */
  document.querySelectorAll("[data-nav]").forEach((el) =>
    el.addEventListener("click", (e) => {
      e.preventDefault();
      (el.dataset.nav === "bank" ? renderBank : renderHome)();
      window.scrollTo(0, 0);
    })
  );
  renderHome();
})();
