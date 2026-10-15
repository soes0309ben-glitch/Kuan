/* LINE 記帳本 —— 網頁版前端（資料與計算都在伺服器，這裡只負責畫面） */
(() => {
  "use strict";

  const $app = document.getElementById("app");
  const $tip = document.getElementById("tooltip");
  const state = { config: null, me: null, month: null, view: "overview", categories: [], filters: { kind: "", q: "", category_id: "" } };

  /* ---------- 小工具 ---------- */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => "$" + Math.round(n).toLocaleString("zh-TW");
  const compact = (n) => (n >= 10000 ? (n / 10000).toLocaleString("zh-TW", { maximumFractionDigits: 1 }) + "萬" : n >= 1000 ? (n / 1000).toLocaleString("zh-TW", { maximumFractionDigits: 1 }) + "千" : String(n));
  const monthLabel = (key) => `${key.slice(0, 4)} 年 ${Number(key.slice(5))} 月`;
  const shiftMonth = (key, d) => { const [y, m] = key.split("-").map(Number); const i = y * 12 + m - 1 + d; return `${Math.floor(i / 12)}-${String(i % 12 + 1).padStart(2, "0")}`; };
  const md = (iso) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8))}`;
  const WEEK = "日一二三四五六";
  const weekday = (iso) => WEEK[new Date(iso + "T00:00:00").getDay()];

  async function api(path, { method = "GET", body } = {}) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("、") : data.detail;
      throw new Error(detail || `發生錯誤（${res.status}）`);
    }
    return data;
  }

  let toastTimer;
  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
  }

  /* ---------- 提示框（圖表 hover） ---------- */
  function showTip(evt, title, rows) {
    $tip.innerHTML = `<div class="t">${esc(title)}</div>` + rows.map((r) =>
      `<div class="r"><span>${r.color ? `<i style="background:${r.color}"></i>` : ""}${esc(r.label)}</span><b class="tabnum">${esc(r.value)}</b></div>`).join("");
    $tip.hidden = false;
    const pad = 12, w = $tip.offsetWidth, h = $tip.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY - h - pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y < 8) y = evt.clientY + pad;
    $tip.style.left = `${Math.max(8, x)}px`;
    $tip.style.top = `${y}px`;
  }
  const hideTip = () => { $tip.hidden = true; };

  function niceMax(v) {
    if (v <= 0) return 100;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  /* 直條圖：series = [{key,label,color}]，rows = [{label, title, values:{key:n}}]
     以容器實際寬度繪製（不靠 viewBox 縮放，手機上字才不會變小），容器寬度改變時重畫 */
  function columnChart({ rows, series, height = 180, labelEvery = 1 }) {
    const el = document.createElement("div");
    el.className = "chart";
    let drawnWidth = 0;

    function draw(W) {
      drawnWidth = W;
      const H = height, L = 40, R = 8, T = 8, B = 22;
      const max = niceMax(Math.max(0, ...rows.flatMap((r) => series.map((s) => r.values[s.key] || 0))));
      const plotW = W - L - R, plotH = H - T - B;
      const band = plotW / rows.length;
      const gap = series.length > 1 ? 2 : 0;
      const barW = Math.max(2, Math.min(28, (band * 0.7 - gap * (series.length - 1)) / series.length));
      const y = (v) => T + plotH - (v / max) * plotH;
      // 窄螢幕自動拉大標籤間距，避免文字重疊
      const every = Math.max(labelEvery, Math.ceil(28 / band));
      let svg = `<g class="grid">`;
      for (let i = 1; i <= 4; i++) {
        const v = (max / 4) * i;
        svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${compact(v)}</text>`;
      }
      svg += `</g>`;
      rows.forEach((r, i) => {
        const x0 = L + band * i;
        const groupW = barW * series.length + gap * (series.length - 1);
        svg += `<rect class="hover-band" data-i="${i}" x="${x0}" y="${T}" width="${band}" height="${plotH}" opacity="0"/>`;
        series.forEach((s, j) => {
          const v = r.values[s.key] || 0;
          if (!v) return;
          const bx = x0 + (band - groupW) / 2 + j * (barW + gap);
          const top = y(v), h = T + plotH - top;
          const rad = Math.min(4, barW / 2, h);
          // 只有頂端圓角，底部貼齊基準線
          svg += `<path class="mark" fill="${s.color}" d="M${bx},${T + plotH} V${top + rad} Q${bx},${top} ${bx + rad},${top} H${bx + barW - rad} Q${bx + barW},${top} ${bx + barW},${top + rad} V${T + plotH} Z"/>`;
        });
        if (i % every === 0) svg += `<text x="${x0 + band / 2}" y="${H - 6}" text-anchor="middle">${esc(r.label)}</text>`;
        svg += `<rect class="hit" data-i="${i}" x="${x0}" y="${T}" width="${band}" height="${plotH + B}"/>`;
      });
      svg += `<line class="baseline" x1="${L}" x2="${W - R}" y1="${T + plotH}" y2="${T + plotH}"/>`;
      el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="直條圖，可切換成表格查看數字">${svg}</svg>`;
      el.querySelectorAll(".hit").forEach((hit) => {
        const i = Number(hit.dataset.i);
        const bandEl = el.querySelector(`.hover-band[data-i="${i}"]`);
        const move = (e) => {
          bandEl.setAttribute("opacity", "1");
          showTip(e, rows[i].title || rows[i].label, series.map((s) => ({ label: s.label, value: money(rows[i].values[s.key] || 0), color: s.color })));
        };
        hit.addEventListener("pointermove", move);
        hit.addEventListener("pointerdown", move);
        hit.addEventListener("pointerleave", () => { bandEl.setAttribute("opacity", "0"); hideTip(); });
      });
    }

    new ResizeObserver(() => {
      const w = Math.floor(el.clientWidth);
      if (w > 0 && w !== drawnWidth) draw(w);
    }).observe(el);
    return el;
  }

  function dataTable(headers, rows) {
    return `<table class="data"><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  /* 圖表卡片：右上角可切換成表格 */
  function chartCard(title, sub, chartEl, tableHtml, legendHtml = "") {
    const card = document.createElement("section");
    card.className = "card";
    card.innerHTML = `<h2>${esc(title)} <small>${esc(sub)}</small><span class="spacer"></span><button class="btn small table-toggle" aria-pressed="false">表格</button></h2>${legendHtml}<div class="body"></div>`;
    const body = card.querySelector(".body");
    body.append(chartEl);
    const btn = card.querySelector(".table-toggle");
    btn.addEventListener("click", () => {
      const on = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "圖表" : "表格";
      body.innerHTML = "";
      if (on) body.innerHTML = tableHtml; else body.append(chartEl);
    });
    return card;
  }

  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function statusOf(ratio) {
    if (ratio >= 1) return { color: "var(--critical)", label: "🔴 超支" };
    if (ratio >= 0.8) return { color: "var(--warning)", label: "🟡 注意" };
    return { color: "var(--good)", label: "🟢 正常" };
  }

  function budgetRows(budgets) {
    return budgets.map((b) => {
      const st = statusOf(b.ratio);
      const remain = b.remaining >= 0 ? `剩 ${money(b.remaining)}` : `超支 ${money(-b.remaining)}`;
      return `<div class="budget">
        <div class="top"><span class="name">${esc(b.icon)} ${esc(b.name)}</span><span class="status">${st.label} ${Math.round(b.ratio * 100)}%</span></div>
        <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="${b.budget}" aria-valuenow="${b.spent}" aria-label="${esc(b.name)}"><span style="width:${Math.min(100, b.ratio * 100)}%;background:${st.color}"></span></div>
        <div class="sub"><span class="tabnum">${money(b.spent)} / ${money(b.budget)}</span><span>${remain}</span></div>
      </div>`;
    }).join("");
  }

  /* ---------- 外框 ---------- */
  const TABS = [
    { id: "overview", ico: "📊", label: "總覽" },
    { id: "list", ico: "🧾", label: "明細" },
    { id: "add", ico: "＋", label: "記一筆" },
    { id: "budget", ico: "💰", label: "預算" },
    { id: "settings", ico: "⚙️", label: "設定" },
  ];

  function shell(title, { monthPicker = true } = {}) {
    $app.innerHTML = `
      <header class="topbar">
        <h1>${esc(title)}</h1>
        ${monthPicker ? `<div class="month-picker"><button class="btn icon" data-m="-1" aria-label="上個月">‹</button><span>${monthLabel(state.month)}</span><button class="btn icon" data-m="1" aria-label="下個月">›</button></div>` : ""}
      </header>
      <main class="wrap" id="main"></main>
      <nav class="tabbar">${TABS.map((t) => `<button data-tab="${t.id}" class="${t.id === "add" ? "add" : ""}" ${t.id === state.view ? 'aria-current="page"' : ""}><span class="ico">${t.ico}</span>${t.label}</button>`).join("")}</nav>`;
    $app.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => { state.month = shiftMonth(state.month, Number(b.dataset.m)); route(); }));
    $app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.tab === "add") return openTxnDialog();
      state.view = b.dataset.tab;
      history.replaceState(null, "", "#" + state.view);
      route();
    }));
    return document.getElementById("main");
  }

  /* ---------- 總覽 ---------- */
  async function renderOverview() {
    const main = shell("📒 " + (state.config.app_name || "記帳本"));
    main.innerHTML = `<div class="empty">載入中…</div>`;
    const [s, trend] = await Promise.all([api(`/api/summary?month=${state.month}`), api("/api/trend?months=6")]);
    const diff = s.expense - s.previous.expense;
    const diffText = s.previous.expense ? `比上月${diff >= 0 ? "多" : "少"} ${money(Math.abs(diff))}` : "上月無紀錄";
    main.innerHTML = `
      <section class="card">
        <div class="stats">
          <div class="stat"><div class="label">支出</div><div class="value expense">${money(s.expense)}</div><div class="delta">${diffText}</div></div>
          <div class="stat"><div class="label">收入</div><div class="value income">${money(s.income)}</div><div class="delta">${s.count} 筆紀錄</div></div>
          <div class="stat"><div class="label">結餘</div><div class="value">${s.balance < 0 ? "-" : ""}${money(Math.abs(s.balance))}</div><div class="delta">${md(s.start)} – ${md(s.end)}</div></div>
        </div>
        <div class="hint-row"><span>日均支出 <b class="tabnum">${money(s.daily_average)}</b></span>${s.projected_expense != null ? `<span>照目前速度，本期預估支出 <b class="tabnum">${money(s.projected_expense)}</b></span>` : ""}</div>
      </section>
      <div id="budget-slot"></div>
      <div class="grid-2" id="charts"></div>
      <div id="trend-slot"></div>`;

    if (s.budgets.length) {
      main.querySelector("#budget-slot").outerHTML = `<section class="card"><h2>💰 預算<span class="spacer"></span><button class="btn small" data-go="budget">管理</button></h2>${budgetRows(s.budgets)}</section>`;
    } else {
      main.querySelector("#budget-slot").outerHTML = `<section class="card"><h2>💰 預算</h2><p class="ink2" style="margin:0">還沒設定預算。設定後超過 80% 與超支時，LINE 會在記帳當下提醒你。 <button class="btn small" data-go="budget">設定預算</button></p></section>`;
    }
    main.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.go; route(); }));

    const charts = main.querySelector("#charts");
    // 支出分類排行
    const exp = s.by_category.filter((c) => c.kind === "expense");
    const rank = document.createElement("section");
    rank.className = "card";
    rank.innerHTML = `<h2>支出分類 <small>點分類看明細</small></h2>` + (exp.length ? `<div class="rank">${exp.map((c) => {
      const pct = s.expense ? c.amount / s.expense : 0;
      return `<div class="rank-row" data-cat="${c.id}" tabindex="0"><span class="name">${esc(c.icon)} ${esc(c.name)} <span class="muted">· ${c.count} 筆</span></span><span class="amt">${money(c.amount)}<small>${Math.round(pct * 100)}%</small></span><div class="track"><span style="width:${pct * 100}%"></span></div></div>`;
    }).join("")}</div>` : `<div class="empty">這個月還沒有支出 🎉</div>`);
    rank.querySelectorAll("[data-cat]").forEach((r) => {
      const go = () => { state.filters = { kind: "", q: "", category_id: r.dataset.cat }; state.view = "list"; route(); };
      r.addEventListener("click", go);
      r.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
    charts.append(rank);

    // 每日支出
    const dailyRows = s.daily.map((d) => ({ label: String(Number(d.date.slice(8))), title: `${md(d.date)}（${weekday(d.date)}）`, values: { expense: d.expense } }));
    const daily = columnChart({ rows: dailyRows, series: [{ key: "expense", label: "支出", color: cssVar("--series-1") }], labelEvery: 5, height: 200 });
    charts.append(chartCard("每日支出", "", daily, dataTable(["日期", "支出", "收入"], s.daily.filter((d) => d.expense || d.income).map((d) => [md(d.date), money(d.expense), money(d.income)]))));

    // 近 6 個月收支
    const series = [{ key: "expense", label: "支出", color: cssVar("--series-1") }, { key: "income", label: "收入", color: cssVar("--series-2") }];
    const trendRows = trend.months.map((m) => ({ label: `${Number(m.month.slice(5))}月`, title: monthLabel(m.month), values: m }));
    const legend = `<div class="legend">${series.map((x) => `<span><i style="background:${x.color}"></i>${x.label}</span>`).join("")}</div>`;
    main.querySelector("#trend-slot").replaceWith(chartCard("近 6 個月", "收入與支出", columnChart({ rows: trendRows, series, height: 200 }),
      dataTable(["月份", "支出", "收入", "結餘"], trend.months.map((m) => [monthLabel(m.month), money(m.expense), money(m.income), money(m.income - m.expense)])), legend));
  }

  /* ---------- 明細 ---------- */
  async function renderList() {
    const main = shell("🧾 明細");
    const f = state.filters;
    const catOptions = state.categories.map((c) => `<option value="${c.id}" ${String(c.id) === String(f.category_id) ? "selected" : ""}>${esc(c.icon)} ${esc(c.name)}</option>`).join("");
    main.innerHTML = `
      <section class="card">
        <div class="filters">
          <div class="seg" role="group" aria-label="收支">
            ${[["", "全部"], ["expense", "支出"], ["income", "收入"]].map(([k, l]) => `<button data-kind="${k}" aria-pressed="${f.kind === k}">${l}</button>`).join("")}
          </div>
          <select id="f-cat" aria-label="分類"><option value="">所有分類</option>${catOptions}</select>
          <input type="search" id="f-q" placeholder="搜尋備註或分類" value="${esc(f.q)}">
        </div>
        <div id="list"><div class="empty">載入中…</div></div>
      </section>`;
    main.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => { f.kind = b.dataset.kind; renderList(); }));
    main.querySelector("#f-cat").addEventListener("change", (e) => { f.category_id = e.target.value; renderList(); });
    let t;
    main.querySelector("#f-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value; loadList(); }, 300); });
    await loadList();
  }

  async function loadList() {
    const f = state.filters;
    const qs = new URLSearchParams({ month: state.month });
    if (f.kind) qs.set("kind", f.kind);
    if (f.category_id) qs.set("category_id", f.category_id);
    if (f.q) qs.set("q", f.q);
    const data = await api(`/api/transactions?${qs}`);
    const box = document.getElementById("list");
    if (!box) return;
    if (!data.transactions.length) {
      box.innerHTML = `<div class="empty">沒有符合的紀錄。<br>在 LINE 傳「午餐 120」，或按下方「＋」新增。</div>`;
      return;
    }
    const groups = new Map();
    for (const t of data.transactions) (groups.get(t.date) || groups.set(t.date, []).get(t.date)).push(t);
    box.innerHTML = [...groups].map(([date, items]) => {
      const out = items.filter((x) => x.kind === "expense").reduce((a, x) => a + x.amount, 0);
      const inc = items.filter((x) => x.kind === "income").reduce((a, x) => a + x.amount, 0);
      return `<div class="day-group"><h3><span>${md(date)}（${weekday(date)}）</span><span class="tabnum">${out ? `支出 ${money(out)}` : ""}${out && inc ? "・" : ""}${inc ? `收入 ${money(inc)}` : ""}</span></h3>
        ${items.map((x) => `<div class="txn" data-id="${x.id}" tabindex="0">
          <span class="emo">${esc(x.icon)}</span>
          <span class="main"><div class="n">${esc(x.note || x.category)}</div><div class="c">${esc(x.category)}${x.source === "line" ? " · 來自 LINE" : ""}</div></span>
          <span class="a ${x.kind}">${x.kind === "expense" ? "-" : "+"}${money(x.amount)}</span>
        </div>`).join("")}</div>`;
    }).join("");
    const byId = new Map(data.transactions.map((x) => [String(x.id), x]));
    box.querySelectorAll(".txn").forEach((el) => {
      const open = () => openTxnDialog(byId.get(el.dataset.id));
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  }

  /* ---------- 新增 / 編輯 ---------- */
  function openTxnDialog(txn = null) {
    const today = state.me.today;
    let kind = txn?.kind || "expense";
    let categoryId = txn?.category_id || null;
    const dlg = document.createElement("dialog");
    dlg.innerHTML = `<form method="dialog">
      <h3>${txn ? "編輯紀錄" : "記一筆"}</h3>
      <div class="seg" role="group" aria-label="收支">
        <button type="button" data-k="expense">支出</button><button type="button" data-k="income">收入</button>
      </div>
      <label>金額<input class="amount-input tabnum" name="amount" type="number" inputmode="numeric" min="1" step="1" required value="${txn?.amount ?? ""}" placeholder="0"></label>
      <label>分類<div class="chips" id="chips"></div></label>
      <label>備註<input type="text" name="note" maxlength="200" value="${esc(txn?.note || "")}" placeholder="例如：午餐、計程車"></label>
      <label>日期<input type="date" name="date" required value="${txn?.date || today}" max="${today}"></label>
      <div class="row">
        ${txn ? `<button type="button" class="btn danger" id="del">刪除</button>` : ""}
        <span class="spacer"></span>
        <button type="button" class="btn" value="cancel" id="cancel">取消</button>
        <button type="submit" class="btn primary">儲存</button>
      </div>
    </form>`;
    document.body.append(dlg);
    const chips = dlg.querySelector("#chips");
    const paint = () => {
      dlg.querySelectorAll("[data-k]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === kind)));
      const cats = state.categories.filter((c) => c.kind === kind);
      if (!cats.some((c) => c.id === categoryId)) categoryId = cats[0]?.id ?? null;
      chips.innerHTML = cats.map((c) => `<button type="button" data-c="${c.id}" aria-pressed="${c.id === categoryId}">${esc(c.icon)} ${esc(c.name)}</button>`).join("");
      chips.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => { categoryId = Number(b.dataset.c); paint(); }));
    };
    dlg.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => { kind = b.dataset.k; paint(); }));
    paint();
    dlg.querySelector("#cancel").addEventListener("click", () => dlg.close());
    dlg.addEventListener("close", () => dlg.remove());
    dlg.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = { kind, amount: Number(fd.get("amount")), category_id: categoryId, note: fd.get("note"), date: fd.get("date") };
      try {
        await api(txn ? `/api/transactions/${txn.id}` : "/api/transactions", { method: txn ? "PUT" : "POST", body });
        dlg.close();
        toast(txn ? "已更新" : "已記錄 ✅");
        route();
      } catch (err) { toast(err.message); }
    });
    dlg.querySelector("#del")?.addEventListener("click", async () => {
      if (!confirm("確定刪除這筆紀錄？")) return;
      await api(`/api/transactions/${txn.id}`, { method: "DELETE" });
      dlg.close();
      toast("已刪除");
      route();
    });
    dlg.showModal();
    dlg.querySelector("[name=amount]").focus();
  }

  /* ---------- 預算 ---------- */
  async function renderBudget() {
    const main = shell("💰 預算");
    const { budgets } = await api(`/api/budgets?month=${state.month}`);
    const byCat = new Map(budgets.map((b) => [b.category_id, b]));
    const total = byCat.get(null);
    main.innerHTML = `
      ${budgets.length ? `<section class="card"><h2>本期使用狀況</h2>${budgetRows(budgets)}</section>` : ""}
      <section class="card">
        <h2>每月預算 <small>留空或 0 代表不設定</small></h2>
        <form id="bf" style="display:grid;gap:10px">
          <div class="cat-row"><span class="emo">💰</span><span class="info"><b>總預算</b><div class="kw">所有支出合計</div></span>
            <input type="number" min="0" step="100" inputmode="numeric" data-cat="" value="${total ? total.budget : ""}" placeholder="例如 20000" style="width:130px"></div>
          ${state.categories.filter((c) => c.kind === "expense").map((c) => {
            const b = byCat.get(c.id);
            return `<div class="cat-row"><span class="emo">${esc(c.icon)}</span><span class="info">${esc(c.name)}${b ? `<div class="kw">本期已花 ${money(b.spent)}</div>` : ""}</span>
              <input type="number" min="0" step="100" inputmode="numeric" data-cat="${c.id}" value="${b ? b.budget : ""}" placeholder="—" style="width:130px"></div>`;
          }).join("")}
          <div class="row" style="display:flex;justify-content:flex-end"><button class="btn primary" type="submit">儲存預算</button></div>
        </form>
        <p class="muted" style="font-size:13px;margin:8px 0 0">也可以在 LINE 傳「預算 20000」或「預算 餐飲 6000」。</p>
      </section>`;
    main.querySelector("#bf").addEventListener("submit", async (e) => {
      e.preventDefault();
      const inputs = [...e.target.querySelectorAll("input[data-cat]")];
      try {
        for (const inp of inputs) {
          const cid = inp.dataset.cat ? Number(inp.dataset.cat) : null;
          const before = byCat.get(cid)?.budget || 0;
          const amount = Number(inp.value || 0);
          if (amount !== before) await api("/api/budgets", { method: "POST", body: { category_id: cid, amount } });
        }
        toast("預算已儲存");
        renderBudget();
      } catch (err) { toast(err.message); }
    });
  }

  /* ---------- 設定 ---------- */
  async function renderSettings() {
    const main = shell("⚙️ 設定", { monthPicker: false });
    const me = state.me;
    const hours = Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === me.reminder_hour ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("");
    const days = Array.from({ length: 28 }, (_, i) => `<option value="${i + 1}" ${i + 1 === me.month_start_day ? "selected" : ""}>每月 ${i + 1} 日</option>`).join("");
    const friend = state.config.add_friend_url;
    main.innerHTML = `
      <section class="card">
        <h2>帳號</h2>
        <div class="cat-row">
          ${me.picture ? `<img src="${esc(me.picture)}" alt="" width="40" height="40" style="border-radius:50%">` : `<span class="emo">🙂</span>`}
          <span class="info"><b>${esc(me.name || "LINE 使用者")}</b><div class="kw">${me.bot_friend ? "✅ 已加入 LINE 官方帳號，可直接在聊天室記帳" : "尚未加入 LINE 官方帳號好友"}</div></span>
          ${!me.bot_friend && friend ? `<a class="btn primary small" href="${esc(friend)}" target="_blank" rel="noopener">加好友</a>` : ""}
        </div>
      </section>
      <section class="card">
        <h2>LINE 提醒</h2>
        <div class="cat-row"><span class="info">每日記帳提醒<div class="kw">當天還沒記帳時，在指定時間傳 LINE 提醒；每月第一天另外推上月月報</div></span>
          <input type="checkbox" id="rem" ${me.reminder_enabled ? "checked" : ""} ${me.bot_friend ? "" : "disabled"} aria-label="開啟每日提醒"></div>
        <div class="cat-row"><span class="info">提醒時間</span><select id="rem-h">${hours}</select></div>
        <div class="cat-row"><span class="info">月結日<div class="kw">配合發薪日，例如 25 號領薪就設 25 日，統計與預算都從那天起算</div></span><select id="msd">${days}</select></div>
      </section>
      <section class="card">
        <h2>分類<span class="spacer"></span><button class="btn small" id="add-cat">＋ 新增分類</button></h2>
        <div class="seg" role="group" aria-label="分類類型" id="cat-kind">
          <button data-k="expense" aria-pressed="true">支出</button><button data-k="income" aria-pressed="false">收入</button>
        </div>
        <div id="cats"></div>
        <p class="muted" style="font-size:13px;margin:8px 0 0">LINE 訊息含有關鍵字時會自動歸類；比對時以最長的關鍵字為準。</p>
      </section>
      <section class="card">
        <h2>匯出</h2>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <a class="btn" href="/api/export.csv?month=${state.month}">⬇️ 匯出 ${monthLabel(state.month)} CSV</a>
          <a class="btn" href="/api/export.csv">⬇️ 匯出全部 CSV</a>
        </div>
      </section>
      <section class="card"><button class="btn danger" id="logout">登出</button></section>`;

    const save = async (body) => {
      try { await api("/api/me/settings", { method: "POST", body }); Object.assign(state.me, body); toast("已儲存"); } catch (err) { toast(err.message); }
    };
    main.querySelector("#rem").addEventListener("change", (e) => save({ reminder_enabled: e.target.checked }));
    main.querySelector("#rem-h").addEventListener("change", (e) => save({ reminder_hour: Number(e.target.value) }));
    main.querySelector("#msd").addEventListener("change", async (e) => {
      await save({ month_start_day: Number(e.target.value) });
      await loadMe();
      state.month = state.me.current_month;
    });
    main.querySelector("#logout").addEventListener("click", async () => { await api("/auth/logout", { method: "POST", body: {} }); location.href = "/"; });

    let catKind = "expense";
    const paintCats = () => {
      main.querySelectorAll("#cat-kind [data-k]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === catKind)));
      const cats = state.categories.filter((c) => c.kind === catKind);
      const box = main.querySelector("#cats");
      box.innerHTML = cats.map((c, i) => `<div class="cat-row">
        <span class="emo">${esc(c.icon)}</span>
        <span class="info"><b>${esc(c.name)}</b><div class="kw">${c.keywords.length ? esc(c.keywords.join("、")) : "（沒有關鍵字）"}</div></span>
        <button class="btn small icon" data-up="${i}" aria-label="上移" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="btn small" data-edit="${c.id}">編輯</button>
      </div>`).join("");
      box.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => openCategoryDialog(state.categories.find((c) => c.id === Number(b.dataset.edit)))));
      box.querySelectorAll("[data-up]").forEach((b) => b.addEventListener("click", async () => {
        const i = Number(b.dataset.up);
        const ids = cats.map((c) => c.id);
        [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
        await api("/api/categories/reorder", { method: "POST", body: { ids } });
        await loadCategories();
        paintCats();
      }));
    };
    main.querySelectorAll("#cat-kind [data-k]").forEach((b) => b.addEventListener("click", () => { catKind = b.dataset.k; paintCats(); }));
    main.querySelector("#add-cat").addEventListener("click", () => openCategoryDialog({ kind: catKind }));
    paintCats();
  }

  function openCategoryDialog(cat) {
    const editing = Boolean(cat.id);
    const dlg = document.createElement("dialog");
    dlg.innerHTML = `<form method="dialog">
      <h3>${editing ? "編輯分類" : `新增${cat.kind === "income" ? "收入" : "支出"}分類`}</h3>
      <label>圖示（emoji）<input type="text" name="icon" maxlength="8" value="${esc(cat.icon || "")}" placeholder="🍜"></label>
      <label>名稱<input type="text" name="name" maxlength="30" required value="${esc(cat.name || "")}"></label>
      <label>關鍵字（用逗號或空白分隔）<input type="text" name="keywords" value="${esc((cat.keywords || []).join(", "))}" placeholder="例如：健身房, 蛋白粉"></label>
      <div class="row">
        ${editing ? `<button type="button" class="btn danger" id="del">刪除</button>` : ""}
        <span class="spacer"></span>
        <button type="button" class="btn" id="cancel">取消</button>
        <button type="submit" class="btn primary">儲存</button>
      </div>
    </form>`;
    document.body.append(dlg);
    dlg.querySelector("#cancel").addEventListener("click", () => dlg.close());
    dlg.addEventListener("close", () => dlg.remove());
    dlg.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const body = { kind: cat.kind, name: fd.get("name"), icon: fd.get("icon"), keywords: String(fd.get("keywords")).split(/[,，、\s]+/).filter(Boolean) };
      try {
        await api(editing ? `/api/categories/${cat.id}` : "/api/categories", { method: editing ? "PUT" : "POST", body });
        dlg.close();
        await loadCategories();
        toast("分類已儲存");
        renderSettings();
      } catch (err) { toast(err.message); }
    });
    dlg.querySelector("#del")?.addEventListener("click", async () => {
      if (!confirm(`刪除「${cat.name}」？已記的紀錄會保留，但之後不會再自動歸到這個分類。`)) return;
      try {
        await api(`/api/categories/${cat.id}`, { method: "DELETE" });
        dlg.close();
        await loadCategories();
        renderSettings();
      } catch (err) { toast(err.message); }
    });
    dlg.showModal();
  }

  /* ---------- 登入頁 ---------- */
  function renderLogin() {
    const c = state.config;
    const params = new URLSearchParams(location.search);
    const notice = params.get("login") === "expired" ? `<p class="expense">登入連結已過期或已使用過，請在 LINE 再傳一次「網頁」。</p>` : "";
    $app.innerHTML = `<div class="hero">
      <div class="logo">📒</div>
      <h1>${esc(c.app_name)}</h1>
      <p>在 LINE 傳一句話就記好帳，網頁看圖表、管預算。</p>
      ${notice}
      <div class="bubble-demo">
        <span class="me">午餐 120</span>
        <span class="bot">✅ 已記錄 🍱 餐飲 -$120<br><small>本期支出 $8,450</small></span>
        <span class="me">本月</span>
        <span class="bot">📊 支出 $8,450・收入 $45,000</span>
      </div>
      ${c.line_login ? `<a class="line-btn" href="/auth/line/login">使用 LINE 登入</a>` : ""}
      ${c.add_friend_url ? `<a class="btn" style="justify-self:center" href="${esc(c.add_friend_url)}" target="_blank" rel="noopener">➕ 加入 LINE 官方帳號</a>` : ""}
      <p class="muted" style="font-size:13px">已經在用 LINE 記帳？在聊天室傳「網頁」，點連結就能直接登入。</p>
      ${c.dev_login ? `<button class="btn" id="dev" style="justify-self:center">🛠 開發者登入</button>` : ""}
    </div>`;
    document.getElementById("dev")?.addEventListener("click", async () => { await api("/auth/dev-login", { method: "POST", body: {} }); location.href = "/"; });
  }

  /* ---------- 路由 ---------- */
  async function loadMe() { state.me = (await api("/api/me")).user; }
  async function loadCategories() { state.categories = (await api("/api/categories")).categories; }

  async function route() {
    hideTip();
    try {
      if (state.view === "list") await renderList();
      else if (state.view === "budget") await renderBudget();
      else if (state.view === "settings") await renderSettings();
      else await renderOverview();
    } catch (err) {
      const main = document.getElementById("main") || $app;
      main.innerHTML = `<div class="card empty">😵 ${esc(err.message)}<br><button class="btn" onclick="location.reload()">重新整理</button></div>`;
    }
  }

  async function boot() {
    state.config = await api("/api/config");
    await loadMe();
    if (!state.me) return renderLogin();
    if (location.search) history.replaceState(null, "", "/" + location.hash);
    state.month = state.me.current_month;
    const hash = location.hash.slice(1);
    if (["overview", "list", "budget", "settings"].includes(hash)) state.view = hash;
    await loadCategories();
    route();
  }

  window.addEventListener("scroll", hideTip, { passive: true });
  boot().catch((err) => { $app.innerHTML = `<div class="hero"><p>😵 ${esc(err.message)}</p></div>`; });
})();
