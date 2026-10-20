#!/usr/bin/env python3
"""
Builds the GitHub profile from data/profile.json:
  assets/hero-{dark,light}.svg      terminal card, morphing dot portrait, identity, live stats
  assets/activity-{dark,light}.svg  streak, contribution map, monthly bars
  assets/stack-{dark,light}.svg     tools as a periodic table
  assets/link-*-{dark,light}.svg    link buttons
  README.md

Run locally:  python scripts/build.py     (no token: sample stats)
In Actions:   GH_TOKEN is set, so real stats are fetched every night.

Change what the profile says in data/profile.json. README.md and assets/*.svg are
regenerated on every run, so edits made to them by hand are overwritten.
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from fontTools import subset as ftsubset
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
ASSETS = ROOT / "assets"
TZ = ZoneInfo("Asia/Riyadh")
NOW = datetime.now(TZ)
TODAY = NOW.date()
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- profile

def load_profile() -> dict:
    path = ROOT / "data" / "profile.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"data/profile.json is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}. "
             "Check for a missing comma or quote near that spot.")
    d.setdefault("name", "Your Name")
    d.setdefault("username", "")
    d.setdefault("role", "")
    d.setdefault("tagline", "")
    d.setdefault("bio", "")
    d.setdefault("city", "Riyadh")
    d.setdefault("stack", {})
    d.setdefault("now", "")
    d.setdefault("links", {})
    d.setdefault("accent", {"light": "#b45f06", "dark": "#f0a64a"})
    return d


COORDS = {
    "riyadh": ("24.71°N 46.68°E", "ruh"), "jeddah": ("21.49°N 39.19°E", "jed"),
    "dammam": ("26.42°N 50.09°E", "dmm"), "khobar": ("26.22°N 50.20°E", "khb"),
    "alkhobar": ("26.22°N 50.20°E", "khb"), "makkah": ("21.39°N 39.86°E", "mkh"),
    "mecca": ("21.39°N 39.86°E", "mkh"), "madinah": ("24.52°N 39.57°E", "med"),
    "medina": ("24.52°N 39.57°E", "med"), "abha": ("18.22°N 42.51°E", "ahb"),
    "taif": ("21.27°N 40.42°E", "tif"), "tabuk": ("28.38°N 36.57°E", "tuu"),
    "buraidah": ("26.33°N 43.97°E", "elq"), "hail": ("27.51°N 41.72°E", "has"),
    "jazan": ("16.89°N 42.55°E", "giz"), "najran": ("17.49°N 44.13°E", "eam"),
    "alula": ("26.61°N 37.92°E", "ulh"),
}


def city_info(p: dict) -> dict:
    city = (p.get("city") or "Riyadh").strip() or "Riyadh"
    key = re.sub(r"[^a-z]", "", city.lower())
    hit = COORDS.get(key)
    return {"city": city, "key": key, "coords": hit[0] if hit else "KSA",
            "code": hit[1] if hit else (key[:3] or "ksa")}


# --------------------------------------------------------------------------- stats

QUERY = """query($login:String!){user(login:$login){
  followers{totalCount}
  pullRequests(states:MERGED){totalCount}
  repositories(ownerAffiliations:OWNER,privacy:PUBLIC,isFork:false,first:100,
               orderBy:{field:STARGAZERS,direction:DESC}){totalCount nodes{stargazerCount}}
  contributionsCollection{contributionCalendar{weeks{contributionDays{date contributionCount}}}}
}}"""


def fetch_stats(login: str, token: str) -> dict:
    import requests
    r = requests.post("https://api.github.com/graphql",
                      json={"query": QUERY, "variables": {"login": login}},
                      headers={"Authorization": f"bearer {token}"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(j["errors"][0].get("message", "GraphQL error"))
    u = j["data"]["user"]
    days = [(date.fromisoformat(d["date"]), d["contributionCount"])
            for w in u["contributionsCollection"]["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    return {"days": days, "repos": u["repositories"]["totalCount"],
            "stars": sum(n["stargazerCount"] for n in u["repositories"]["nodes"]),
            "followers": u["followers"]["totalCount"], "prs": u["pullRequests"]["totalCount"],
            "sample": False}


def sample_stats() -> dict:
    rng = np.random.default_rng(2026)
    sunday_offset = (TODAY.weekday() + 1) % 7
    start = TODAY - timedelta(days=52 * 7 + sunday_offset)
    days = []
    d = start
    while d <= TODAY:
        k = (d - start).days
        wk, dow = k // 7, (d.weekday() + 1) % 7
        vacation = wk in (17, 18, 34)
        active = not vacation and rng.random() < (0.78 if dow <= 4 else 0.28)
        days.append((d, 1 + int(rng.random() ** 2.1 * 14) if active else 0))
        d += timedelta(days=1)
    for i in range(len(days) - 20, len(days)):
        if days[i][1] == 0:
            days[i] = (days[i][0], 1 + int(rng.random() * 5))
    return {"days": days, "repos": 27, "stars": 143, "followers": 64, "prs": 46, "sample": True}


def derive(st: dict) -> dict:
    days = st["days"]
    year = days[-365:]
    total = sum(c for _, c in year)
    active = sum(1 for _, c in year if c > 0)
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:
        i -= 1                       # today not started yet: count from yesterday
    streak = 0
    while i >= 0 and days[i][1] > 0:
        streak += 1
        i -= 1
    best = max(year, key=lambda t: t[1]) if year else (TODAY, 0)
    months: dict[tuple[int, int], int] = {}
    for d, c in year:
        months[(d.year, d.month)] = months.get((d.year, d.month), 0) + c
    mlist = [(k[1], v) for k, v in sorted(months.items())][-12:]
    return {**st, "total": total, "active": active, "streak": streak, "best": best, "months": mlist}


# --------------------------------------------------------------------------- fonts

class Face:
    def __init__(self, file: str, family: str, weight: int):
        self.path = FONTS / file
        f = TTFont(self.path)
        self.adv = f["hmtx"][f.getBestCmap()[ord("M")]][0] / f["head"].unitsPerEm
        self.family, self.weight = family, weight

    def width(self, text: str, size: float, tracking_em: float = 0.0) -> float:
        return len(text) * (self.adv + tracking_em) * size

    def css(self, chars: str) -> str:
        opts = ftsubset.Options()
        opts.flavor = "woff2"
        opts.name_IDs = []
        opts.notdef_outline = True
        f = TTFont(self.path)
        sub = ftsubset.Subsetter(opts)
        sub.populate(text=chars + "0123456789")
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (f"@font-face{{font-family:'{self.family}';font-weight:{self.weight};"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


MM = Face("MartianMono-ExtraBold.ttf", "MM", 800)
JB4 = Face("JetBrainsMono-Regular.ttf", "JB", 400)
JB5 = Face("JetBrainsMono-Medium.ttf", "JB", 500)
JB7 = Face("JetBrainsMono-Bold.ttf", "JB", 700)
MONO = "'JB',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
WIDE = "'MM','JB',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"


def font_css(svg_body: str) -> str:
    text = "".join(html.unescape(t) for t in re.findall(r">([^<>]+)<", svg_body))
    chars = "".join(sorted(set(text)))
    return "".join(f.css(chars) for f in (MM, JB4, JB5, JB7))


# --------------------------------------------------------------------------- colour

def hx(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: str, b: str, t: float) -> str:
    """t of colour a over colour b."""
    ra, rb = hx(a), hx(b)
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(ra, rb))


def palette(theme: str, accent: dict) -> dict:
    if theme == "dark":
        acc = accent.get("dark", "#f0a64a")
        p = {"win": "#0c1015", "bar": "#11161c", "line": "#2b3138", "key": "#838c97",
             "val": "#eef2f6", "dim": "#2c333b", "cell0": "#161b22", "ok": "#3dd68c", "base": "#0f141a"}
    else:
        acc = accent.get("light", "#b45f06")
        p = {"win": "#ffffff", "bar": "#f7f7f6", "line": "#d1d9e0", "key": "#68717c",
             "val": "#1f2328", "dim": "#c3c9d0", "cell0": "#ebeef1", "ok": "#1f9d5c", "base": "#f6f7f8"}
    p["acc"] = acc
    p["zone"] = mix(acc, p["base"], 0.04)
    p["c"] = [p["cell0"], mix(acc, p["cell0"], .28), mix(acc, p["cell0"], .52), mix(acc, p["cell0"], .76), acc]
    return p


def base_css(P: dict) -> str:
    return f"""
