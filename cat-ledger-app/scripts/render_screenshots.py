"""產生商店截圖（App Store 6.9 吋 1320x2868、Google Play 1080x1920）與 Google Play 主打圖片（1024x500）。

用法：python3 scripts/render_screenshots.py   （需要 playwright 與 Chromium）
"""
import os
import pathlib
import re

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "store" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
APP = (ROOT / "www" / "index.html").as_uri()
CHROME = os.environ.get("CHROMIUM") or None  # 不設定就用 playwright 自己安裝的 Chromium

# 每張截圖上方的標語（白色大字放在截圖上方的色塊）
SHOTS = [
    ("overview", "說一句「午餐 120」就記好", None),
    ("list", "每一筆都清清楚楚", None),
    ("budgets", "設定預算，財財幫你盯著", None),
    ("quick", "日期、收入、分類都聽得懂", "昨天 計程車250；+3000 獎金"),
]
# 模擬手機環境（資料存在記憶體），畫面才會顯示「存在這支手機裡」
MOCK = """
const mem = {};
window.Capacitor = { isNativePlatform: () => true, registerPlugin: (n) => ({
  Preferences: { get: async ({ key }) => ({ value: mem[key] || null }), set: async ({ key, value }) => { mem[key] = value; } },
}[n]) };
"""
SIZES = {"appstore-6.9": (440, 956, 3), "googleplay": (360, 640, 3)}

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME)
    for label, (w, h, scale) in SIZES.items():
        app_h = int(h * 0.80)
        ctx = b.new_context(viewport={"width": w, "height": app_h}, device_scale_factor=scale)
        ctx.add_init_script(MOCK)
        pg = ctx.new_page()
        pg.goto(APP); pg.wait_for_timeout(1500)
        pg.add_style_tag(content=".tag{display:none!important}")
        if pg.query_selector("#load-sample"):
            pg.click("#load-sample"); pg.wait_for_timeout(1500)
        # 截圖用的預算設得寬鬆一點，讓財財開開心心
        pg.click("#tabs button[data-view=budgets]"); pg.wait_for_timeout(400)
        pg.fill("#b-total", "50000"); pg.fill("#b-shopping", "20000"); pg.fill("#b-food", "6000")
        pg.click("#bf button[type=submit]"); pg.wait_for_timeout(3200)
        for i, (view, title, typed) in enumerate(SHOTS, 1):
            pg.click(f"#tabs button[data-view={'overview' if view == 'quick' else view}]"); pg.wait_for_timeout(500)
            pg.fill("#quick-input", typed or ""); pg.dispatch_event("#quick-input", "input"); pg.wait_for_timeout(300)
            shot = pg.screenshot()
            frame = ctx.new_page()
            frame.set_viewport_size({"width": w, "height": h})
            import base64
            img = base64.b64encode(shot).decode()
            frame.set_content(f"""<html><head><link rel="stylesheet" href="{(ROOT / 'www' / 'fonts' / 'fonts.css').as_uri()}"></head>
              <body style="margin:0;width:{w}px;height:{h}px;background:#ec5f8c;font-family:Huninn,sans-serif;overflow:hidden">
              <div style="height:{h - app_h - 18}px;display:grid;place-items:center;color:#fff;font-size:{w // 15}px;text-align:center;padding:0 16px">{title}</div>
              <img src="data:image/png;base64,{img}" style="display:block;width:{w - 24}px;margin:0 12px;border-radius:22px;box-shadow:0 10px 30px rgba(80,20,40,.3)">
              </body></html>""")
            frame.wait_for_timeout(400)
            frame.screenshot(path=str(OUT / f"{label}-{i}-{view}.png"))
            frame.close()
        ctx.close()
    # Google Play 主打圖片
    html = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
    defs = re.search(r'<svg width="0" height="0"[\s\S]*?</svg>', html).group(0)
    pg = b.new_page(viewport={"width": 1024, "height": 500})
    pg.set_content(f"""<html><head><link rel="stylesheet" href="{(ROOT / 'www' / 'fonts' / 'fonts.css').as_uri()}"></head>
      <body style="margin:0;width:1024px;height:500px;background:#fff3ee;font-family:Huninn,sans-serif;display:flex;align-items:center;gap:40px;padding:0 70px;box-sizing:border-box">{defs}
      <svg viewBox="0 0 120 104" width="380" height="330"><use href="#cat-happy"/></svg>
      <div><div style="font-size:72px;color:#c9406c">隨手記帳本</div><div style="font-size:34px;color:#6e5a64;margin-top:12px">招財貓財財陪你記帳<br>說一句話就記好 🐟</div></div></body></html>""")
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT / "googleplay-feature-graphic.png"))
    b.close()
print("done")
