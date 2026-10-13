"""Share cards for PaveBench results (16:9, 1600 x 900 rendered at 2x).

    python3 promo/build_cards.py            # writes promo/out/*.html and *.png

Reads results/leaderboard.json and the public Justice IL case. Each card is a
self-contained HTML page screenshotted with headless Chrome. Cards are minimal on
purpose: a short title, the chart, the brand. One row per model (its best tested
setup); the full tables and method notes are on the site.
"""

from __future__ import annotations

import json
import math
import subprocess
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "promo" / "out"
DATA = json.loads((ROOT / "results" / "leaderboard.json").read_text())
META = DATA["meta"]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1600, 900
CW = 1400  # chart width inside the card

# Vendor colors validated with the dataviz palette checker (light surface, all checks pass).
VENDOR = {"OpenAI": "#00916f", "Google": "#3560d4", "Anthropic": "#b0532c", "Meta": "#7a4ccc"}
INK, MUTED, GRID, SHEET, CARD, PAINT = "#1d2a30", "#6b777c", "#e3e8ea", "#f3f5f5", "#fbfcfc", "#e8a900"
MONO = "Overpass Mono, monospace"


def model_of(system: str) -> str:
    return system.split(",")[0].strip()


def best_per_model(rows: list[dict], key=lambda r: r["accuracy"]) -> list[dict]:
    best: dict[str, dict] = {}
    for r in rows:
        if r.get("excluded"):
            continue
        m = model_of(r["system"])
        if m not in best or key(r) > key(best[m]):
            best[m] = r
    return sorted(best.values(), key=key, reverse=True)


def usd(v: float | None) -> str:
    if v is None:
        return "flat fee"
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}" if v >= 0.01 else f"${v:.4f}".rstrip("0")


def page(body: str, title: str) -> str:
    head = f"<h1>{escape(title)}</h1>" if title else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Overpass:wght@400;600;800&family=Overpass+Mono:wght@400;600&display=swap">
<style>
*{{box-sizing:border-box}} html,body{{margin:0;width:{W}px;height:{H}px;background:{SHEET};color:{INK};font-family:Overpass,Arial,sans-serif;-webkit-font-smoothing:antialiased}}
.card{{position:absolute;inset:28px;border:2.5px solid {INK};background:{CARD};padding:52px 70px 0;display:flex;flex-direction:column}}
h1{{font-size:64px;font-weight:800;letter-spacing:-0.02em;line-height:1.02;margin:0}}
.main{{flex:1;min-height:0;margin-top:40px}}
.brand{{position:absolute;right:30px;top:58px;display:flex;align-items:center;gap:12px;font-weight:800;font-size:26px}}
svg text{{font-family:Overpass,Arial,sans-serif}}
</style></head><body><div class="card">{head}{body}
<div class="brand"><svg width="40" height="26" viewBox="0 0 36 24"><rect x="1" y="1" width="34" height="22" rx="2" fill="{INK}"/><path d="M8 1v8M14 1v8M20 1v8M26 1v8M8 23v-8M14 23v-8M20 23v-8M26 23v-8" stroke="{SHEET}" stroke-width="1.6"/><path d="M3 12h30" stroke="{PAINT}" stroke-width="2"/></svg>pavebench.org</div>
</div></body></html>"""


def bars(rows, value, fmt, vmax, height, head=None):
    """One bar per model; value at the bar end, cost per lot in a right column."""

    label_w, right_w = 330, 170
    plot_w = CW - label_w - right_w - 130
    top = 36
    n, gap = len(rows), 14
    bh = (height - top - gap * (n - 1)) / n
    fs = min(28, bh * 0.56)
    out = [f'<svg width="{CW}" height="{height}" viewBox="0 0 {CW} {height}">']
    if head:
        out.append(f'<text x="{label_w}" y="20" font-size="20" fill="{MUTED}">{escape(head)}</text>')
    out.append(f'<text x="{CW}" y="20" font-size="20" fill="{MUTED}" text-anchor="end">cost per lot</text>')
    for i, r in enumerate(rows):
        y = top + i * (bh + gap)
        mid = y + bh / 2 + fs * 0.36
        w = max(4, plot_w * value(r) / vmax)
        out.append(f'<text x="0" y="{mid:.1f}" font-size="{fs:.0f}" font-weight="700" fill="{INK}">{escape(model_of(r["system"]))}</text>')
        out.append(f'<rect x="{label_w}" y="{y:.1f}" width="{w:.1f}" height="{bh:.1f}" rx="4" fill="{VENDOR.get(r["provider"], MUTED)}"/>')
        out.append(f'<text x="{label_w + w + 14:.1f}" y="{mid:.1f}" font-size="{fs:.0f}" font-weight="600" fill="{INK}" font-family="{MONO}">{escape(fmt(r))}</text>')
        out.append(f'<text x="{CW}" y="{mid:.1f}" font-size="{fs * 0.86:.0f}" fill="{MUTED}" text-anchor="end" font-family="{MONO}">{escape(usd(r["cost"]))}</text>')
    out.append("</svg>")
    return f'<div class="main">{"".join(out)}</div>'


def card_hero() -> str:
    from PIL import Image

    case = ROOT / "dataset" / "v0" / "cases" / "pb_us_il_justice_testa_001"
    meta = json.loads((case / "metadata.json").read_text())
    b, cuts = meta["gold"]["boundary"], meta["gold"]["cutouts"]
    img = Image.open(case / "image.png").convert("RGB")
    xs, ys = [p[0] for p in b], [p[1] for p in b]
    pad = 0.05 * max(max(xs) - min(xs), max(ys) - min(ys))
    x0, y0, x1, y1 = max(0, min(xs) - pad), max(0, min(ys) - pad), min(img.width, max(xs) + pad), min(img.height, max(ys) + pad)
    crop = img.crop((round(x0), round(y0), round(x1), round(y1)))
    crop.save(OUT / "justice.jpg", quality=88)
    cw, ch = crop.size
    path = lambda ring: "M" + " L".join(f"{x - x0:.1f},{y - y0:.1f}" for x, y in ring) + " Z"
    islands = "".join(f'<path d="{path(r)}" fill="rgba(255,255,255,.2)" stroke="#fff" stroke-width="2.4"/>' for r in cuts)
    ih = 784
    iw = ih * cw / ch
    body = f"""