.t-title{{font:500 13px {MONO};fill:{P['key']}}}
.t-cap{{font:700 10.5px {MONO};letter-spacing:.14em;fill:{P['key']}}}
.t-capa{{font:700 10.5px {MONO};letter-spacing:.14em;fill:{P['acc']}}}
.t-name{{font-family:{WIDE};font-weight:800;fill:{P['val']};letter-spacing:-.02em}}
.t-tag{{font:700 12.5px {MONO};letter-spacing:.16em;fill:{P['acc']}}}
.t-bio{{font:400 16px {SANS};fill:{P['key']}}}
.t-k{{font:700 10.5px {MONO};letter-spacing:.14em;fill:{P['key']}}}
.t-v{{font:500 15px {MONO};fill:{P['val']}}}
.t-num{{font:800 30px {WIDE};fill:{P['val']};letter-spacing:-.02em}}
.t-numa{{fill:{P['acc']}}}
.t-huge{{font:800 76px {WIDE};fill:{P['acc']};letter-spacing:-.03em}}
.t-unit{{font:500 16px {MONO};fill:{P['key']}}}
.t-mid{{font:800 26px {WIDE};fill:{P['val']};letter-spacing:-.02em}}
.t-sm{{font:800 18px {WIDE};fill:{P['val']}}}
.t-sym{{font:800 34px {WIDE};fill:{P['acc']};letter-spacing:-.03em}}
.t-el{{font:500 11.5px {MONO};fill:{P['val']}}}
.t-mbv{{font:700 12px {MONO};fill:{P['acc']}}}
@keyframes hl{{from{{opacity:0;transform:translateY(10px)}}}}
@keyframes fade{{from{{opacity:0}}}}
@keyframes grow{{from{{transform:scaleY(0)}}}}
@keyframes blink{{50%{{opacity:.25}}}}
.hl{{animation:hl .7s cubic-bezier(.2,.7,.2,1) both}}
.fd{{animation:fade .4s ease-out both}}
.gw{{transform-box:fill-box;transform-origin:50% 100%;animation:grow .7s cubic-bezier(.2,.8,.2,1) both}}
.okd{{animation:blink 1.8s ease-in-out infinite}}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def trunc(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def window(W: int, H: int, P: dict, title: str, right: str, bar: int = 56) -> str:
    return (f'<rect x="12.5" y="12.5" width="{W - 25}" height="{H - 25}" rx="16" fill="{P["win"]}" stroke="{P["line"]}"/>'
            f'<path d="M13 28.5a15.5 15.5 0 0 1 15.5-15.5h{W - 57}a15.5 15.5 0 0 1 15.5 15.5V{bar}H13z" fill="{P["bar"]}"/>'
            f'<path d="M13 {bar}.5H{W - 13}" stroke="{P["line"]}"/>'
            f'<circle cx="40" cy="{bar // 2 + 6.5}" r="6" fill="#ff5f57"/><circle cx="62" cy="{bar // 2 + 6.5}" r="6" fill="#febc2e"/>'
            f'<circle cx="84" cy="{bar // 2 + 6.5}" r="6" fill="#28c840"/>'
            f'<text class="t-title" x="{W // 2}" y="{bar // 2 + 11}" text-anchor="middle">{esc(title)}</text>'
            f'<text class="t-cap" x="{W - 36}" y="{bar // 2 + 11}" text-anchor="end">{esc(right)}</text>')


def wrap_svg(W: int, H: int, title: str, desc: str, css: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-labelledby="t d"><title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>'
            f'<style>{font_css(body)}{css}</style>{body}</svg>')


# --------------------------------------------------------------------------- dithering

GW, GH, BW, BH = 280, 320, 420, 480           # dot grid, drawing box (1 grid step = 1.5px)


def fs_dither(a: np.ndarray, keep) -> list[tuple[int, int]]:
    """Floyd–Steinberg with serpentine scan. keep(q, y, x) decides which pixels become dots."""
    rows = a.tolist()
    H, W = len(rows), len(rows[0])
    pts = []
    for y in range(H):
        row = rows[y]
        nxt = rows[y + 1] if y + 1 < H else None
        d = 1 if y % 2 == 0 else -1
        for x in (range(W) if d == 1 else range(W - 1, -1, -1)):
            old = row[x]
            q = 1.0 if old >= 0.5 else 0.0
            e = old - q
            row[x] = q
            xd = x + d
            if 0 <= xd < W:
                row[xd] += e * 0.4375
            if nxt is not None:
                xm = x - d
                if 0 <= xm < W:
                    nxt[xm] += e * 0.1875
                nxt[x] += e * 0.3125
                if 0 <= xd < W:
                    nxt[xd] += e * 0.0625
            if keep(q, y, x):
                pts.append((x, y))
    return pts


def cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    W, H = size
    s = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * s)), max(H, round(im.height * s))), Image.LANCZOS)
    left = (im.width - W) // 2
    top = int((im.height - H) * 0.2)
    return im.crop((left, top, left + W, top + H))


