/* 知識大挑戰 —— 前端（題目與判分都在伺服器，這裡只負責畫面） */
(() => {
  "use strict";

  const $app = document.getElementById("app");
  const CAT_ICON = { anime: "🎬", life: "🏠", history: "📜", travel: "✈️", riddle: "🧩", animal: "🐾", trivia: "🤯", all: "🎲" };
  const CAT_DESC = {
    anime: "日本動漫、吉卜力、經典角色",
    life: "健康、安全、節慶與日常",
    history: "中外歷史事件、人物與古蹟",
    travel: "世界景點、首都與地理",
    riddle: "字謎、腦筋急轉彎、成語圖謎",
    animal: "動物習性、冷知識、認動物",
    trivia: "顛覆常識的科學、歷史、生活冷知識",
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
      ? `<a href="#" class="me-link" data-nav="profile" title="個人檔案">${avatarHtml(32)}
           <span class="who">${esc(displayName())}</span></a>
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

  /* ---------- 個人外觀 ---------- */
  const FRAMES = { none: "無", ribbon: "蝴蝶結", heart: "愛心", star: "星星", flower: "花朵", crown: "皇冠", rainbow: "彩虹" };
  const COLORS = { pink: "粉紅", lavender: "薰衣草", mint: "薄荷", sky: "天空藍", peach: "蜜桃", lemon: "檸檬" };
  const AVATAR_EMOJIS = ["🐰", "🐱", "🐶", "🐻", "🐼", "🐨", "🦊", "🐹", "🐧", "🦄", "🐸", "🐥",
    "🌸", "🌈", "⭐", "🍓", "🍰", "🧁", "🍡", "🎀", "💖", "☁️", "🌙", "🍀"];

  const displayName = (p = ME.profile, u = ME.user) => (p && p.nickname) || (u && (u.name || u.email)) || "";

  function avatarHtml(size, p = ME.profile, u = ME.user) {
    p = p || { avatar_type: "google", avatar_url: u?.picture || "", frame: "none" };
    let inner;
    if (p.avatar_type === "emoji" && p.avatar_emoji) inner = `<span class="avatar-img emoji">${esc(p.avatar_emoji)}</span>`;
    else if (p.avatar_url) inner = `<img class="avatar-img" src="${esc(p.avatar_url)}" alt="" referrerpolicy="no-referrer">`;
    else inner = `<span class="avatar-img emoji">${esc((displayName(p, u) || "?").slice(0, 1))}</span>`;
    return `<span class="avatar-wrap frame-${esc(p.frame || "none")}" style="--s:${size}px">${inner}</span>`;
  }

  function applyColor(color) {
    if (color && color !== "pink") document.documentElement.dataset.accent = color;
    else delete document.documentElement.dataset.accent;
  }

  // 上傳的圖片先在瀏覽器裁成正方形並縮小，再送到伺服器
  function resizeImage(file, size = 256) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const side = Math.min(img.width, img.height);
        const canvas = Object.assign(document.createElement("canvas"), { width: size, height: size });
        canvas.getContext("2d").drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
        URL.revokeObjectURL(img.src);
        const webp = canvas.toDataURL("image/webp", 0.85);
        resolve(webp.startsWith("data:image/webp") ? webp : canvas.toDataURL("image/jpeg", 0.85));
      };
      img.onerror = () => reject(new Error("無法讀取這張圖片，請換一張試試"));
      img.src = URL.createObjectURL(file);
    });
  }

  function renderProfile() {
    if (!ME.user) {
      location.href = loginUrl("/?view=profile");
      return;
    }
    const draft = { ...ME.profile };
    $app.innerHTML = `
      <section class="panel profile">
        <h2>🎀 個人檔案</h2>
        <div class="profile-preview">
          <div id="pv-avatar"></div>
          <div><b id="pv-name"></b><p class="hint">${esc(ME.user.email)}</p></div>
        </div>
        <fieldset>
          <legend>暱稱</legend>
          <input id="nickname" class="text-input" maxlength="20" placeholder="${esc(ME.user.name || "取個可愛的名字")}" value="${esc(draft.nickname)}">
        </fieldset>
        <fieldset>
          <legend>頭像</legend>
          <div class="chips">
            <label class="chip"><input type="radio" name="atype" value="google"> Google 大頭貼</label>
            <label class="chip"><input type="radio" name="atype" value="emoji"> 可愛圖案</label>
            <label class="chip"><input type="radio" name="atype" value="upload"> 上傳圖片</label>
          </div>
          <div class="emoji-grid" id="emoji-grid">${AVATAR_EMOJIS.map((e) => `<button type="button" class="emoji-pick" data-e="${e}">${e}</button>`).join("")}</div>
          <div id="upload-box" class="upload-box">
            <label class="btn">📷 選擇圖片<input type="file" id="avatar-file" accept="image/png,image/jpeg,image/webp" hidden></label>
            <span class="hint">支援 PNG、JPG、WebP，會自動裁成正方形</span>
          </div>
        </fieldset>
        <fieldset>
          <legend>頭像框</legend>
          <div class="frame-grid">${Object.entries(FRAMES).map(([k, v]) => `<button type="button" class="frame-pick" data-f="${k}"><span class="fp-avatar"></span><small>${v}</small></button>`).join("")}</div>
        </fieldset>
        <fieldset>
          <legend>主題顏色</legend>
          <div class="color-grid">${Object.entries(COLORS).map(([k, v]) => `<button type="button" class="color-pick c-${k}" data-c="${k}"><span></span><small>${v}</small></button>`).join("")}</div>
        </fieldset>
        <div class="actions"><button class="btn" id="cancel">取消</button><button class="btn primary" id="save">儲存</button></div>
      </section>`;

    const refresh = () => {
      document.getElementById("pv-avatar").innerHTML = avatarHtml(96, draft);
      document.getElementById("pv-name").textContent = displayName(draft);
      $app.querySelectorAll("input[name=atype]").forEach((r) => (r.checked = r.value === draft.avatar_type));
      document.getElementById("emoji-grid").hidden = draft.avatar_type !== "emoji";
      document.getElementById("upload-box").hidden = draft.avatar_type !== "upload";
      $app.querySelectorAll(".emoji-pick").forEach((b) => b.classList.toggle("on", b.dataset.e === draft.avatar_emoji));
      $app.querySelectorAll(".frame-pick").forEach((b) => {
        b.classList.toggle("on", b.dataset.f === draft.frame);
        b.querySelector(".fp-avatar").innerHTML = avatarHtml(48, { ...draft, frame: b.dataset.f });
      });
      $app.querySelectorAll(".color-pick").forEach((b) => b.classList.toggle("on", b.dataset.c === draft.color));
      applyColor(draft.color);
    };

    document.getElementById("nickname").addEventListener("input", (e) => { draft.nickname = e.target.value; refresh(); });
    $app.querySelectorAll("input[name=atype]").forEach((r) => r.addEventListener("change", () => {
      draft.avatar_type = r.value;
      if (r.value === "emoji" && !draft.avatar_emoji) draft.avatar_emoji = AVATAR_EMOJIS[0];
      if (r.value === "google") draft.avatar_url = ME.user.picture || "";
      if (r.value === "upload" && draft.has_upload) draft.avatar_url = `/api/profile/avatar?v=${Date.now()}`;
      refresh();
    }));
    $app.querySelectorAll(".emoji-pick").forEach((b) => b.addEventListener("click", () => { draft.avatar_emoji = b.dataset.e; refresh(); }));
    $app.querySelectorAll(".frame-pick").forEach((b) => b.addEventListener("click", () => { draft.frame = b.dataset.f; refresh(); }));
    $app.querySelectorAll(".color-pick").forEach((b) => b.addEventListener("click", () => { draft.color = b.dataset.c; refresh(); }));
    document.getElementById("avatar-file").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const p = await api("/api/profile/avatar", { data_url: await resizeImage(file) });
        Object.assign(draft, { avatar_type: "upload", avatar_url: p.avatar_url, has_upload: true });
        ME.profile = { ...ME.profile, avatar_url: p.avatar_url, has_upload: true, avatar_type: "upload" };
        toast("圖片上傳成功，記得按「儲存」");
        refresh();
      } catch (err) {
        toast(err.message);
      }
    });
    document.getElementById("cancel").addEventListener("click", () => { applyColor(ME.profile.color); go("home"); });
    document.getElementById("save").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        ME.profile = await api("/api/profile", {
          nickname: draft.nickname, avatar_type: draft.avatar_type, avatar_emoji: draft.avatar_emoji,
          frame: draft.frame, color: draft.color,
        });
        renderNav();
        toast("💖 已儲存你的個人檔案");
        go("home");
        return;
      } catch (err) {
        toast(err.message);
      }
      e.target.disabled = false;
    });
    refresh();
  }

  /* ---------- 左上角 ☰ 選單 ---------- */
  function closeMenu() {
    const menu = document.getElementById("menu");
    if (menu) menu.hidden = true;
    document.getElementById("menu-btn")?.setAttribute("aria-expanded", "false");
  }

  function setupMenu() {
    const btn = document.getElementById("menu-btn");
    const menu = document.getElementById("menu");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      btn.setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
    bindNav(menu);
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
    closeMenu();
    ({ home: renderHome, bank: renderBank, admin: renderAdmin, profile: renderProfile, teams: renderTeams }[view] || renderHome)();
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
        <p class="tagline">${Object.keys(CONFIG.categories).length} 大主題 × 三種難度，共 <strong>${CONFIG.total}</strong> 題！</p>
        <div class="rules">
          <span>🎯 個人挑戰：每個主題的每種難度限一次</span>
          <a href="#" class="rule-team">👥 組隊挑戰：不限次數，找朋友一起來！</a>
        </div>
        ${ME.user ? "" : `<p class="login-cta"><a class="btn primary" href="${loginUrl("/")}">用 Google 帳號登入開始挑戰</a></p>`}
      </section>
      <section class="cat-grid">${cards}</section>`;

    $app.querySelector(".rule-team").addEventListener("click", (e) => { e.preventDefault(); go("teams"); });
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
  let current = null; // { data, index, src }

  // src：{ base 作答 API 前綴, load 讀題目的網址, done 完成後要做什麼, reload 重新載入 }
  async function runQuiz(src) {
    const data = await api(src.load);
    if (data.finished) return src.done(data);
    // 從第一個還沒完成的題目開始（問答題作答後還要自評）
    const index = data.questions.findIndex((q) => !data.results[q.id] || data.results[q.id].score === null);
    current = { data, index: Math.max(index, 0), src };
    streak = 0;
    renderQuestion();
  }

  const runAttempt = (id) => runQuiz({
    base: `/api/attempts/${id}`, load: `/api/attempts/${id}`, label: "",
    done: renderResult, reload: () => runAttempt(id),
  });

  const runTeamQuiz = (code) => runQuiz({
    base: `/api/teams/${code}`, load: `/api/teams/${code}/play`, label: "👥 組隊・",
    done: () => renderTeam(code), reload: () => runTeamQuiz(code),
  });

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
          <span>${current.src.label}${CAT_ICON[data.category]} ${esc(catName(data.category))}・${DIFF[data.difficulty].icon} ${DIFF[data.difficulty].name}</span>
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
        const r = await api(`${current.src.base}/answer`, { question_id: q.id, given });
        data.results[q.id] = r;
        return r;
      } catch (e) {
        toast(e.message);
        if (e.status === 409) current.src.reload();
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
          await api(`${current.src.base}/self-grade`, { question_id: q.id, score: Number(b.dataset.s) });
          streak = Number(b.dataset.s) === 1 ? streak + 1 : 0;
          data.results[q.id].score = Number(b.dataset.s);
          next();
        } catch (e) {
          toast(e.message);
          current.src.reload();
        }
      })
    );
  }

  async function next() {
    current.index++;
    if (current.index < current.data.questions.length) return renderQuestion();
    await loadMe();
    current.src.done(await api(current.src.load));
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


  /* ---------- 組隊挑戰 ---------- */
  const STATUS = (t) => t.all_finished ? "🏆 已公布排名" : t.members.length < 2 ? "⏳ 等待隊友加入" : "✏️ 作答中";

  async function renderTeams() {
    if (!ME.user) return renderLoginNeeded("組隊挑戰", "/?view=teams");
    const cats = [...Object.keys(CONFIG.categories), "all"];
    $app.innerHTML = `
      <section class="panel teams">
        <h2>👥 組隊挑戰</h2>
        <p class="hint">開一個隊伍、把邀請連結傳給朋友，最多 3 人答同一組 ${CONFIG.per_attempt} 題，大家各自有空就作答；全員完成後公布隊內排名。組隊不會用掉個人挑戰的次數。</p>
        <fieldset>
          <legend>選擇主題</legend>
          <div class="chips">${cats.map((c, i) => `<label class="chip"><input type="radio" name="tcat" value="${c}" ${i === 0 ? "checked" : ""}> ${CAT_ICON[c]} ${esc(catName(c))}</label>`).join("")}</div>
        </fieldset>
        <fieldset>
          <legend>選擇難度</legend>
          <div class="chips">${CONFIG.difficulties.map((d, i) => `<label class="chip"><input type="radio" name="tdiff" value="${d}" ${i === 0 ? "checked" : ""}> ${DIFF[d].icon} ${DIFF[d].name}</label>`).join("")}</div>
        </fieldset>
        <button class="btn primary big" id="create-team">建立隊伍並取得邀請連結</button>
        <h3>我的隊伍</h3>
        <div id="my-teams" class="team-list"><p class="hint">載入中…</p></div>
      </section>`;
    document.getElementById("create-team").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        const { code } = await api("/api/teams", {
          category: $app.querySelector("input[name=tcat]:checked").value,
          difficulty: $app.querySelector("input[name=tdiff]:checked").value,
        });
        renderTeam(code);
      } catch (err) {
        toast(err.message);
        e.target.disabled = false;
      }
    });
    const { teams } = await api("/api/teams/mine");
    const box = document.getElementById("my-teams");
    if (!box) return;
    box.innerHTML = teams.length
      ? teams.map((t) => `
          <div class="team-row">
            <button class="team-open" data-code="${esc(t.code)}">
              <span>${CAT_ICON[t.category]} ${esc(catName(t.category))}・${DIFF[t.difficulty].icon} ${DIFF[t.difficulty].name}${t.is_owner ? ` <small class="badge soft">隊長</small>` : ""}</span>
              <span class="team-avatars">${t.members.map((m) => avatarHtml(28, m.profile)).join("")}</span>
              <small>${STATUS(t)}</small>
            </button>
            <button class="team-delete" data-code="${esc(t.code)}" data-owner="${t.is_owner ? 1 : 0}" title="${t.is_owner ? "刪除隊伍" : "退出隊伍"}" aria-label="${t.is_owner ? "刪除隊伍" : "退出隊伍"}">🗑️</button>
          </div>`).join("")
      : `<p class="hint">還沒有隊伍，建立一個邀請朋友吧！</p>`;
    box.querySelectorAll(".team-open").forEach((b) => b.addEventListener("click", () => renderTeam(b.dataset.code)));
    box.querySelectorAll(".team-delete").forEach((b) => b.addEventListener("click", async () => {
      if (await leaveTeam(b.dataset.code, b.dataset.owner === "1")) renderTeams();
    }));
  }

  // 隊長刪除整個隊伍；隊員退出隊伍
  async function leaveTeam(code, isOwner) {
    const ok = await confirmDialog(isOwner
      ? `<h2>🗑️ 刪除這個隊伍？</h2><p>所有成員的作答紀錄都會一起刪除，而且無法復原。</p>`
      : `<h2>👋 退出這個隊伍？</h2><p>你的作答紀錄會被移除，其他隊友不受影響。</p>`,
    isOwner ? "刪除隊伍" : "退出隊伍");
    if (!ok) return false;
    try {
      await api(`/api/teams/${encodeURIComponent(code)}/leave`, {});
      toast(isOwner ? "已刪除隊伍" : "已退出隊伍");
      return true;
    } catch (err) {
      toast(err.message);
      return false;
    }
  }

  function renderLoginNeeded(title, next) {
    $app.innerHTML = `
      <section class="panel paywall">
        <svg class="mascot small" viewBox="0 0 140 112" aria-hidden="true"><use href="#mascot"/></svg>
        <h2>${esc(title)}</h2>
        <p>每位參加的朋友都需要先用 Google 帳號登入喔！</p>
        <a class="btn primary big" href="${loginUrl(next)}">用 Google 帳號登入</a>
      </section>`;
  }

  async function renderTeam(code) {
    history.replaceState(null, "", `/?team=${encodeURIComponent(code)}`);
    if (!ME.user) return renderLoginNeeded("👥 朋友邀請你一起組隊挑戰！", `/?team=${encodeURIComponent(code)}`);
    let t;
    try {
      t = await api(`/api/teams/${encodeURIComponent(code)}`);
    } catch (e) {
      $app.innerHTML = `<section class="panel"><h2>找不到隊伍</h2><p>${esc(e.message)}</p><button class="btn primary" id="back">回組隊頁</button></section>`;
      document.getElementById("back").addEventListener("click", () => go("teams"));
      return;
    }
    const link = `${location.origin}/?team=${encodeURIComponent(t.code)}`;
    const memberRows = t.members.map((m) => `
      <li class="member">
        ${avatarHtml(44, m.profile)}
        <div><b>${esc(m.name)}</b>${m.user_id === t.members[0].user_id ? ` <small class="badge soft">隊長</small>` : ""}${m.user_id === t.me ? ` <small class="badge">我</small>` : ""}
          <p class="ra">${m.finished ? "✅ 已完成" : `作答中 ${m.answered} / ${t.total}`}${m.score !== null ? `・${fmt(m.score)} 分` : ""}</p></div>
      </li>`).join("");
    const slots = Array.from({ length: t.max_members - t.members.length }, () => `<li class="member empty"><span class="avatar-wrap" style="--s:44px"><span class="avatar-img emoji">＋</span></span><div><b>等待加入</b></div></li>`).join("");

    let action = "";
    if (!t.is_member) {
      action = t.members.length < t.max_members
        ? `<button class="btn primary big" id="join">加入這個隊伍</button>`
        : `<p class="hint">這個隊伍已經滿 ${t.max_members} 人了。</p>`;
    } else if (!t.my_finished) {
      const answered = t.my_answered;
      action = `<button class="btn primary big" id="play">${answered ? `繼續作答（${answered} / ${t.total}）` : "開始作答"}</button>`;
    } else if (!t.all_finished) {
      action = `<p class="hint">你已經完成了！等隊友都答完就會公布排名。</p><button class="btn" id="refresh">🔄 更新進度</button>`;
    }

    let ranking = "";
    if (t.all_finished) {
      const medals = ["🥇", "🥈", "🥉"];
      ranking = `
        <div class="podium">${t.ranking.map((r) => {
          // 同分同名次
          const rank = 1 + t.ranking.filter((x) => x.score > r.score).length;
          return `<div class="place p${rank}">${medals[rank - 1] || ""}<b>${esc(r.name)}</b><span>${fmt(r.score)} 分</span></div>`;
        }).join("")}</div>
        <h3>每題作答結果</h3>
        <div class="breakdown"><table>
          <thead><tr><th>題目</th>${t.members.map((m) => `<th>${avatarHtml(26, m.profile)}</th>`).join("")}</tr></thead>
          <tbody>${t.breakdown.map((b, i) => `<tr><td><span class="rq">${i + 1}. ${esc(b.q)} ${b.emoji ? esc(b.emoji) : ""}</span><span class="ra">正解：${esc(b.answer)}</span></td>${t.members.map((m) => {
            const v = b.scores[m.user_id];
            return `<td class="mark">${v === 1 ? "✅" : v > 0 ? "🟡" : v === 0 ? "❌" : "—"}</td>`;
          }).join("")}</tr>`).join("")}</tbody>
        </table></div>`;
    }

    $app.innerHTML = `
      <section class="panel team">
        <div class="team-top">
          <button class="link back-teams">← 我的隊伍</button>
          ${t.is_member ? `<button class="link danger" id="leave-team">${t.is_owner ? "🗑️ 刪除隊伍" : "👋 退出隊伍"}</button>` : ""}
        </div>
        <h2>👥 ${CAT_ICON[t.category]} ${esc(catName(t.category))}・${DIFF[t.difficulty].icon} ${DIFF[t.difficulty].name}</h2>
        <p class="hint">${STATUS(t)}・每人 ${t.total} 題・最多 ${t.max_members} 人</p>
        ${t.is_member && t.members.length < t.max_members ? `
        <div class="invite">
          <b>📨 邀請朋友（還可以再邀 ${t.max_members - t.members.length} 人）</b>
          <div class="invite-row"><input class="text-input" id="invite-link" readonly value="${esc(link)}">
            <button class="btn" id="copy">複製連結</button>${navigator.share ? `<button class="btn primary" id="share">分享</button>` : ""}</div>
          <small class="hint">朋友打開連結、登入 Google 後就能加入。</small>
        </div>` : ""}
        <ul class="members">${memberRows}${t.is_member ? slots : ""}</ul>
        ${action}
        ${ranking}
      </section>`;

    $app.querySelector(".back-teams").addEventListener("click", () => go("teams"));
    document.getElementById("leave-team")?.addEventListener("click", async () => {
      if (await leaveTeam(t.code, t.is_owner)) go("teams");
    });
    document.getElementById("copy")?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(link);
        toast("已複製邀請連結，貼給朋友吧！");
      } catch {
        document.getElementById("invite-link").select();
        toast("請手動複製連結");
      }
    });
    document.getElementById("share")?.addEventListener("click", () =>
      navigator.share({ title: "知識大挑戰・組隊邀請", text: `一起來挑戰「${catName(t.category)}・${DIFF[t.difficulty].name}」！`, url: link }).catch(() => {}));
    document.getElementById("join")?.addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        await api(`/api/teams/${encodeURIComponent(t.code)}/join`, {});
        toast("🎉 已加入隊伍！");
        renderTeam(t.code);
      } catch (err) {
        toast(err.message);
        renderTeam(t.code);
      }
    });
    document.getElementById("play")?.addEventListener("click", () => runTeamQuiz(t.code));
    document.getElementById("refresh")?.addEventListener("click", () => renderTeam(t.code));
    if (t.all_finished && t.ranking.find((r) => r.user_id === t.me)?.score === t.ranking[0]?.score) confetti();
  }

  /* ---------- 題庫總覽（訂閱制） ---------- */
  const bankFilters = { cat: "", difficulty: "", type: "", q: "", page: 1 };

  // 未登入：請先登入（瀏覽題庫免費，只需要登入）
  function renderLoginPrompt() {
    $app.innerHTML = `
      <section class="panel paywall">
        <svg class="mascot small" viewBox="0 0 140 112" aria-hidden="true"><use href="#mascot"/></svg>
        <h2>📚 題庫總覽</h2>
        <p>登入後就能<strong>免費</strong>瀏覽全部 <strong>${CONFIG.total}</strong> 題、篩選與搜尋；訂閱會員可看全部答案並匯出 PDF。</p>
        <a class="btn primary big" href="${loginUrl("/?view=bank")}">用 Google 帳號登入</a>
      </section>`;
  }

  // 免費會員在題庫上方看到的訂閱方案
  function subscribeBanner() {
    return `
      <div class="sub-banner">
        <div>
          <b>🔓 訂閱解鎖全部答案與解說</b>
          <p>每月 NT$${CONFIG.price_twd}，隨時可以取消。訂閱後可看全部答案，並匯出含答案與解說的 PDF 題本。</p>
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
          ${subscribed
            ? `<a class="btn primary" id="export">📄 匯出 PDF</a>`
            : `<button class="btn" id="export-locked" type="button">🔒 匯出 PDF（訂閱會員）</button>`}
        </div>
        <p class="hint" id="bank-count">載入中…</p>
        <ol class="bank-list"></ol>
        <div class="pager"></div>
        <p class="credits">圖片來源：Wikimedia Commons／Wikipedia（自由授權）。</p>
      </section>`;

    bindSubscribe();
    document.getElementById("export-locked")?.addEventListener("click", () => {
      toast("匯出 PDF 是訂閱會員功能，訂閱後可下載含全部答案與解說的題本");
      window.scrollTo({ top: 0, behavior: "smooth" });
      document.getElementById("subscribe")?.focus();
    });
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
      const link = document.getElementById("export");
      if (!link) return;
      link.href = `/api/bank/export.pdf?${new URLSearchParams(Object.entries(rest).filter(([, v]) => v))}`;
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
    applyColor(ME.profile?.color);
    renderNav();
  }

  async function boot() {
    bindNav(document.querySelector(".nav-links"));
    document.querySelector(".brand").addEventListener("click", (e) => { e.preventDefault(); go("home"); });
    setupMenu();
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
    if (params.get("team")) return renderTeam(params.get("team"));
    go(params.get("view") || "home");
  }

  boot().catch((e) => {
    $app.innerHTML = `<section class="panel"><h2>載入失敗</h2><p>${esc(e.message)}</p></section>`;
  });
})();