<style>.card{{padding:0;flex-direction:row}} .left{{flex:1;padding:0 60px 40px 70px;display:flex;flex-direction:column;justify-content:center;gap:34px}}
.left h1{{font-size:84px}} .left p{{font:600 30px/1.3 Overpass,Arial,sans-serif;color:{MUTED};margin:0}}
.right{{position:relative;width:{iw:.0f}px;height:{ih}px;margin:28px 28px 0 0;border:2px solid {INK}}} .right img{{width:100%;height:100%;display:block}} .right svg{{position:absolute;inset:0;width:100%;height:100%}}
.brand{{left:70px;right:auto;top:auto;bottom:44px}}</style>
<div class="left"><h1>How well can AI measure a parking lot?</h1>
<p>{META['systems']} AI setups. Lot outline, stall count, striping.</p></div>
<div class="right"><img src="justice.jpg"><svg viewBox="0 0 {cw} {ch}" preserveAspectRatio="none"><path d="{path(b)}" fill="rgba(232,169,0,.16)" stroke="#f2b400" stroke-width="6" stroke-linejoin="round"/>{islands}</svg></div>"""
    return page(body, "")


def card_composite() -> str:
    rows = best_per_model(DATA["tasks"]["composite"])
    return page(bars(rows, lambda r: r["accuracy"], lambda r: f"{r['accuracy']:.2f}", 1.0, 640, head="outline + stalls + striping, 1 is perfect"), "Full takeoff score")


def card_frontier() -> str:
    rows = [r for r in best_per_model(DATA["tasks"]["composite"]) if r["cost"]]
    width, height = CW, 650
    L, R, T, B = 60, 20, 10, 70
    pw, ph = width - L - R, height - T - B
    lo, hi = min(r["cost"] for r in rows) / 1.8, max(r["cost"] for r in rows) * 1.8
    sx = lambda v: L + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * pw
    sy = lambda v: T + (1 - v / 1.0) * ph
    out = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    for v in (0.001, 0.01, 0.1, 1):
        if lo <= v <= hi:
            out.append(f'<line x1="{sx(v)}" x2="{sx(v)}" y1="{T}" y2="{T + ph}" stroke="{GRID}"/><text x="{sx(v)}" y="{T + ph + 32}" font-size="21" fill="{MUTED}" text-anchor="middle" font-family="{MONO}">${v:g}</text>')
    for v in (0.2, 0.4, 0.6, 0.8, 1.0):
        out.append(f'<line x1="{L}" x2="{L + pw}" y1="{sy(v)}" y2="{sy(v)}" stroke="{GRID}"/><text x="{L - 12}" y="{sy(v) + 7}" font-size="21" fill="{MUTED}" text-anchor="end" font-family="{MONO}">{v:.1f}</text>')
    out.append(f'<text x="{L + pw}" y="{height - 2}" font-size="21" fill="{MUTED}" text-anchor="end">cost per lot, log scale</text>')
    # Frontier: cheapest first, keep only systems that raise the best score so far.
    front, best = [], -1.0
    for r in sorted(rows, key=lambda r: r["cost"]):
        if r["accuracy"] > best:
            front.append(r)
            best = r["accuracy"]
    pts = [(sx(r["cost"]), sy(r["accuracy"])) for r in front]
    d = "".join((f" L{x:.1f},{pts[i - 1][1]:.1f} L" if i else "M") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{PAINT}" stroke-width="4" stroke-linejoin="round"/>')
    for r in rows:
        on = r in front
        out.append(f'<circle cx="{sx(r["cost"]):.1f}" cy="{sy(r["accuracy"]):.1f}" r="{13 if on else 11}" fill="{VENDOR[r["provider"]]}" stroke="{PAINT if on else CARD}" stroke-width="{4 if on else 2.5}"/>')
    # Labels avoid each other, every point and the frontier line.
    obstacles = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        obstacles += [(ax, bx, ay - 4, ay + 4), (bx - 4, bx + 4, min(ay, by), max(ay, by))]
    for r in rows:
        x, y = sx(r["cost"]), sy(r["accuracy"])
        obstacles.append((x - 15, x + 15, y - 15, y + 15))
    hit = lambda b: any(b[0] < o[1] and b[1] > o[0] and b[2] < o[3] and b[3] > o[2] for o in obstacles)
    for r in sorted(rows, key=lambda r: -r["accuracy"]):
        x, y = sx(r["cost"]), sy(r["accuracy"])
        text = model_of(r["system"])
        w, h = len(text) * 12.6, 26
        spots = [(x + 22, y + 9), (x - 22 - w, y + 9), (x - w / 2, y - 24), (x - w / 2, y + 44),
                 (x + 18, y - 20), (x - 18 - w, y - 20), (x + 18, y + 38), (x - 18 - w, y + 38)]
        spots = [s for s in spots if s[0] >= L + 4 and s[0] + w <= L + pw and s[1] - h > T]
        left, base = next((s for s in spots if not hit((s[0], s[0] + w, s[1] - h + 5, s[1] + 5))), spots[0])
        obstacles.append((left, left + w, base - h + 5, base + 5))
        out.append(f'<text x="{left:.1f}" y="{base:.1f}" font-size="23" font-weight="700" fill="{INK}" style="paint-order:stroke;stroke:{CARD};stroke-width:6px">{escape(text)}</text>')
    out.append("</svg>")
    return page(f'<div class="main" style="margin-top:34px">{"".join(out)}</div>', "Score vs. cost")


def card_outlines() -> str:
    rows = best_per_model(DATA["tasks"]["area"])[:8]
    return page(bars(rows, lambda r: r["accuracy"], lambda r: f"{r['accuracy']:.3f}", 1.0, 640, head="IoU with the hand trace, 1 is perfect"), "Lot outline accuracy")


def card_stalls() -> str:
    rows = sorted(best_per_model(DATA["tasks"]["stall"]), key=lambda r: r["meanErr"])[:8]
    vmax = max(r["meanErr"] for r in rows)
    return page(bars(rows, lambda r: r["meanErr"], lambda r: f"{r['meanErr'] * 100:.1f}%", vmax, 640, head="mean miss vs. a hand count, lower is better"), "Stall count error")


def shoot(name: str, html: str) -> Path:
    src = OUT / f"{name}.html"
    src.write_text(html, encoding="utf-8")
    png = OUT / f"{name}.png"
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}", "--force-device-scale-factor=2",
         "--virtual-time-budget=6000", f"--screenshot={png}", src.as_uri()],
        check=True, capture_output=True,
    )
    return png


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cards = {
        "1-hero": card_hero(),
        "2-composite": card_composite(),
        "3-frontier": card_frontier(),
        "4-outlines": card_outlines(),
        "5-stalls": card_stalls(),
    }
    for name, html in cards.items():
        print(shoot(name, html))


if __name__ == "__main__":
    main()