def portrait_points(dark: bool, contrast: float = 1.15):
    src = ROOT / "assets" / "source" / "portrait.png"
    if not src.exists():
        fail("assets/source/portrait.png is missing.")
    im = cover(Image.open(src), (GW, GH))
    if im.mode in ("LA", "RGBA", "PA"):
        mask = np.asarray(im.convert("RGBA").getchannel("A"), dtype=np.float32) / 255 > 0.5
    else:
        mask = None
    L = np.asarray(im.convert("L"), dtype=np.float32) / 255
    if mask is None or mask.sum() < 50:
        mask = L < 0.95                     # plain photo: treat near-white as background
    vals = np.sort(L[mask])
    lo, hi = vals[int(len(vals) * 0.02)], vals[int(len(vals) * 0.98) - 1]
    v = np.clip(((L - lo) / max(0.05, hi - lo) - 0.5) * contrast + 0.5, 0, 1)
    jitter = (np.random.default_rng(3).random(L.shape) - 0.5) * 0.14
    level = (0.07 + 0.6 * v ** 1.35) if dark else (0.06 + 0.82 * v)
    a = np.where(mask, level + jitter, 0.0 if dark else 1.0)
    ml = mask.tolist()
    pts = fs_dither(a, lambda q, y, x: ml[y][x] and (q == 1.0 if dark else q == 0.0))
    tone = [float(v[y, x] if dark else 1 - v[y, x]) for x, y in pts]
    return pts, tone


def shape_points(draw_fn) -> list[tuple[int, int]]:
    S = 2
    im = Image.new("L", (BW * S, BH * S), 255)
    draw_fn(ImageDraw.Draw(im), S)
    L = np.asarray(im.resize((GW, GH), Image.LANCZOS), dtype=np.float32) / 255
    Ll = L.tolist()
    return fs_dither(L.copy(), lambda q, y, x: q == 0.0 and Ll[y][x] < 0.97)


def draw_skyline(d: ImageDraw.ImageDraw, S: int) -> None:
    sc = lambda pts: [(x * S, y * S) for x, y in pts]
    circ = lambda cx, cy, r, f: d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=f)
    circ(318, 170, 62, 222)
    for x, t, w in [(6, 318, 26), (36, 262, 24), (64, 338, 22), (88, 292, 18), (206, 276, 22),
                    (232, 330, 18), (254, 236, 20), (360, 286, 24), (388, 330, 26), (392, 250, 14)]:
        d.rectangle([x * S, t * S, (x + w) * S, 446 * S], fill=172)
    cx, top, base, hw = 150, 54, 446, 46                       # Kingdom Centre
    W = lambda y: hw * max(0.0, (y - top) / (base - top)) ** 0.5
    ys = list(range(top, base + 1, 2))
    d.polygon(sc([(cx - W(y), y) for y in ys] + [(cx + W(y), y) for y in reversed(ys)]), fill=46)
    ht, hb = 74, 196

    def hole(y):
        w = W(y) - 9
        if y > hb - 28:
            k = (y - (hb - 28)) / 28
            w *= max(0.0, 1 - k * k) ** 0.5
        return max(0.0, w)
    ys = list(range(ht, hb + 1))
    d.polygon(sc([(cx - hole(y), y) for y in ys] + [(cx + hole(y), y) for y in reversed(ys)]), fill=255)
    bw = hole(118)
    d.rectangle([(cx - bw - 2) * S, 118 * S, (cx + bw + 2) * S, 124 * S], fill=46)
    d.rectangle([(cx - 76) * S, 412 * S, (cx + 76) * S, 446 * S], fill=120)
    fx = 312                                                   # Al Faisaliah
    d.polygon(sc([(fx - 36, 446), (fx - 4, 138), (fx, 92), (fx + 4, 138), (fx + 36, 446)]), fill=54)
    circ(fx, 214, 23, 255)
    circ(fx, 214, 17, 40)
    d.rectangle([0, 446 * S, BW * S, 453 * S], fill=30)


