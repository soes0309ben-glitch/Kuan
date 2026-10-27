"""把網頁版「隨手記帳本」轉成 App 用的 www/index.html。

用法：python3 scripts/build_www.py <網頁版 index.html 路徑>

做的事：
- Google Fonts 改用 www/fonts/ 內建字型（離線也能顯示）
- 在手機上改用 Capacitor Preferences 存資料（系統保存，不會被清掉）
- 匯出 CSV、備份改用系統分享面板；加上「從備份還原」
- 補上完整的 HTML 外框（viewport-fit=cover、safe area）
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if s.count(old) != 1:
        sys.exit(f"找不到要替換的段落（{label}），網頁版程式可能改過了，請更新這個腳本。")
    return s.replace(old, new, 1)


NATIVE_STORE = '''  const NATIVE = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  const plugin = (name) => (NATIVE ? window.Capacitor.registerPlugin(name) : null);
  async function nativeStore() {
    const Prefs = plugin("Preferences"), KEY = "ledger-v1";
    let data = { txns: {}, settings: null };
    try {
      const { value } = await Prefs.get({ key: KEY });
      if (value) data = JSON.parse(value);
    } catch (_) { /* 讀不到就從空白開始 */ }
    let onT = () => {}, onS = () => {}, chain = Promise.resolve();
    const persist = () => (chain = chain.then(() => Prefs.set({ key: KEY, value: JSON.stringify(data) })));
    const emitT = () => onT(Object.entries(data.txns).map(([id, v]) => ({ id, ...v })));
    return {
      kind: "native",
      subscribe(t, s2) { onT = t; onS = s2; emitT(); onS(data.settings); },
      async putTxn(id, v) { data.txns[id] = v; emitT(); await persist(); },
      async delTxn(id) { delete data.txns[id]; emitT(); await persist(); },
      async saveSettings(v) { data.settings = v; onS(v); await persist(); },
      async replaceAll(next) { data = next; emitT(); onS(data.settings); await persist(); },
      dump: () => JSON.parse(JSON.stringify(data)),
    };
  }
  async function cloudStore() {'''

BACKUP_FNS = '''  async function shareFile(filename, text) {
    try {
      const Fs = plugin("Filesystem"), Share = plugin("Share");
      const { uri } = await Fs.writeFile({ path: filename, data: text, directory: "CACHE", encoding: "utf8" });
      await Share.share({ title: filename, files: [uri] });
    } catch (e) { if (!/cancel/i.test(String(e?.message || e))) toast("無法匯出檔案，請再試一次"); }
  }
  async function backup() {
    const name = `財財記帳備份-${iso(todayDate())}.json`;
    const text = JSON.stringify({ app: "cat-ledger", version: 1, ...S.store.dump() });
    if (NATIVE) return shareFile(name, text);
    const dl = window.claude?.use ? await window.claude.use("downloads") : null;
    if (!dl) { toast("這個檢視方式不能下載檔案"); return; }
    try { await dl.save({ filename: name, data: new Blob([text], { type: "application/json" }) }); }
    catch (e) { if (e?.code !== "declined") toast("無法下載檔案"); }
  }
  async function restore(file) {
    try {
      const d = JSON.parse(await file.text());
      if (d.app !== "cat-ledger" || typeof d.txns !== "object") throw new Error("bad");
      if (await write(() => S.store.replaceAll({ txns: d.txns, settings: d.settings || null }), `已還原 ${Object.keys(d.txns).length} 筆紀錄`)) render();
    } catch (_) { toast("這個檔案不是財財的備份喔"); }
  }

  function bindSample() {'''

HEAD = (
    '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
    '<meta name="color-scheme" content="light dark"><meta name="format-detection" content="telephone=no">'
    '<style>html{-webkit-text-size-adjust:100%}body{margin:0;-webkit-tap-highlight-color:transparent}'
    'img{max-width:100%}[hidden]{display:none!important}:root{padding-top:env(safe-area-inset-top,0px)}</style>'
    '</head><body>\n'
)


def build(src: str) -> str:
    s = src
    s = s.replace('<link rel="preconnect" href="https://fonts.googleapis.com">\n', "")
    s = s.replace('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n', "")
    s = s.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    s = replace_once(
        s,
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Huninn&family=Fredoka:wght@500;600;700&display=swap">',
        '<link rel="stylesheet" href="fonts/fonts.css">',
        "字型",
    )
    s = replace_once(s, "  async function cloudStore() {", NATIVE_STORE, "手機儲存")
    s = replace_once(
        s,
        "      async saveSettings(v) { data.settings = v; persist(); onS(v); },\n    };\n  }",
        "      async saveSettings(v) { data.settings = v; persist(); onS(v); },\n"
        "      async replaceAll(next) { data = next; persist(); emitT(); onS(data.settings); },\n"
        "      dump: () => JSON.parse(JSON.stringify(data)),\n    };\n  }",
        "本機備份",
    )
    s = replace_once(
        s,
        "  const fallback = setTimeout(() => { if (!S.store) attach(localStore()); }, 11000);\n  cloudStore().then(",
        "  if (NATIVE) { nativeStore().then(attach); } else {\n"
        "  const fallback = setTimeout(() => { if (!S.store) attach(localStore()); }, 11000);\n  cloudStore().then(",
        "啟動",
    )
    s = replace_once(
        s,
        'attach(localStore()); } });\n  addEventListener("scroll", hideTip, { passive: true });',
        'attach(localStore()); } });\n  }\n  addEventListener("scroll", hideTip, { passive: true });',
        "啟動結尾",
    )
    s = replace_once(
        s,
        'S.store.kind === "cloud" ? "☁️ 已同步・只有你看得到" : "📱 只存在這台裝置";',
        'S.store.kind === "cloud" ? "☁️ 已同步・只有你看得到" : S.store.kind === "native" ? "📱 存在這支手機裡" : "📱 只存在這台裝置";',
        "狀態標籤",
    )
    s = replace_once(
        s,
        '    const dl = window.claude?.use ? await window.claude.use("downloads") : null;\n    if (!dl) { toast("這個檢視方式不能下載檔案，請在 Claude 裡開啟這個頁面"); return; }',
        '    if (NATIVE) return shareFile(filename, csv);\n'
        '    const dl = window.claude?.use ? await window.claude.use("downloads") : null;\n'
        '    if (!dl) { toast("這個檢視方式不能下載檔案"); return; }',
        "匯出",
    )
    s = replace_once(s, "  function bindSample() {", BACKUP_FNS, "備份函式")
    s = replace_once(
        s,
        '          ${sampleCount ? `<span id="clear-box">',
        '          ${S.store?.dump ? `<button type="button" class="btn" id="backup">備份全部資料</button>'
        '<label class="btn" for="restore-file">從備份還原</label>'
        '<input type="file" id="restore-file" accept="application/json,.json" hidden>` : ""}\n'
        '          ${sampleCount ? `<span id="clear-box">',
        "備份按鈕",
    )
    s = replace_once(
        s,
        '        <p class="muted" style="margin:0;font-size:13px">${S.store?.kind === "cloud" ?',
        '        <p class="muted" style="margin:0;font-size:13px">${S.store?.kind === "native" ? '
        '"你的紀錄只存在這支手機裡，不會上傳到任何地方。換手機或刪除 App 前，記得先「備份全部資料」，存到雲端硬碟或傳給自己。" : '
        'S.store?.kind === "cloud" ?',
        "儲存說明",
    )
    s = replace_once(
        s,
        '    $main.querySelector("#exp-month").addEventListener("click",',
        '    $main.querySelector("#backup")?.addEventListener("click", backup);\n'
        '    $main.querySelector("#restore-file")?.addEventListener("change", (e) => { const f = e.target.files[0]; if (f) restore(f); e.target.value = ""; });\n'
        '    $main.querySelector("#exp-month").addEventListener("click",',
        "備份事件",
    )
    return HEAD + s + "\n</body></html>\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = ROOT / "www" / "index.html"
    out.write_text(build(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8")
    print(f"已產生 {out}")
