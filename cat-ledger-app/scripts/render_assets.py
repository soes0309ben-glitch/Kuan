"""用 www/index.html 裡的財財圖案產生 App icon 與啟動畫面（assets/*.png），再交給 @capacitor/assets 產生各尺寸。

用法：python3 scripts/render_assets.py   （需要 playwright 與 Chromium）
"""
import os
import pathlib
import re

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
html = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
defs = re.search(r'<svg width="0" height="0"[\s\S]*?</svg>', html).group(0)
fonts = (ROOT / "www" / "fonts").as_uri()

def page(body, size, bg):
    return f"""<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="{fonts}/fonts.css">
<style>html,body{{margin:0;width:{size}px;height:{size}px;background:{bg};overflow:hidden}}
.c{{width:100%;height:100%;display:grid;place-items:center;font-family:Huninn,sans-serif}}</style></head><body>{defs}{body}</body></html>"""

cat = lambda w, mood="happy": f'<svg viewBox="0 0 120 104" width="{w}" height="{w*104/120:.0f}"><use href="#cat-{mood}"/></svg>'
paw = "radial-gradient(circle at 50% 50%, #ffe1ea 0 46%, transparent 46.5%)"

jobs = {
    # iOS 與舊版 Android：整張不透明
    "icon-only.png": (1024, "#fff3ee", f'<div class="c" style="background:{paw}">{cat(760)}</div>'),
    # Android adaptive icon：前景透明，圖案放在中間 60% 安全區內
    "icon-foreground.png": (1024, "transparent", f'<div class="c">{cat(560)}</div>'),
    "icon-background.png": (1024, "#fff3ee", f'<div class="c" style="background:{paw}"></div>'),
    "splash.png": (2732, "#fff3ee", f'<div class="c"><div style="display:grid;justify-items:center;gap:60px">{cat(900)}<div style="font-size:150px;color:#c9406c">隨手記帳本</div></div></div>'),
    "splash-dark.png": (2732, "#1d1722", f'<div class="c"><div style="display:grid;justify-items:center;gap:60px">{cat(900, "sleep")}<div style="font-size:150px;color:#ff9ab8">隨手記帳本</div></div></div>'),
}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    for name, (size, bg, body) in jobs.items():
        pg = b.new_page(viewport={"width": size, "height": size})
        tmp = ROOT / "assets" / "_tmp.html"
        tmp.write_text(page(body, size, bg), encoding="utf-8")
        pg.goto(tmp.as_uri()); pg.wait_for_timeout(400)
        pg.screenshot(path=str(ROOT / "assets" / name), omit_background=(bg == "transparent"))
        pg.close()
        tmp.unlink()
    b.close()
print("done")