def ksa_data() -> dict:
    return json.loads((ROOT / "scripts" / "data" / "ksa.json").read_text())


def ksa_rings() -> list[list[tuple[float, float]]]:
    rings = []
    for part in ksa_data()["d"].split("M")[1:]:
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", part)]
        rings.append(list(zip(nums[0::2], nums[1::2])))
    return rings


def draw_map(city_key: str):
    def fn(d: ImageDraw.ImageDraw, S: int) -> None:
        for ring in ksa_rings():
            pts = [(x * S, y * S) for x, y in ring]
            d.polygon(pts, fill=150)
            d.line(pts + [pts[0]], fill=28, width=round(3.2 * S), joint="curve")
        c = ksa_data()["cities"].get(city_key)
        if c:
            x, y = c[0] * S, c[1] * S
            d.ellipse([x - 7 * S, y - 7 * S, x + 7 * S, y + 7 * S], fill=20)
            d.ellipse([x - 15 * S, y - 15 * S, x + 15 * S, y + 15 * S], outline=20, width=round(2.4 * S))
    return fn


def draw_name(name: str):
    words = name.upper().split()
    lines = [words[0], " ".join(words[1:])] if len(words) >= 2 else [name.upper()]

    def fn(d: ImageDraw.ImageDraw, S: int) -> None:
        path = str(FONTS / "MartianMono-ExtraBold.ttf")
        size = (170 if len(lines) > 1 else 220) * S
        f = ImageFont.truetype(path, size)
        w = max(d.textlength(l, font=f) for l in lines)
        size = int(min(size, size * 360 * S / max(1, w)))
        f = ImageFont.truetype(path, size)
        lh = size * 1.08
        y0 = BH * S / 2 - 10 * S - (len(lines) - 1) * lh / 2
        for i, l in enumerate(lines):
            d.text((BW * S / 2, y0 + i * lh), l, font=f, fill=40, anchor="mm")
    return fn


# --------------------------------------------------------------------------- hero

BANDS = 20
HOLD = {"portrait": 6.0, "skyline": 3.6, "map": 4.2, "name": 3.6}


def dots_path(pts: list[tuple[int, int]]) -> str:
    out, px, py = [], None, None
    for x, y in sorted(pts, key=lambda t: (t[1], t[0])):
        out.append(f"M{x} {y}h0" if px is None else f"m{x - px} {y - py}h0")
        px, py = x, y
    return "".join(out)


def frame_groups(idx: int, pts, tone=None) -> str:
    """One frame as horizontal bands, each band delayed a little so frames sweep top to bottom."""
    buckets: dict[tuple[int, int], list] = {}
    for i, (x, y) in enumerate(pts):
        b = y * BANDS // GH
        cls = 2 if tone is None else (2 if tone[i] > 0.66 else 1 if tone[i] > 0.33 else 0)
        buckets.setdefault((b, cls), []).append((x, y))
    out = [f'<g class="f f{idx}">']
    for b in range(BANDS):
        paths = "".join(f'<path class="o{c}" d="{dots_path(buckets[(b, c)])}"/>'
                        for c in range(3) if (b, c) in buckets)
        if paths:
            out.append(f'<g class="b" style="animation-delay:{b * 0.55 / BANDS:.3f}s">{paths}</g>')
    out.append("</g>")
    return "".join(out)


def timeline(frames: list[str]):
    switches, t = [], HOLD[frames[0]]
    for k in frames[1:]:
        switches.append(t)
        t += HOLD[k]
    switches.append(t)                         # back to the portrait
    T = t + 1.2
    return switches, T


def frame_keyframes(frames: list[str]) -> tuple[str, float, list[float]]:
    sw, T = timeline(frames)
    p = lambda s: f"{max(0.0, min(100.0, s / T * 100)):.3f}%"
    shown, above, below = "opacity:1;transform:none", "opacity:0;transform:translateY(-6px)", "opacity:0;transform:translateY(6px)"
    css = []
    last = sw[-1]
    css.append(f"@keyframes k0{{0%{{{shown}}}{p(sw[0])}{{{shown}}}{p(sw[0] + .8)}{{{below}}}"
               f"{p(last + .35)}{{{above}}}100%{{{shown}}}}}")
    for i in range(1, len(frames)):
        a, b = sw[i - 1], sw[i]
        css.append(f"@keyframes k{i}{{0%{{{above}}}{p(a + .35)}{{{above}}}{p(a + 1.15)}{{{shown}}}"
                   f"{p(b)}{{{shown}}}{p(b + .8)}{{{below}}}100%{{{below}}}}}")
    scan = ["0%{opacity:0;transform:translateY(0)}"]
    for s in sw:
        scan.append(f"{p(s - .02)}{{opacity:0;transform:translateY(0)}}{p(s)}{{opacity:1;transform:translateY(0)}}"
                    f"{p(s + .9)}{{opacity:1;transform:translateY(480px)}}{p(s + .95)}{{opacity:0;transform:translateY(480px)}}")
    scan.append("100%{opacity:0;transform:translateY(480px)}")
    css.append("@keyframes scan{" + "".join(scan) + "}")
    for i in range(len(frames)):
        css.append(f".f{i} .b,.l{i}{{animation-name:k{i}}}")
        if i:
            css.append(f".f{i} .b,.l{i}{{opacity:0}}")
    css.append(f".b,.fl{{animation-duration:{T:.2f}s;animation-iteration-count:infinite;"
               "animation-timing-function:cubic-bezier(.45,0,.25,1)}")
    css.append(f".scan{{opacity:0;animation:scan {T:.2f}s linear infinite}}")
    return "".join(css), T, sw


