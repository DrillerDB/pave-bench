"""Build the static pavebench.org site from the public results bundle.

    python3 -m pavebench.cli build-site --results results/leaderboard.json --out _site

Inputs: ``site/`` (index.html, style.css, app.js, content.json, canary.txt), the
results bundle written by ``pavebench publish``, and the public Justice IL case for
the hero drawing (public-domain Cook County orthophoto + hand trace).
"""

from __future__ import annotations

import json
import math
import shutil
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HERO_CASE = ROOT / "dataset" / "v0" / "cases" / "pb_us_il_justice_testa_001"
DOMAIN = "pavebench.org"

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><rect x="1" y="7" width="34" height="22" rx="2" fill="#1d2a30"/><path d="M8 7v8M14 7v8M20 7v8M26 7v8M8 29v-8M14 29v-8M20 29v-8M26 29v-8" stroke="#f3f5f5" stroke-width="1.6"/><path d="M3 18h30" stroke="#e8a900" stroke-width="2"/></svg>
"""


def _path(ring: list[list[float]], ox: float, oy: float) -> str:
    pts = [f"{x - ox:.1f},{y - oy:.1f}" for x, y in ring]
    return "M" + " L".join(pts) + " Z"


def _perimeter(ring: list[list[float]]) -> float:
    return sum(math.dist(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))


def build_hero(out: Path) -> str:
    """Crop the Justice ortho to the lot, write assets/hero.jpg and og.jpg, return the figure HTML."""

    meta = json.loads((HERO_CASE / "metadata.json").read_text(encoding="utf-8"))
    gold = meta["gold"]
    boundary, cutouts = gold["boundary"], gold["cutouts"]
    gsd = float(meta["resolutionMetersPerPixel"])
    img = Image.open(HERO_CASE / "image.png").convert("RGB")
    xs = [p[0] for p in boundary]
    ys = [p[1] for p in boundary]
    pad = 0.07 * max(max(xs) - min(xs), max(ys) - min(ys))
    x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
    x1, y1 = min(img.width, max(xs) + pad), min(img.height, max(ys) + pad)
    crop = img.crop((round(x0), round(y0), round(x1), round(y1)))
    cw, ch = crop.size
    (out / "assets").mkdir(parents=True, exist_ok=True)
    crop.save(out / "assets" / "hero.jpg", quality=84, optimize=True, progressive=True)

    # Open Graph card: the same crop with the trace burned in, 1200 x 630.
    og = crop.copy()
    d = ImageDraw.Draw(og, "RGBA")
    shift = [(x - x0, y - y0) for x, y in boundary]
    d.polygon(shift, fill=(232, 169, 0, 34))
    d.line(shift + [shift[0]], fill=(242, 180, 0, 255), width=5)
    for ring in cutouts:
        r = [(x - x0, y - y0) for x, y in ring]
        d.line(r + [r[0]], fill=(255, 255, 255, 255), width=3)
    scale = max(1200 / og.width, 630 / og.height)
    og = og.resize((round(og.width * scale), round(og.height * scale)))
    left, top = (og.width - 1200) // 2, (og.height - 630) // 2
    og.crop((left, top, left + 1200, top + 630)).save(out / "assets" / "og.jpg", quality=84)

    # Vector overlay in crop pixel space.
    outline = _path(boundary, x0, y0)
    islands = "".join(f'<path class="ov-island" d="{_path(r, x0, y0)}"/>' for r in cutouts)
    fs = ch * 0.032
    scale_m = 50
    scale_px = scale_m / gsd
    sbx, sby = cw * 0.04, ch * 0.95
    svg = f"""<svg class="overlay" viewBox="0 0 {cw} {ch}" preserveAspectRatio="none" aria-hidden="true">
  <path class="ov-outline" d="{outline}" style="--len:{_perimeter(boundary):.0f}" stroke-width="{max(3, cw / 260):.1f}"/>
  {islands}
  <g class="ov-scale">
    <rect class="k" x="{sbx:.1f}" y="{sby:.1f}" width="{scale_px / 2:.1f}" height="{ch * 0.009:.1f}"/>
    <rect x="{sbx + scale_px / 2:.1f}" y="{sby:.1f}" width="{scale_px / 2:.1f}" height="{ch * 0.009:.1f}"/>
    <text x="{sbx:.1f}" y="{sby - ch * 0.012:.1f}" font-size="{fs * 0.7:.1f}">0</text>
    <text x="{sbx + scale_px:.1f}" y="{sby - ch * 0.012:.1f}" font-size="{fs * 0.7:.1f}" text-anchor="middle">{scale_m} m</text>
  </g>
</svg>"""
    return (
        f'<div class="drawing" style="aspect-ratio:{cw}/{ch}">'
        f'<img src="assets/hero.jpg" width="{cw}" height="{ch}" alt="Aerial photo of an office parking lot in Justice, Illinois, with its paved area outlined in yellow and 30 landscape islands outlined in white.">'
        f"{svg}</div>"
    )


def build_site(results_path: str | Path, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    content = json.loads((SITE / "content.json").read_text(encoding="utf-8"))
    canary = (SITE / "canary.txt").read_text(encoding="utf-8").strip()
    bundle = json.dumps({"results": results, "content": content}).replace("</", "<\\/")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--HERO_FIGURE-->", build_hero(out)).replace("__DATA__", bundle).replace("__CANARY__", escape(canary))
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in ("style.css", "app.js"):
        shutil.copy(SITE / name, out / name)
    (out / "assets" / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    shutil.copy(results_path, out / "leaderboard.json")
    (out / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    return out
