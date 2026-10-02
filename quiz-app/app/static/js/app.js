/* 知識大挑戰 —— 前端（題目與判分都在伺服器，這裡只負責畫面） */
(() => {
  "use strict";

  const $app = document.getElementById("app");
  const CAT_ICON = { anime: "🎬", life: "🏠", history: "📜", travel: "✈️", riddle: "🧩", animal: "🐾", all: "🎲" };
  const CAT_DESC = {
    anime: "日本動漫、吉卜力、經典角色",
    life: "健康、安全、節慶與日常",
    history: "中外歷史事件、人物與古蹟",
    travel: "世界景點、首都與地理",
    riddle: "字謎、腦筋急轉彎、成語圖謎",
    animal: "動物習性、冷知識、認動物",
    all: "從所有主題隨機出題",
  };
  const DIFF = { easy: { name: "簡單", icon: "🌱" }, medium: { name: "中等", icon: "🌟" }, hard: { name: "困難", icon: "🔥" } };
  const TYPES = { single: { name: "單選題", icon: "🔘" }, image: { name: "圖片題", icon: "🖼️" }, short: { name: "簡答題", icon: "✏️" }, qa: { name: "問答題", icon: "💬" } };

  let CONFIG = null; // /api/config
  let ME = { user: null, attempts: [] }; // /api/me

  /* ---------- 小工具 ---------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (Number.isInteger(n) ? n : Number(n).toFixed(1));
  const catName = (c) => (c === "all" ? "綜合挑戰" : CONFIG.categories[c]);

  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail || "發生錯誤，請稍後再試");
      err.status = res.status;
      throw err;
    }
    return data;
  }
  const loginUrl = (next = location.pathname + location.search) => `/auth/google/login?next=${encodeURIComponent(next)}`;

  /* ---------- 節目效果：音效、彩帶、懸念 ---------- */
  const sound = {
    on: (() => { try { return localStorage.getItem("quiz-sound") !== "off"; } catch { return true; } })(),
    ctx: null,
    play(notes) {
      if (!this.on) return;
      try {
        this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
        let t = this.ctx.currentTime;
        for (const [freq, len, type = "sine", vol = 0.25] of notes) {
          const osc = this.ctx.createOscillator(), gain = this.ctx.createGain();
          osc.type = type;
          osc.frequency.value = freq;
          gain.gain.setValueAtTime(vol, t);
          gain.gain.exponentialRampToValueAtTime(0.001, t + len);
          osc.connect(gain).connect(this.ctx.destination);
          osc.start(t);
          osc.stop(t + len);
          t += len * 0.8;
        }
      } catch { /* 瀏覽器不支援就靜音 */ }
    },
    tick() { this.play([[880, 0.05, "square", 0.05]]); },
    correct() { this.play([[784, 0.12], [1047, 0.12], [1319, 0.35]]); },
    wrong() { this.play([[196, 0.25, "sawtooth", 0.12], [147, 0.4, "sawtooth", 0.12]]); },
  };

  function confetti() {
    const colors = ["#ff6fa3", "#ffd166", "#7ad7c0", "#a78bfa", "#7cc6fe"];
    const box = Object.assign(document.createElement("div"), { className: "confetti" });
    for (let i = 0; i < 60; i++) {
      const p = document.createElement("i");
      p.style.cssText = `left:${Math.random() * 100}%;background:${colors[i % colors.length]};` +
        `animation-delay:${Math.random() * 0.25}s;animation-duration:${1 + Math.random() * 0.8}s;` +
        `--dx:${(Math.random() - 0.5) * 160}px;--rot:${Math.random() * 720}deg`;
      box.append(p);
    }
    document.body.append(box);
    setTimeout(() => box.remove(), 2200);
  }

  // 送出答案後先「揭曉中…」吊一下胃口，再公布結果
  async function suspense(promise) {
    const bar = Object.assign(document.createElement("div"), { className: "suspense", innerHTML: "揭曉中<span>.</span><span>.</span><span>.</span>" });
    $app.querySelector(".answer-area").after(bar);
    const ticks = setInterval(() => sound.tick(), 220);
    try {
      const [result] = await Promise.all([promise, new Promise((r) => setTimeout(r, 1100))]);
      return result;
    } finally {
      clearInterval(ticks);
      bar.remove();
    }
  }

  let streak = 0;

  function toast(msg) {
    const el = Object.assign(document.createElement("div"), { className: "toast", textContent: msg });
    document.body.append(el);
    setTimeout(() => el.remove(), 3500);
  }

  function confirmDialog(html, okText = "確定") {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "modal-backdrop";
      wrap.innerHTML = `<div class="modal panel" role="dialog" aria-modal="true">${html}
        <div class="actions"><button class="btn cancel">再想想</button><button class="btn primary ok">${esc(okText)}</button></div></div>`;
      document.body.append(wrap);
      const done = (v) => { wrap.remove(); resolve(v); };
      wrap.querySelector(".ok").addEventListener("click", () => done(true));
      wrap.querySelector(".cancel").addEventListener("click", () => done(false));
      wrap.addEventListener("click", (e) => e.target === wrap && done(false));
      wrap.querySelector(".ok").focus();
    });
  }

  function renderNav() {
    const u = ME.user;
    document.getElementById("account").innerHTML = u
      ? `${u.picture ? `<img class="avatar" src="${esc(u.picture)}" alt="" referrerpolicy="no-referrer">` : ""}
         <span class="who">${esc(u.name || u.email)}</span>
         ${u.is_admin ? `<a href="#" data-nav="admin">管理</a>` : ""}
         <button class="link" id="logout">登出</button>`
      : `<a class="btn google" href="${loginUrl()}"><span class="g">G</span> Google 登入</a>`;
    document.getElementById("account").insertAdjacentHTML("afterbegin",
      `<button class="link sound-toggle" title="音效開關">${sound.on ? "🔊" : "🔇"}</button>`);
    document.querySelector(".sound-toggle").addEventListener("click", (e) => {
      sound.on = !sound.on;
      try { localStorage.setItem("quiz-sound", sound.on ? "on" : "off"); } catch { /* 忽略 */ }
      e.currentTarget.textContent = sound.on ? "🔊" : "🔇";
    });
    document.getElementById("logout")?.addEventListener("click", async () => {
      await api("/auth/logout", {});
      location.href = "/";
    });
    bindNav(document.getElementById("account"));
  }

  function bindNav(root) {
    root.querySelectorAll("[data-nav]").forEach((el) =>
      el.addEventListener("click", (e) => {
        e.preventDefault();
        go(el.dataset.nav);
      })
    );
  }

  function go(view) {
    history.replaceState(null, "", view === "home" ? "/" : `/?view=${view}`);
    ({ home: renderHome, bank: renderBank, admin: renderAdmin }[view] || renderHome)();
    window.scrollTo(0, 0);
  }

  const attemptFor = (cat, diff) => ME.attempts.find((a) => a.category === cat && a.difficulty === diff);

  /* ---------- 首頁 ---------- */
  function renderHome() {
    const cats = [...Object.keys(CONFIG.categories), "all"];
    const cards = cats.map((c) => {
      const pills = CONFIG.difficulties.map((d) => {
        const n = c === "all"
          ? Object.keys(CONFIG.categories).reduce((s, k) => s + (CONFIG.counts[`${k}:${d}`] || 0), 0)
          : CONFIG.counts[`${c}:${d}`] || 0;
        const a = attemptFor(c, d);
        let state = "open", label = `${n} 題`;
        if (a?.finished) { state = "done"; label = `${fmt(a.score)} / ${a.total} 分`; }
        else if (a) { state = "doing"; label = `繼續 ${a.answered}/${a.total}`; }
        else if (!n) { state = "empty"; label = "準備中"; }
        return `<button class="diff-pill ${state}" data-cat="${c}" data-diff="${d}" ${state === "done" || state === "empty" ? "disabled" : ""}>
          <span>${DIFF[d].icon} ${DIFF[d].name}</span><small>${label}</small></button>`;
      }).join("");
      return `<div class="cat-card" data-cat="${c}">
          <span class="cat-icon">${CAT_ICON[c]}</span>
          <span class="cat-name">${esc(catName(c))}</span>
          <span class="cat-desc">${esc(CAT_DESC[c])}</span>
          <div class="diff-pills">${pills}</div>
        </div>`;
    }).join("");

    $app.innerHTML = `
      <section class="hero">
        <span class="sparkle s1">✨</span><span class="sparkle s2">💖</span><span class="sparkle s3">⭐</span>
        <svg class="mascot" viewBox="0 0 140 112" role="img" aria-label="吉祥物問問"><use href="#mascot"/></svg>
        <h1>知識大挑戰</h1>
        <p>六大主題、三種難度，共 <strong>${CONFIG.total}</strong> 題。每個主題的每種難度，<strong>每人只能挑戰一次</strong>！</p>
        ${ME.user ? "" : `<p class="login-cta"><a class="btn primary" href="${loginUrl("/")}">用 Google 帳號登入開始挑戰</a></p>`}
      </section>
      <section class="cat-grid">${cards}</section>`;

    $app.querySelectorAll(".diff-pill:not([disabled])").forEach((el) =>
      el.addEventListener("click", () => startOrResume(el.dataset.cat, el.dataset.diff))
    );
  }

  async function startOrResume(cat, diff) {
    if (!ME.user) {
      location.href = loginUrl("/");
      return;
    }
    const existing = attemptFor(cat, diff);
    if (!existing) {
      const ok = await confirmDialog(
        `<h2>${CAT_ICON[cat]} ${esc(catName(cat))}・${DIFF[diff].icon} ${DIFF[diff].name}</h2>
         <p>共 ${CONFIG.per_attempt} 題。<strong>每個主題的每種難度只能挑戰一次</strong>，按下開始就算使用這次機會，中途離開可以回來繼續，但不能重來。</p>`,
        "開始挑戰"
      );
      if (!ok) return;
    }
    try {
      const { attempt_id } = await api("/api/attempts", { category: cat, difficulty: diff });
      await loadMe();
      runAttempt(attempt_id);
    } catch (e) {
      toast(e.message);
    }
  }

  /* ---------- 作答 ---------- */
  let current = null; // { data, index }

  async function runAttempt(id) {
    const data = await api(`/api/attempts/${id}`);
    if (data.finished) return renderResult(data);
    // 從第一個還沒完成的題目開始（問答題作答後還要自評）
    const index = data.questions.findIndex((q) => !data.results[q.id] || data.results[q.id].score === null);
    current = { data, index: Math.max(index, 0) };
    streak = 0;
    renderQuestion();
  }

  function renderQuestion() {
    const { data, index } = current;
    const q = data.questions[index];
    const total = data.questions.length;
    const score = Object.values(data.results).reduce((s, r) => s + (r.score || 0), 0);
    const pending = data.results[q.id]; // 問答題已作答、還沒自評

    let media = "";
    if (q.img) media = `<figure class="q-img"><img src="${esc(q.img)}" alt="題目圖片"></figure>`;
    if (q.emoji) media = `<div class="q-emoji" aria-label="表情符號圖謎">${esc(q.emoji)}</div>`;

    let body = "";
    if (q.type === "single" || q.type === "image") {
      body = `<div class="options">${q.options.map((o) => `<button class="option" data-v="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
    } else if (q.type === "short") {
      body = `<form class="short-form"><input class="text-input" name="ans" autocomplete="off" placeholder="輸入你的答案" maxlength="100"><button class="btn primary" type="submit">送出</button></form>`;
    } else {
      body = `<textarea class="text-input area" maxlength="2000" placeholder="寫下你的想法，送出後會顯示參考答案">${esc(pending?.given || "")}</textarea>
              <button class="btn primary reveal" type="button" ${pending ? "hidden" : ""}>送出並看參考答案</button>`;
    }

    $app.innerHTML = `
      <section class="panel quiz">
        <header class="quiz-head">
          <button class="link quit">← 回首頁</button>
          <span>${CAT_ICON[data.category]} ${esc(catName(data.category))}・${DIFF[data.difficulty].icon} ${DIFF[data.difficulty].name}</span>
          <span class="score-pill">得分 ${fmt(score)}</span>
        </header>
        <div class="progress"><div style="width:${(index / total) * 100}%"></div></div>
        <div class="q-intro">第 ${index + 1} 題${streak >= 2 ? `<span class="streak">🔥 連對 ${streak} 題</span>` : ""}</div>
        <div class="q-meta">
          <span class="badge">${TYPES[q.type].icon} ${TYPES[q.type].name}</span>
          ${data.category === "all" ? `<span class="badge soft">${CAT_ICON[q.cat]} ${esc(catName(q.cat))}</span>` : ""}
          <span class="q-count">${index + 1} / ${total}</span>
        </div>
        <h2 class="q-text">${esc(q.q)}</h2>
        ${media}
        <div class="answer-area">${body}</div>
        <div class="feedback" hidden></div>
      </section>`;

    $app.querySelector(".quit").addEventListener("click", async () => {
      await loadMe();
      go("home");
    });

    const submit = async (given) => {
      try {
        const r = await api(`/api/attempts/${data.id}/answer`, { question_id: q.id, given });
        data.results[q.id] = r;
        return r;
      } catch (e) {
        toast(e.message);
        if (e.status === 409) runAttempt(data.id);
        return null;
      }
    };

    if (q.type === "single" || q.type === "image") {
      $app.querySelectorAll(".option").forEach((btn) =>
        btn.addEventListener("click", async () => {
          $app.querySelectorAll(".option").forEach((b) => (b.disabled = true));
          btn.classList.add("picked");
          const r = await suspense(submit(btn.dataset.v));
          btn.classList.remove("picked");
          if (!r) return;
          $app.querySelectorAll(".option").forEach((b) => b.dataset.v === r.correct_answer && b.classList.add("correct"));
          if (!r.score) btn.classList.add("wrong");
          showFeedback(r);
        })
      );
    } else if (q.type === "short") {
      const form = $app.querySelector(".short-form");
      form.ans.focus();
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const v = form.ans.value.trim();
        if (!v) return;
        form.ans.disabled = true;
        form.querySelector("button").disabled = true;
        const r = await suspense(submit(v));
        if (!r) return;
        form.ans.classList.add(r.score ? "correct" : "wrong");
        showFeedback(r);
      });
    } else {
      const area = $app.querySelector("textarea");
      if (pending) {
        area.readOnly = true;
        showSelfGrade(pending);
      }
      $app.querySelector(".reveal").addEventListener("click", async (e) => {
        e.target.disabled = true;
        const r = await submit(area.value.trim());
        if (!r) return;
        area.readOnly = true;
        e.target.hidden = true;
        showSelfGrade(r);
      });
    }
  }

  const CHEERS = ["答對了！", "太神啦！", "完全正確！", "你是天才嗎！", "漂亮！"];
  const OOPS = ["差一點點！", "哎呀～", "沒想到吧！", "被騙了吧！"];
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

  function showFeedback(r) {
    if (r.score) {
      streak++;
      sound.correct();
      confetti();
    } else {
      streak = 0;
      sound.wrong();
      $app.querySelector(".quiz").classList.add("shake");
    }
    const fb = $app.querySelector(".feedback");
    fb.hidden = false;
    fb.className = "feedback pop " + (r.score ? "good" : "bad");
    fb.innerHTML = `
      <h3>${r.score ? `🎉 ${pick(CHEERS)}${streak >= 2 ? `　🔥 連對 ${streak} 題` : ""}` : `😵 ${pick(OOPS)}正確答案是：${esc(r.correct_answer)}`}</h3>
      ${r.explain ? `<div class="fact-card"><b>🤯 冷知識</b><p>${esc(r.explain)}</p></div>` : ""}
      <button class="btn primary next">${current.index + 1 < current.data.questions.length ? "下一題 →" : "看結果 →"}</button>`;
    const btn = fb.querySelector(".next");
    btn.addEventListener("click", next);
    btn.focus();
  }

  function showSelfGrade(r) {
    const { data } = current;
    const q = data.questions[current.index];
    const fb = $app.querySelector(".feedback");
    fb.hidden = false;
    fb.className = "feedback neutral";
    fb.innerHTML = `
      <h3>📖 參考答案</h3><p>${esc(r.ref)}</p>
      <p class="self-label">對照一下，你覺得自己答得如何？（誠實自評喔）</p>
      <div class="self-grade">
        <button class="btn" data-s="1">😎 大致答對</button>
        <button class="btn" data-s="0.5">🤔 答對一部分</button>
        <button class="btn" data-s="0">😅 沒答出來</button>
      </div>`;
    fb.querySelectorAll(".self-grade button").forEach((b) =>
      b.addEventListener("click", async () => {
        fb.querySelectorAll("button").forEach((x) => (x.disabled = true));
        try {
          await api(`/api/attempts/${data.id}/self-grade`, { question_id: q.id, score: Number(b.dataset.s) });
          streak = Number(b.dataset.s) === 1 ? streak + 1 : 0;
          data.results[q.id].score = Number(b.dataset.s);
          next();
        } catch (e) {
          toast(e.message);
          runAttempt(data.id);
        }
      })
    );
  }

  async function next() {
    current.index++;
    if (current.index < current.data.questions.length) return renderQuestion();
    await loadMe();
    renderResult(await api(`/api/attempts/${current.data.id}`));
  }

  /* ---------- 結果 ---------- */
  function renderResult(data) {
    const pct = data.total ? Math.round((data.score / data.total) * 100) : 0;
    const msg = pct >= 90 ? "太強了，知識王！🏆" : pct >= 70 ? "表現很棒！🎉" : pct >= 50 ? "不錯喔，再接再厲！💪" : "下次換個主題試試看！📚";
    const rows = data.questions.map((q, i) => {
      const r = data.results[q.id] || {};
      const mark = r.score === 1 ? "✅" : r.score > 0 ? "🟡" : "❌";
      const answer = r.correct_answer;
      return `<li class="review-item"><span class="mark">${mark}</span>
        <div><p class="rq">${i + 1}. ${esc(q.q)} ${q.emoji ? esc(q.emoji) : ""}</p>
        <p class="ra">你的答案：${esc(r.given || "—")}　｜　正解：${esc(answer)}</p></div></li>`;
    }).join("");
    $app.innerHTML = `
      <section class="panel result">
        <div class="score-ring" style="--pct:${pct}"><span>${pct}<small>%</small></span></div>
        <h2>${msg}</h2>
        <p>${CAT_ICON[data.category]} ${esc(catName(data.category))}・${DIFF[data.difficulty].icon} ${DIFF[data.difficulty].name}：${data.total} 題中得到 ${fmt(data.score)} 分</p>
        <p class="hint">這個組合已挑戰完成，換個主題或難度繼續吧！</p>
        <div class="actions"><button class="btn primary home">選下一個挑戰</button><button class="btn bank">看題庫總覽</button></div>
        <h3>答題回顧</h3>
        <ol class="review">${rows}</ol>
      </section>`;
    $app.querySelector(".home").addEventListener("click", () => go("home"));
    $app.querySelector(".bank").addEventListener("click", () => go("bank"));
    if (pct >= 70) {
      confetti();
      sound.play([[523, 0.15], [659, 0.15], [784, 0.15], [1047, 0.5]]);
    }
  }

  /* ---------- 題庫總覽（訂閱制） ---------- */
  const bankFilters = { cat: "", difficulty: "", type: "", q: "", page: 1 };

  // 未登入：請先登入（瀏覽題庫免費，只需要登入）
  function renderLoginPrompt() {
    $app.innerHTML = `
      <section class="panel paywall">
        <svg class="mascot small" viewBox="0 0 140 112" aria-hidden="true"><use href="#mascot"/></svg>
        <h2>📚 題庫總覽</h2>
        <p>登入後就能<strong>免費</strong>瀏覽全部 <strong>${CONFIG.total}</strong> 題、篩選搜尋並匯出 PDF。</p>
        <a class="btn primary big" href="${loginUrl("/?view=bank")}">用 Google 帳號登入</a>
      </section>`;
  }

  // 免費會員在題庫上方看到的訂閱方案
  function subscribeBanner() {
    return `
      <div class="sub-banner">
        <div>
          <b>🔓 訂閱解鎖全部答案與解說</b>
          <p>每月 NT$${CONFIG.price_twd}，隨時可以取消。訂閱後題庫與 PDF 都會附上所有答案。</p>
        </div>
        <button class="btn primary" id="subscribe">訂閱 NT$${CONFIG.price_twd} / 月</button>
      </div>`;
  }

  function bindSubscribe() {
    document.getElementById("subscribe")?.addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        location.href = (await api("/api/billing/checkout", {})).url;
      } catch (err) {
        toast(err.message);
        e.target.disabled = false;
      }
    });
  }

  async function renderBank() {
    if (!ME.user) return renderLoginPrompt();
    const subscribed = ME.user.subscribed;
    const opt = (obj, sel, labelFn) => Object.entries(obj).map(([k, v]) => `<option value="${k}" ${sel === k ? "selected" : ""}>${labelFn(k, v)}</option>`).join("");
    $app.innerHTML = `
      <section class="panel bank">
        <div class="bank-head">
          <h2>📚 題庫總覽</h2>
          ${subscribed ? `<button class="link" id="portal">管理訂閱</button>` : ""}
        </div>
        ${subscribed
          ? `<p class="hint">💖 你是訂閱會員，可以看到全部答案與解說。</p>`
          : subscribeBanner() + `<p class="hint">免費瀏覽所有題目；你已挑戰完成的「主題 × 難度」也會顯示答案。</p>`}
        <div class="filters">
          <select id="f-cat"><option value="">全部主題</option>${opt(CONFIG.categories, bankFilters.cat, (k, v) => `${CAT_ICON[k]} ${v}`)}</select>
          <select id="f-diff"><option value="">全部難度</option>${opt(DIFF, bankFilters.difficulty, (k, v) => `${v.icon} ${v.name}`)}</select>
          <select id="f-type"><option value="">全部題型</option>${opt(TYPES, bankFilters.type, (k, v) => `${v.icon} ${v.name}`)}</select>
          <input id="f-q" class="text-input" placeholder="搜尋題目關鍵字" value="${esc(bankFilters.q)}">
          <a class="btn primary" id="export">📄 匯出 PDF</a>
        </div>
        <p class="hint" id="bank-count">載入中…</p>
        <ol class="bank-list"></ol>
        <div class="pager"></div>
        <p class="credits">圖片來源：Wikimedia Commons／Wikipedia（自由授權）。</p>
      </section>`;

    bindSubscribe();
    document.getElementById("portal")?.addEventListener("click", async () => {
      try {
        location.href = (await api("/api/billing/portal", {})).url;
      } catch (e) {
        toast(e.message);
      }
    });

    const query = () => new URLSearchParams(Object.entries(bankFilters).filter(([, v]) => v !== "")).toString();
    const updateExport = () => {
      const { page, ...rest } = bankFilters;
      document.getElementById("export").href = `/api/bank/export.pdf?${new URLSearchParams(Object.entries(rest).filter(([, v]) => v))}`;
    };

    const draw = async () => {
      updateExport();
      let data;
      try {
        data = await api(`/api/bank?${query()}`);
      } catch (e) {
        return toast(e.message);
      }
      document.getElementById("bank-count").textContent = `共 ${data.total} 題・第 ${data.page} / ${data.pages} 頁`;
      $app.querySelector(".bank-list").innerHTML = data.questions.map((q) => {
        const answer = q.answer === undefined
          ? `<p class="locked">🔒 答案為訂閱會員內容<button class="link unlock">　訂閱解鎖 →</button></p>`
          : `<details><summary>看答案</summary><p>${esc(q.answer)}</p>${q.explain ? `<p class="ra">${esc(q.explain)}</p>` : ""}</details>`;
        return `<li>
          <div class="q-meta"><span class="badge">${TYPES[q.type].icon} ${TYPES[q.type].name}</span>
            <span class="badge soft">${CAT_ICON[q.cat]} ${esc(catName(q.cat))}</span>
            <span class="badge diff-${q.difficulty}">${DIFF[q.difficulty].icon} ${DIFF[q.difficulty].name}</span></div>
          <p class="rq">${esc(q.q)} ${q.emoji ? `<span class="inline-emoji">${esc(q.emoji)}</span>` : ""}</p>
          ${q.img ? `<img class="thumb" src="${esc(q.img)}" alt="" loading="lazy">` : ""}
          ${q.options ? `<p class="ra">選項：${q.options.map(esc).join("、")}</p>` : ""}
          ${answer}
        </li>`;
      }).join("");
      $app.querySelectorAll(".unlock").forEach((b) => b.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
        document.getElementById("subscribe")?.focus();
      }));
      const pager = $app.querySelector(".pager");
      pager.innerHTML = data.pages > 1
        ? `<button class="btn" data-p="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""}>← 上一頁</button>
           <button class="btn" data-p="${data.page + 1}" ${data.page >= data.pages ? "disabled" : ""}>下一頁 →</button>`
        : "";
      pager.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        bankFilters.page = Number(b.dataset.p);
        draw();
        window.scrollTo(0, 0);
      }));
    };

    let timer;
    [["f-cat", "cat"], ["f-diff", "difficulty"], ["f-type", "type"], ["f-q", "q"]].forEach(([id, key]) =>
      document.getElementById(id).addEventListener("input", (e) => {
        bankFilters[key] = e.target.value.trim();
        bankFilters.page = 1;
        clearTimeout(timer);
        timer = setTimeout(draw, key === "q" ? 300 : 0);
      })
    );
    draw();
  }

  /* ---------- 管理 ---------- */
  async function renderAdmin() {
    if (!ME.user?.is_admin) return go("home");
    const s = await api("/api/admin/stats");
    $app.innerHTML = `
      <section class="panel admin">
        <h2>🛠️ 管理後台</h2>
        <div class="stats">
          <div class="stat"><b>${s.questions}</b><span>題目</span></div>
          <div class="stat"><b>${s.users}</b><span>使用者</span></div>
          <div class="stat"><b>${s.subscribers}</b><span>訂閱中</span></div>
          <div class="stat"><b>${s.finished_attempts} / ${s.attempts}</b><span>完成 / 開始的挑戰</span></div>
        </div>
        <h3>匯入題庫</h3>
        <p class="hint">選擇題庫 JSON 檔（可多選）。相同主題＋題目會更新，新的會新增，不會刪除舊題。</p>
        <input type="file" id="import-file" accept=".json,application/json" multiple>
        <h3>重設某人的挑戰</h3>
        <form id="reset-form" class="filters">
          <input class="text-input" name="email" placeholder="使用者 Email" required>
          <select name="category">${Object.entries({ ...CONFIG.categories, all: "綜合挑戰" }).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
          <select name="difficulty">${Object.entries(DIFF).map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("")}</select>
          <button class="btn" type="submit">重設</button>
        </form>
      </section>`;
    document.getElementById("import-file").addEventListener("change", async (e) => {
      try {
        let items = [];
        for (const f of e.target.files) items = items.concat(JSON.parse(await f.text()));
        const r = await api("/api/admin/import", items);
        toast(`匯入完成：新增 ${r.added} 題、更新 ${r.updated} 題`);
        CONFIG = await api("/api/config");
        renderAdmin();
      } catch (err) {
        toast(err.message);
      }
    });
    document.getElementById("reset-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        await api("/api/admin/reset-attempt", { email: f.email.value, category: f.category.value, difficulty: f.difficulty.value });
        toast("已重設，對方可以重新挑戰");
      } catch (err) {
        toast(err.message);
      }
    });
  }

  /* ---------- 啟動 ---------- */
  async function loadMe() {
    ME = await api("/api/me");
    if (!ME.attempts) ME.attempts = [];
    renderNav();
  }

  async function boot() {
    bindNav(document.querySelector(".topbar"));
    [CONFIG] = await Promise.all([api("/api/config"), loadMe()]);
    const params = new URLSearchParams(location.search);
    if (params.get("checkout") === "success" && params.get("session_id")) {
      try {
        const r = await api("/api/billing/sync", { session_id: params.get("session_id") });
        await loadMe();
        toast(r.subscribed ? "🎉 訂閱成功！歡迎使用題庫總覽" : "付款處理中，稍後重新整理即可");
      } catch (e) {
        toast(e.message);
      }
    } else if (params.get("checkout") === "cancelled") {
      toast("已取消付款");
    } else if (params.get("login") === "cancelled") {
      toast("已取消登入");
    }
    go(params.get("view") || "home");
  }

  boot().catch((e) => {
    $app.innerHTML = `<section class="panel"><h2>載入失敗</h2><p>${esc(e.message)}</p></section>`;
  });
})();