def build_hero(p: dict, s: dict, theme: str, login: str) -> str:
    P = palette(theme, p["accent"])
    dark = theme == "dark"
    ci = city_info(p)
    frames = ["portrait"] + (["skyline"] if ci["key"] in ("riyadh", "") else []) + ["map", "name"]
    labels = {"portrait": "PORTRAIT", "skyline": "RIYADH.SKYLINE", "map": f"KSA · {ci['city'].upper()}", "name": "NAME"}

    por, tone = portrait_points(dark)
    groups = [frame_groups(0, por, tone)]
    for i, k in enumerate(frames[1:], start=1):
        fn = draw_skyline if k == "skyline" else draw_map(ci["key"]) if k == "map" else draw_name(p["name"])
        g = frame_groups(i, shape_points(fn))
        if k == "map" and ci["key"] in ksa_data()["cities"]:
            cx, cy = (v / 1.5 for v in ksa_data()["cities"][ci["key"]])
            pulse = "".join(f'<circle class="pu" style="animation-delay:{dl}s" cx="{cx:.1f}" cy="{cy:.1f}" r="10" '
                            f'fill="none" stroke="{P["acc"]}" stroke-width=".9"/>' for dl in (0, .8))
            g = g[:-4] + f'<g class="b" style="animation-delay:.3s">{pulse}</g></g>'
        groups.append(g)
    kf, T, sw = frame_keyframes(frames)

    nm = (p.get("name") or login).strip()
    words = nm.split()
    lines = [words[0], " ".join(words[1:])] if (len(words) >= 2 and len(nm) > 9) else [nm]
    fs = 76 if len(lines) > 1 else 84
    widest = max(MM.width(l, 1, -0.02) for l in lines)
    fs = min(fs, int(612 / widest))
    base0 = 124 + fs * 0.76
    name_svg = "".join(f'<tspan x="542" y="{base0 + i * fs * 0.98:.1f}">{esc(l)}</tspan>' for i, l in enumerate(lines))
    tag_y = base0 + (len(lines) - 1) * fs * 0.98 + 44

    tag = "  //  ".join(x.strip().upper() for x in (p.get("role"), p.get("tagline")) if x and x.strip())
    stk = p.get("stack", {})
    j = lambda *keys: " · ".join(v for k in keys for v in stk.get(k, []) if v)
    rows = [("BASE", f"{ci['city']}, Saudi Arabia"), ("STACK", j("languages")), ("WEB", j("web")),
            ("BACKEND", j("backend", "data")), ("TOOLS", j("infra", "tools")), ("NOW", p.get("now", ""))]
    rows = [r for r in rows if r[1] and r[1].strip()]
    rs = ""
    for i, (k, v) in enumerate(rows):
        y = 84 + i * 26
        if tag_y + y > 524:
            break
        rs += (f'<g class="hl" style="animation-delay:{1.0 + i * .07:.2f}s"><text class="t-k" x="546" y="{y}">{k}</text>'
               f'<text class="t-v" x="660" y="{y}">{esc(trunc(v, 52))}</text></g>')
    stats = [("STREAK", f"{s['streak']}d", True), ("CONTRIBS · 12M", f"{s['total']:,}", False),
             ("REPOS", f"{s['repos']:,}", False), ("STARS", f"{s['stars']:,}", False)]
    ss = ""
    for i, (k, v, a) in enumerate(stats):
        x = 546 + i * 156
        ss += (f'<g class="hl" style="animation-delay:{1.5 + i * .08:.2f}s">'
               f'<path d="M{x} 540H{x + 142}" stroke="{P["acc"] if a else P["line"]}" stroke-width="{2 if a else 1}"/>'
               f'<text class="t-k" x="{x}" y="562">{k}</text>'
               f'<text class="t-num{" t-numa" if a else ""}" x="{x}" y="600">{esc(v)}</text></g>')

    sync = f"SAMPLE STATS · RUN THE ACTION" if s["sample"] else f"SYNC {TODAY.isoformat()} · 00:00 AST"
    flabels = "".join(f'<text class="t-cap fl l{i}" x="462" y="105" text-anchor="end">'
                      f'{i + 1:02d}/{len(frames):02d} · {esc(labels[k])}</text>' for i, k in enumerate(frames))
    body = (
        window(1200, 660, P, f"{login}@{ci['code']}-01 — ~/profile.sh --live", sync, bar=60)
        + f'<rect x="40.5" y="84.5" width="439" height="531" rx="10" fill="{P["zone"]}" stroke="{P["line"]}"/>'
        + '<text class="t-capa" x="58" y="105">SUBJECT.SCAN</text>' + flabels
        + f'<path d="M52 126v-12h12M456 114h12v12M52 580v12h12M456 592h12v-12" fill="none" stroke="{P["acc"]}" stroke-width="1.5"/>'
        + f'<g transform="translate(50 112) scale(1.5)" fill="none" stroke="{P["acc"]}" stroke-linecap="round" stroke-width="1.05">'
        + "".join(groups) + "</g>"
        + f'<g class="scan"><rect x="56" y="104" width="408" height="14" fill="{P["acc"]}" opacity=".12"/>'
          f'<rect x="56" y="117" width="408" height="2" fill="{P["acc"]}"/></g>'
        + f'<text class="t-cap" x="58" y="605">PTS {len(por):,} · FS/SERPENTINE</text>'
        + f'<text class="t-cap" x="462" y="605" text-anchor="end">{esc(ci["coords"])}</text>'
        + f'<g class="hl" style="animation-delay:.45s"><circle class="okd" cx="551" cy="104.5" r="4" fill="{P["ok"]}"/>'
          f'<text class="t-cap" x="564" y="109">ONLINE · {esc(ci["code"].upper())}-01 · UTC+3</text></g>'
        + f'<g class="hl" style="animation-delay:.55s"><text class="t-name" font-size="{fs}">{name_svg}</text></g>'
        + f'<g transform="translate(0 {tag_y:.1f})">'
          f'<g class="hl" style="animation-delay:.8s"><text class="t-tag" x="546" y="0">{esc(trunc(tag, 62))}</text></g>'
          f'<g class="hl" style="animation-delay:.9s"><text class="t-bio" x="546" y="30">{esc(trunc(p.get("bio", ""), 70))}</text></g>'
          f'<path d="M546 54.5H1160" stroke="{P["line"]}"/>{rs}</g>'
        + ss
    )
    css = (base_css(P) + kf
           + f".o0{{opacity:.5}}.o1{{opacity:.78}}"
           + "@keyframes pu{0%{transform:scale(.3);opacity:.9}100%{transform:scale(2.6);opacity:0}}"
           + ".pu{transform-box:fill-box;transform-origin:center;animation:pu 1.6s ease-out infinite}"
           + "@media (prefers-reduced-motion:reduce){.b,.fl,.scan,.pu,.hl,.okd{animation:none!important}}")
    title = f"{nm}: profile.sh --live"
    desc = (f"Dot portrait of {nm} that turns into {'the Riyadh skyline, ' if 'skyline' in frames else ''}"
            f"a map of Saudi Arabia and the name, next to role, stack and live GitHub stats.")
    return wrap_svg(1200, 660, title, desc, css, body)


# --------------------------------------------------------------------------- activity

def build_activity(p: dict, s: dict, theme: str) -> str:
    P = palette(theme, p["accent"])
    ci = city_info(p)
    days = s["days"][-371:]
    x0, y0, step, cs = 396, 104, 14.4, 11
    first_row = (days[0][0].weekday() + 1) % 7 if days else 0
    cells, months, prev = [], [], None
    for i, (d, c) in enumerate(days):
        k = i + first_row
        col, row = k // 7, k % 7
        lvl = 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 8 else 4
        if row == 0 or i == 0:
            if d.month != prev:
                if col > 0 or d.day <= 7:
                    months.append(f'<text class="t-cap" x="{x0 + col * step:.1f}" y="94">{MON[d.month - 1].upper()}</text>')
                prev = d.month
        cells.append(f'<rect class="fd" style="animation-delay:{col * 11 + row * 16}ms" x="{x0 + col * step:.1f}" '
                     f'y="{y0 + row * step:.1f}" width="{cs}" height="{cs}" rx="2.2" fill="{P["c"][lvl]}"/>')
    dlabels = "".join(f'<text class="t-cap" x="386" y="{y0 + r * step + 9:.1f}" text-anchor="end">{t}</text>'
                      for t, r in (("SUN", 0), ("TUE", 2), ("THU", 4)))
    legend = "".join(f'<rect x="{1066 + i * 14}" y="219" width="11" height="11" rx="2.2" fill="{P["c"][i]}"/>' for i in range(5))
    ms = s["months"] or [(TODAY.month, 0)]
    mx = max(max(v for _, v in ms), 1)
    slot = 760 / len(ms)
    bars = ""
    for i, (m, v) in enumerate(ms):
        h = max(3, v / mx * 64)
        x = x0 + i * slot + (slot - 34) / 2
        top = 318 - h
        is_max = v == mx and v > 0
        col = P["acc"] if is_max else mix(P["acc"], P["cell0"], .55)
        bars += (f'<rect class="gw" style="animation-delay:{.5 + i * .05:.2f}s" x="{x:.1f}" y="{top:.1f}" width="34" '
                 f'height="{h:.1f}" rx="3" fill="{col}"/>')
        if is_max:
            bars += f'<text class="t-mbv" x="{x + 17:.1f}" y="{top - 6:.1f}" text-anchor="middle">{v:,}</text>'
        bars += f'<text class="t-cap" x="{x + 17:.1f}" y="336" text-anchor="middle">{MON[m - 1][0]}</text>'
    bd, bc = s["best"]
    avg = s["total"] / max(1, s["active"])
    body = (
        window(1200, 364, P, "activity.log --last-12m", f"{ci['city'].upper()} · UTC+3")
        + '<text class="t-capa" x="46" y="96">CURRENT STREAK</text>'
        + f'<text x="44" y="170"><tspan class="t-huge">{s["streak"]}</tspan><tspan class="t-unit" dx="10">days</tspan></text>'
        + f'<path d="M46 196.5H330" stroke="{P["line"]}"/>'
        + f'<text class="t-k" x="46" y="224">CONTRIBUTIONS</text><text class="t-mid" x="46" y="258">{s["total"]:,}</text>'
        + f'<text class="t-k" x="216" y="224">ACTIVE DAYS</text><text class="t-mid" x="216" y="258">{s["active"]}</text>'
        + f'<text class="t-k" x="46" y="296">BEST DAY</text><text class="t-sm" x="46" y="324">{bc} · {MON[bd.month - 1]} {bd.day}</text>'
        + f'<text class="t-k" x="216" y="296">AVG / ACTIVE</text><text class="t-sm" x="216" y="324">{avg:.1f}</text>'
        + f'<path d="M356.5 76V336" stroke="{P["line"]}"/>'
        + "".join(months) + dlabels + "".join(cells)
        + f'<text class="t-k" x="{x0}" y="228">CONTRIBUTIONS / MONTH</text>'
        + '<text class="t-cap" x="1058" y="228" text-anchor="end">LESS</text>' + legend
        + '<text class="t-cap" x="1140" y="228">MORE</text>' + bars
    )
    css = base_css(P) + "@media (prefers-reduced-motion:reduce){.fd,.gw{animation:none!important}}"
    return wrap_svg(1200, 364, "Activity",
                    f"{s['streak']}-day streak, {s['total']:,} contributions and {s['active']} active days in the last 12 months.",
                    css, body)


# --------------------------------------------------------------------------- stack

SYM = {"typescript": "Ts", "javascript": "Js", "python": "Py", "go": "Go", "golang": "Go", "rust": "Rs",
       "java": "Jv", "kotlin": "Kt", "swift": "Sw", "dart": "Dt", "php": "Ph", "ruby": "Rb", "c++": "C++",
       "c#": "C#", "c": "C", "solidity": "Sl", "react": "Re", "next.js": "Nx", "nextjs": "Nx", "vue": "Vu",
       "angular": "Ng", "svelte": "Sv", "tailwind": "Tw", "flutter": "Fl", "three.js": "3j", "node": "Nd",
       "node.js": "Nd", "fastapi": "Fa", "django": "Dj", "flask": "Fk", "express": "Ex", "nestjs": "Ns",
       "spring": "Sp", "laravel": "Lv", ".net": "Nt", "postgres": "Pg", "postgresql": "Pg", "mysql": "My",
       "mongodb": "Mg", "redis": "Rd", "supabase": "Sb", "firebase": "Fb", "sqlite": "Sq", "sql server": "Ss", "mssql": "Ss", "aws": "Aw",
       "gcp": "Gc", "azure": "Az", "vercel": "Vc", "docker": "Dk", "kubernetes": "K8", "git": "Gt",
       "vs code": "Vs", "vscode": "Vs", "linux": "Lx", "figma": "Fg", "cursor": "Cu", "html": "Ht", "css": "Cs",
       "sql": "Sq", "pytorch": "Pt", "tensorflow": "Tf", "pandas": "Pd", "numpy": "Np"}
CATS = [("languages", "LANG", .22), ("web", "WEB", .15), ("backend", "API", .12),
        ("data", "DATA", .10), ("infra", "OPS", .08), ("tools", "TOOL", .05)]


def symbol(name: str) -> str:
    k = name.lower().strip()
    if k in SYM:
        return SYM[k]
    w = re.sub(r"[^A-Za-z0-9+#]", "", name)
    cons = re.search(r"[bcdfghjklmnpqrstvwxz]", w[1:], re.I)
    return (w[:1].upper() + (cons.group(0) if cons else w[1:2]).lower()) or "?"


def build_stack(p: dict, theme: str) -> str | None:
    P = palette(theme, p["accent"])
    seen, items = set(), []
    for key, cat, tint in CATS:
        for v in p.get("stack", {}).get(key, []) or []:
            v = str(v).strip()
            if v and v.lower() not in seen:
                seen.add(v.lower())
                items.append((v, cat, tint))
    items = items[:24]
    if not items:
        return None
    per = 8
    rows = -(-len(items) // per)
    tw = (1176 - 48 - (per - 1) * 12) / per
    th = 118
    H = 76 + rows * (th + 12) + 14
    tiles = ""
    for i, (n, c, t) in enumerate(items):
        r, col = divmod(i, per)
        x, y = 36 + col * (tw + 12), 76 + r * (th + 12)
        tiles += (f'<g class="hl" style="animation-delay:{.15 + i * .05:.2f}s">'
                  f'<rect x="{x:.1f}" y="{y}" width="{tw:.1f}" height="{th}" rx="8" fill="{mix(P["acc"], P["win"], t)}" stroke="{P["line"]}"/>'
                  f'<text class="t-cap" x="{x + 12:.1f}" y="{y + 22}">{i + 1:02d}</text>'
                  f'<text class="t-cap" x="{x + tw - 12:.1f}" y="{y + 22}" text-anchor="end">{c}</text>'
                  f'<text class="t-sym" x="{x + 12:.1f}" y="{y + 76}">{esc(symbol(n))}</text>'
                  f'<text class="t-el" x="{x + 12:.1f}" y="{y + 101}">{esc(trunc(n, 15))}</text></g>')
    body = window(1200, H, P, "stack.periodic --by-layer", f"{len(items)} ELEMENTS") + tiles
    css = base_css(P) + "@media (prefers-reduced-motion:reduce){.hl{animation:none!important}}"
    return wrap_svg(1200, H, "Stack", "Tools as a periodic table: " + ", ".join(n for n, _, _ in items), css, body)


# --------------------------------------------------------------------------- links

def links(p: dict) -> list[dict]:
    L = p.get("links", {}) or {}
    out = []
    li = (L.get("linkedin") or "").strip()
    if li:
        url = li if li.startswith("http") else "https://www.linkedin.com/in/" + li.strip("/").removeprefix("in/").strip("/")
        out.append({"id": "linkedin", "key": "in", "label": "LINKEDIN", "url": url})
    x = (L.get("x") or "").strip()
    if x:
        handle = x.rstrip("/").split("/")[-1].lstrip("@")
        out.append({"id": "x", "key": "X", "label": "@" + handle.upper(), "url": f"https://x.com/{handle}"})
    em = (L.get("email") or "").strip()
    if em:
        out.append({"id": "email", "key": "@", "label": "EMAIL", "url": f"mailto:{em}"})
    web = (L.get("website") or "").strip()
    if web:
        url = web if web.startswith("http") else "https://" + web
        label = re.sub(r"^https?://(www\.)?", "", url).rstrip("/").upper()
        out.append({"id": "website", "key": "WWW", "label": trunc(label, 24), "url": url})
    return out


def build_chip(c: dict, theme: str, accent: dict) -> str:
    P = palette(theme, accent)
    kw = MM.width(c["key"], 11)
    lw = JB7.width(c["label"], 12, 0.1)
    W = round(16 + kw + 10 + lw + 12 + 10 + 16)
    H = 40
    ax = 16 + kw + 10 + lw + 12
    body = (f'<rect x="1" y="1" width="{W - 2}" height="{H - 4}" rx="6" fill="{P["win"]}" stroke="{P["line"]}"/>'
            f'<path d="M7 {H - 2.5}H{W - 7}" stroke="{P["line"]}" stroke-width="3" stroke-linecap="round"/>'
            f'<text x="16" y="24" style="font:800 11px {WIDE};fill:{P["acc"]}">{esc(c["key"])}</text>'
            f'<text x="{16 + kw + 10:.1f}" y="24" style="font:700 12px {MONO};letter-spacing:.1em;fill:{P["val"]}">{esc(c["label"])}</text>'
            f'<path d="M{ax:.1f} 24.5l7-7M{ax + 2:.1f} 17.5h5v5" fill="none" stroke="{P["key"]}" stroke-width="1.4" stroke-linecap="round"/>')
    return wrap_svg(W, H, c["label"], f"Link: {c['url']}", "", body)


# --------------------------------------------------------------------------- readme

VER = NOW.strftime("%Y%m%d%H%M")      # new URL on every run, so GitHub never shows a stale cached image


def picture(name: str, alt: str, width: str = "100%") -> str:
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg?v={VER}">\n'
            f'  <source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg?v={VER}">\n'
            f'  <img src="assets/{name}-light.svg?v={VER}" width="{width}" alt="{esc(alt)}">\n</picture>')


def readme(p: dict, s: dict, chips: list[dict], has_stack: bool) -> str:
    nm = p["name"]
    ci = city_info(p)
    parts = ["<!-- Generated by scripts/build.py from data/profile.json. Edit that file, not this one. -->",
             '<div align="center">', "",
             picture("hero", f"{nm}: {p.get('role', '')}, {ci['city']}. Dot portrait with live GitHub stats."),
             "", "<br>", ""]
    if chips:
        parts.append("&nbsp;".join(
            f'<a href="{esc(c["url"])}"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/link-{c["id"]}-dark.svg?v={VER}">'
            f'<img src="assets/link-{c["id"]}-light.svg?v={VER}" height="40" alt="{esc(c["label"].title())}"></picture></a>' for c in chips))
        parts += ["", "<br>", ""]
    parts += [picture("activity", f"{s['streak']}-day streak, {s['total']:,} contributions in the last 12 months"), "", "<br>", ""]
    if has_stack:
        parts += [picture("stack", "Tech stack"), "", "<br>", ""]
    stamp = "sample stats until the first Actions run" if s["sample"] else f"synced {TODAY.isoformat()} · 00:00 AST"
    parts += [f"<sub>{stamp}</sub>", "", "</div>", ""]
    return "\n".join(parts)


# --------------------------------------------------------------------------- main

def main() -> None:
    p = load_profile()
    login = os.environ.get("GITHUB_REPOSITORY_OWNER") or (p.get("username") or "").strip() or "you"
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    stats = None
    if token and login != "you":
        try:
            stats = fetch_stats(login, token)
            print(f"stats: fetched for {login}")
        except Exception as e:                     # keep the profile up even if the API hiccups
            print(f"warning: could not fetch stats ({e}); using sample stats", file=sys.stderr)
    if stats is None:
        stats = sample_stats()
        print("stats: sample data (no token)")
    s = derive(stats)

    ASSETS.mkdir(exist_ok=True)
    for old in ASSETS.glob("link-*.svg"):
        old.unlink()
    chips = links(p)
    has_stack = False
    for theme in ("dark", "light"):
        (ASSETS / f"hero-{theme}.svg").write_text(build_hero(p, s, theme, login), encoding="utf-8")
        (ASSETS / f"activity-{theme}.svg").write_text(build_activity(p, s, theme), encoding="utf-8")
        st = build_stack(p, theme)
        if st:
            has_stack = True
            (ASSETS / f"stack-{theme}.svg").write_text(st, encoding="utf-8")
        for c in chips:
            (ASSETS / f"link-{c['id']}-{theme}.svg").write_text(build_chip(c, theme, p["accent"]), encoding="utf-8")
    (ROOT / "README.md").write_text(readme(p, s, chips, has_stack), encoding="utf-8")
    for f in sorted(ASSETS.glob("*.svg")):
        print(f"  {f.name:28s} {f.stat().st_size // 1024:5d} KB")


if __name__ == "__main__":
    main()
