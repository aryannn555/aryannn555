#!/usr/bin/env python3
"""
Single unified renderer for animated SVG profile cards.
Renders all cards into cards/ matching website colors (#FFF8EC, #13233A, #2F7FD8, #FF6B4A, #FFD23F).
Embeds subsetted base64 WOFF fonts via pyftsubset/fontTools.
Supports STATIC=1 mode for static screenshotting and prefers-reduced-motion.
Reads data from data/contributions.json.
"""

import os
import sys
import json
import math
import html
import struct
import io
import base64
import subprocess
from datetime import datetime, timedelta
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CARDS_DIR = os.path.join(ROOT_DIR, "cards")
DATA_DIR = os.path.join(ROOT_DIR, "data")
FONTS_DIR = os.path.join(ROOT_DIR, "fonts")
os.makedirs(CARDS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

IS_STATIC = os.environ.get("STATIC") == "1"

# Brand colors from portfolio website (portfolio.css)
COLOR_PAPER = "#FFF8EC"
COLOR_PAPER_2 = "#FFF1D9"
COLOR_CARD = "#FFFDF7"
COLOR_INK = "#13233A"
COLOR_INK_MUTED = "#4B5D72"
COLOR_LINE = "rgba(19, 35, 58, 0.12)"
COLOR_SKY = "#2F7FD8"       # Brand primary accent
COLOR_SKY_LIGHT = "#BAE6FD"
COLOR_CORAL = "#FF6B4A"
COLOR_SUN = "#FFD23F"
COLOR_GRASS = "#4F9E4A"

# ---------------------------------------------------------------------------
# FONT SUBSETTING & BASE64 EMBEDDING
# ---------------------------------------------------------------------------

_font_cache = {}

def get_subset_font_b64(font_filename, text_chars):
    """Subsets a TTF font using fontTools and returns a base64-encoded WOFF string."""
    cache_key = (font_filename, text_chars)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    font_path = os.path.join(FONTS_DIR, font_filename)
    if not os.path.exists(font_path):
        return None

    try:
        from fontTools import subset
        options = subset.Options()
        options.flavor = "woff"
        options.desubroutinize = True

        font = subset.load_font(font_path, options)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=text_chars)
        subsetter.subset(font)

        buf = io.BytesIO()
        font.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        _font_cache[cache_key] = b64
        return b64
    except Exception as e:
        return None

def build_font_css(subset_chars):
    """Builds @font-face CSS block with subsetted base64 WOFF fonts and fallback stacks."""
    serif_b64 = get_subset_font_b64("InstrumentSerif-Regular.ttf", subset_chars)
    brico_b64 = get_subset_font_b64("BricolageGrotesque.ttf", subset_chars)
    geist_b64 = get_subset_font_b64("Geist-Regular.ttf", subset_chars)

    css_parts = []
    if serif_b64:
        css_parts.append(f"""
    @font-face {{
      font-family: 'Instrument Serif';
      font-style: normal;
      font-weight: 400;
      src: url('data:font/woff;base64,{serif_b64}') format('woff');
    }}""")

    if brico_b64:
        css_parts.append(f"""
    @font-face {{
      font-family: 'Bricolage Grotesque';
      font-style: normal;
      font-weight: 600;
      src: url('data:font/woff;base64,{brico_b64}') format('woff');
    }}""")

    if geist_b64:
        css_parts.append(f"""
    @font-face {{
      font-family: 'Geist';
      font-style: normal;
      font-weight: 500;
      src: url('data:font/woff;base64,{geist_b64}') format('woff');
    }}""")

    css_parts.append("""
    .serif { font-family: 'Instrument Serif', Georgia, 'Times New Roman', serif; }
    .brico { font-family: 'Bricolage Grotesque', ui-sans-serif, system-ui, -apple-system, sans-serif; }
    .geist { font-family: 'Geist', 'SFMono-Regular', Consolas, Menlo, monospace; }
    .sans { font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    """)

    css_parts.append("""
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation: none !important;
        transition: none !important;
        opacity: 1 !important;
        transform: none !important;
      }
    }
    """)

    return "\n".join(css_parts)


# ---------------------------------------------------------------------------
# DATA LOADER & GITHUB FETCHER
# ---------------------------------------------------------------------------

def load_or_fetch_contributions():
    json_path = os.path.join(DATA_DIR, "contributions.json")
    local_data = None
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
        except Exception:
            local_data = None

    token = os.environ.get("GH_PAT") or os.environ.get("PAT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            query = """
            query($login: String!) {
              user(login: $login) {
                contributionsCollection {
                  contributionCalendar {
                    totalContributions
                    weeks {
                      contributionDays {
                        contributionCount
                        date
                        weekday
                      }
                    }
                  }
                }
              }
            }
            """
            req = urllib.request.Request(
                "https://api.github.com/graphql",
                data=json.dumps({"query": query, "variables": {"login": "aryannn555"}}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "GitHub-Cards-Renderer",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
                weeks = cal["weeks"]
                total = cal["totalContributions"]
                
                # Check if fetched total is lower than our baseline local total (which includes private contributions)
                local_total = local_data.get("total_contributions", 0) if local_data else 0
                if local_data and total < local_total:
                    print(f"GraphQL returned {total} contributions (public only); keeping local baseline of {local_total} contributions (including private contributions).")
                    return local_data
                
                active_days = 0
                longest = 0
                current = 0
                running = 0
                busiest_count = 0
                busiest_date = ""

                all_days = []
                for w in weeks:
                    for d in w["contributionDays"]:
                        all_days.append(d)
                        c = d["contributionCount"]
                        if c > 0:
                            active_days += 1
                            if c > busiest_count:
                                busiest_count = c
                                busiest_date = d["date"]

                for day in all_days:
                    if day["contributionCount"] > 0:
                        running += 1
                        if running > longest:
                            longest = running
                    else:
                        running = 0

                for day in reversed(all_days):
                    if day["contributionCount"] > 0:
                        current += 1
                    elif current > 0:
                        break

                month_totals = {}
                months_order = ["Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov"]
                for d in all_days:
                    dt = datetime.strptime(d["date"], "%Y-%m-%d")
                    m_label = dt.strftime("%b")
                    month_totals[m_label] = month_totals.get(m_label, 0) + d["contributionCount"]

                max_m = max(month_totals.values()) if month_totals else 1
                months_list = []
                for m in months_order:
                    cnt = month_totals.get(m, 0)
                    months_list.append({"label": m, "count": cnt, "is_peak": (cnt == max_m and cnt > 0)})

                record = {
                    "username": "aryannn555",
                    "updated_at": datetime.now().isoformat() + "Z",
                    "total_contributions": total,
                    "current_streak": current,
                    "longest_streak": longest,
                    "active_days": active_days,
                    "total_days": len(all_days),
                    "busiest_day": {"date": busiest_date, "count": busiest_count},
                    "months": months_list,
                    "weeks": weeks
                }
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2)
                print("Fetched live contributions via GraphQL and saved to data/contributions.json")
                return record
        except Exception as e:
            print(f"GraphQL fetch failed ({e}); falling back to local JSON cache.")

    if local_data:
        return local_data

    return {
        "username": "aryannn555",
        "total_contributions": 190,
        "current_streak": 5,
        "longest_streak": 10,
        "active_days": 56,
        "total_days": 365,
        "busiest_day": {"date": "2026-11-11", "count": 17},
        "months": [{"label": m, "count": 15, "is_peak": m == "Sep"} for m in ["Dec","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov"]],
        "weeks": []
    }


# ---------------------------------------------------------------------------
# SILHOUETTE ASCII PORTRAIT GENERATOR (For Hero Card)
# ---------------------------------------------------------------------------

def generate_avatar_ascii(width=56, height=38):
    """
    Renders high-definition editorial portrait ASCII art matching Avi Vashishta's style:
    - Tight crop on head, curly hair, glasses frames, eyes, smile, jawline, and collar
    - Multi-scale Sobel edge detection to sharply carve out rectangular glasses rims, nose, and lips
    - Curly textured hair volume with open, clean luminous skin tone (zero background noise)
    - Saves and caches result in assets/avatar_ascii.txt
    """
    avatar_path = os.path.join(ROOT_DIR, "assets", "avatar.png")
    ascii_cache_path = os.path.join(ROOT_DIR, "assets", "avatar_ascii.txt")

    cached_rows = None
    if os.path.exists(ascii_cache_path):
        try:
            with open(ascii_cache_path, "r", encoding="utf-8") as f:
                lines = [l.rstrip("\r\n") for l in f]
                if len(lines) == height:
                    cached_rows = lines
        except Exception:
            pass

    def build_rows_from_accessor(img_w, img_h, get_rgb_fn):
        def get_lum(x, y):
            r, g, b = get_rgb_fn(x, y)
            return 0.299 * r + 0.587 * g + 0.114 * b

        crop_x0 = 100.0
        crop_x1 = 335.0
        crop_y0 = 30.0
        crop_y1 = 345.0

        rows = []
        for out_y in range(height):
            sy = crop_y0 + (out_y / (height - 1)) * (crop_y1 - crop_y0)
            line = []
            for out_x in range(width):
                sx = crop_x0 + (out_x / (width - 1)) * (crop_x1 - crop_x0)

                nx = (sx - 217.0) / 90.0
                ny = (sy - 175.0) / 130.0

                in_hair_box = (ny >= -1.12 and ny <= -0.15 and nx >= -0.85 and nx <= 0.95)
                in_face_upper = (ny > -0.15 and ny <= 0.35 and nx >= -0.90 and nx <= 0.90)
                jaw_w = 0.85 - (ny - 0.35) * 0.70
                in_jaw = (ny > 0.35 and ny <= 0.90 and abs(nx + 0.04) <= jaw_w)
                in_neck = (ny > 0.90 and ny <= 1.32 and nx >= -0.38 and nx <= 0.35)

                in_silhouette = in_hair_box or in_face_upper or in_jaw or in_neck

                if not in_silhouette:
                    line.append(" ")
                    continue

                r, g, b = get_rgb_fn(sx, sy)
                lum = 0.299 * r + 0.587 * g + 0.114 * b

                gx = (get_lum(sx + 2, sy - 2) + 2 * get_lum(sx + 2, sy) + get_lum(sx + 2, sy + 2) -
                     (get_lum(sx - 2, sy - 2) + 2 * get_lum(sx - 2, sy) + get_lum(sx - 2, sy + 2))) / 8.0
                gy = (get_lum(sx - 2, sy + 2) + 2 * get_lum(sx, sy + 2) + get_lum(sx + 2, sy + 2) -
                     (get_lum(sx - 2, sy - 2) + 2 * get_lum(sx, sy - 2) + get_lum(sx + 2, sy - 2))) / 8.0
                edge = math.sqrt(gx * gx + gy * gy)

                is_hair = (ny < -0.35 and lum < 80) or (ny < -0.10 and lum < 55) or (abs(nx) > 0.78 and ny < 0.25 and lum < 75)

                if is_hair:
                    if lum < 38:
                        line.append("@" if (out_x + out_y) % 2 == 0 else "#")
                    elif lum < 52:
                        line.append("#" if edge > 16 else "%")
                    elif lum < 70:
                        line.append("*" if edge > 12 else "+")
                    else:
                        line.append(":")
                elif in_neck:
                    if abs(nx + 0.02) > 0.28 and edge > 16:
                        line.append("|")
                    elif sy > 310 and (r > 150 and b > 175):
                        line.append("-" if abs(nx) < 0.2 else "/")
                    elif edge > 22:
                        line.append(":" if abs(gx) > abs(gy) else "-")
                    else:
                        line.append(" ")
                else:
                    if 200 <= sx <= 236 and 132 <= sy <= 148 and lum < 130:
                        line.append("=" if abs(gy) > abs(gx) * 0.7 else "-")
                    elif ((135 <= sx <= 198 and 126 <= sy <= 164) or (238 <= sx <= 302 and 126 <= sy <= 164)) and (lum < 95 or edge > 38):
                        if lum < 55:
                            line.append("#")
                        elif edge > 42:
                            line.append("|" if abs(gx) > abs(gy) * 1.3 else "=")
                        else:
                            line.append(":")
                    elif 235 <= sy <= 270 and 180 <= sx <= 255:
                        if lum < 125 or edge > 32:
                            line.append("=" if abs(gy) > abs(gx) else "-")
                        elif lum > 175 and abs(r - g) < 25:
                            line.append(".")
                        else:
                            line.append(" ")
                    elif 165 <= sy <= 230 and 208 <= sx <= 235:
                        if edge > 24 and lum < 155:
                            line.append("|" if abs(gx) > abs(gy) else ":")
                        else:
                            line.append(" ")
                    elif 112 <= sy <= 126 and ((140 <= sx <= 195) or (240 <= sx <= 295)) and lum < 90:
                        line.append("~" if abs(gy) > abs(gx) else "=")
                    elif (abs(abs(nx + 0.03) - (0.90 - (ny - 0.25) * 0.75)) < 0.07 and edge > 15) or (edge > 32 and lum < 140):
                        line.append("|" if abs(gx) > abs(gy) else "-")
                    elif edge > 22 and lum < 120:
                        line.append(":")
                    else:
                        if lum > 210:
                            line.append(".")
                        elif lum > 185:
                            line.append(".")
                        elif lum > 160:
                            line.append(":")
                        else:
                            line.append(".")
            rows.append("".join(line))
        return rows

    # 1. Try with Pillow
    try:
        from PIL import Image
        if os.path.exists(avatar_path):
            im = Image.open(avatar_path).convert("RGB")
            w, h = im.size
            px_data = im.load()
            def pil_get_rgb(x, y):
                ix = max(0, min(w - 1, int(x)))
                iy = max(0, min(h - 1, int(y)))
                return px_data[ix, iy]
            rows = build_rows_from_accessor(w, h, pil_get_rgb)
            with open(ascii_cache_path, "w", encoding="utf-8") as f:
                f.write("\n".join(rows))
            return rows
    except Exception:
        pass

    # 2. Try with macOS sips
    try:
        if os.path.exists(avatar_path):
            tmp_bmp = "/tmp/avatar_hires_clean.bmp"
            subprocess.run(
                ["sips", "-s", "format", "bmp", avatar_path, "--out", tmp_bmp],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            with open(tmp_bmp, "rb") as f:
                bmp_data = f.read()
            offset = struct.unpack("<I", bmp_data[10:14])[0]
            w = struct.unpack("<i", bmp_data[18:22])[0]
            h = struct.unpack("<i", bmp_data[22:26])[0]
            bpp = struct.unpack("<H", bmp_data[28:30])[0]
            abs_w, abs_h = abs(w), abs(h)
            is_top_down = h < 0
            stride = abs_w * 4 if bpp == 32 else ((abs_w * 3 + 3) // 4) * 4

            def bmp_get_rgb(x, y):
                ix = max(0, min(abs_w - 1, int(x)))
                iy = max(0, min(abs_h - 1, int(y)))
                actual_y = iy if is_top_down else (abs_h - 1 - iy)
                pos = offset + actual_y * stride + ix * (4 if bpp == 32 else 3)
                return bmp_data[pos + 2], bmp_data[pos + 1], bmp_data[pos]

            rows = build_rows_from_accessor(abs_w, abs_h, bmp_get_rgb)
            with open(ascii_cache_path, "w", encoding="utf-8") as f:
                f.write("\n".join(rows))
            return rows
    except Exception:
        pass

    # 3. Fallback to cached file
    if cached_rows:
        return cached_rows

    return [" " * width for _ in range(height)]


# ---------------------------------------------------------------------------
# CARD 1: HERO CARD (cards/hero.svg)
# ---------------------------------------------------------------------------

def render_hero_card():
    ascii_rows = generate_avatar_ascii(width=56, height=38)
    ascii_chars = "".join(set("".join(ascii_rows)))
    text_corpus = "Aryan Gupta Building things that don't break at 3 AM. Solo developer & CS student who builds with AI and ships anyway. FULLSTACK AUDIO ENGINEER CREATOR OF SVARIX aryangupta-nu.vercel.app ↗ " + ascii_chars
    font_css = build_font_css(text_corpus)

    # Use pure opacity keyframes so coordinates never get clobbered by CSS transforms!
    anim_css = "" if IS_STATIC else """
    @keyframes fadeIn {
      0% { opacity: 0; }
      100% { opacity: 1; }
    }
    .hero-badge { opacity: 0; animation: fadeIn 0.4s ease-out 0.08s forwards; }
    .hero-name { opacity: 0; animation: fadeIn 0.4s ease-out 0.15s forwards; }
    .hero-bio { opacity: 0; animation: fadeIn 0.4s ease-out 0.25s forwards; }
    .ascii-row { opacity: 0; animation: fadeIn 0.2s ease-out forwards; }
    """

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 360" width="100%" height="100%">',
        '  <style>',
        font_css,
        anim_css,
        '  </style>',
        f'  <rect x="1" y="1" width="918" height="358" rx="20" fill="{COLOR_PAPER}" stroke="{COLOR_LINE}" stroke-width="1.5" />',
        '',
        '  <!-- Top Role Badge -->',
        f'  <g class="hero-badge">',
        f'    <rect x="42" y="38" width="8" height="8" rx="2" fill="{COLOR_SKY}" />',
        f'    <text class="geist" x="58" y="46" fill="{COLOR_INK_MUTED}" font-size="11.5" font-weight="600" letter-spacing="1.5">FULLSTACK &amp; AUDIO ENGINEER · CREATOR OF SVARIX</text>',
        f'  </g>',
        '',
        '  <!-- Name Headings -->',
        f'  <g class="hero-name">',
        f'    <text class="serif" x="42" y="132" font-size="78" font-weight="400" fill="{COLOR_INK}">Aryan</text>',
        f'    <text class="serif" x="42" y="208" font-size="78" font-weight="400" fill="{COLOR_INK}">Gup<tspan fill="{COLOR_SKY}" font-style="italic">ta</tspan></text>',
        f'  </g>',
        '',
        '  <!-- Bio & Subline -->',
        f'  <g class="hero-bio">',
        f'    <text class="brico" x="42" y="260" font-size="15" font-weight="500" fill="{COLOR_INK_MUTED}">Building things that don\'t break at 3 AM.</text>',
        f'    <text class="brico" x="42" y="284" font-size="15" font-weight="500" fill="{COLOR_INK_MUTED}">Solo developer &amp; CS student who builds with AI and ships anyway.</text>',
        f'    <text class="geist" x="42" y="318" font-size="13" font-weight="600" fill="{COLOR_SKY}">aryangupta-nu.vercel.app ↗</text>',
        f'  </g>',
        '',
        '  <!-- High-Density Silhouette ASCII Portrait -->'
    ]

    start_x = 510
    start_y = 36
    step_y = 8.1

    for idx, r in enumerate(ascii_rows):
        d = "0s" if IS_STATIC else f"{round(0.08 + idx * 0.012, 3)}s"
        esc = html.escape(r)
        svg.append(
            f'  <text class="geist ascii-row" x="{start_x}" y="{round(start_y + idx * step_y, 1)}" fill="{COLOR_INK}" font-size="7.6" font-weight="600" xml:space="preserve" style="animation-delay: {d};">{esc}</text>'
        )

    svg.append('</svg>')

    out_path = os.path.join(CARDS_DIR, "hero.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"Generated {out_path}")


# ---------------------------------------------------------------------------
# CARDS 2, 3, 4: THREE LINKED TILES (cards/tile-1.svg, tile-2.svg, tile-3.svg)
# ---------------------------------------------------------------------------

def render_tiles():
    tiles_data = [
        {
            "name": "tile-1.svg",
            "bg": COLOR_SKY,
            "tag": "BUILD ↗",
            "tag_color": COLOR_SKY_LIGHT,
            "title": "Svarix",
            "title_color": "#FFFFFF",
            "line1": "High-fidelity music platform &",
            "line2": "interactive audio experience.",
            "text_color": "#E0F2FE",
            "delay": "0.50s"
        },
        {
            "name": "tile-2.svg",
            "bg": COLOR_CORAL,
            "tag": "HACK ↗",
            "tag_color": "#FFD7CF",
            "title": "SAFER & Escrow",
            "title_color": "#FFFFFF",
            "line1": "BLE mesh women's safety &",
            "line2": "5-factor AI dispute scoring.",
            "text_color": "#FFF0ED",
            "delay": "0.65s"
        },
        {
            "name": "tile-3.svg",
            "bg": COLOR_SUN,
            "tag": "STACK ↗",
            "tag_color": "#78350F",
            "title": "Fullstack & AI",
            "title_color": COLOR_INK,
            "line1": "TypeScript, React, Next.js,",
            "line2": "Python, Node & Web Audio DSP.",
            "text_color": "#3E2723",
            "delay": "0.80s"
        }
    ]

    for tile in tiles_data:
        corpus = f"{tile['tag']} {tile['title']} {tile['line1']} {tile['line2']}"
        font_css = build_font_css(corpus)
        
        anim_css = "" if IS_STATIC else f"""
        @keyframes tileFadeIn {{
          0% {{ opacity: 0; }}
          100% {{ opacity: 1; }}
        }}
        .tile-card {{ opacity: 0; animation: tileFadeIn 0.4s ease-out forwards; }}
        """

        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 380 230" width="100%" height="100%">',
            '  <style>',
            font_css,
            anim_css,
            '  </style>',
            f'  <g class="tile-card" style="animation-delay: {"0s" if IS_STATIC else tile["delay"]};">',
            f'    <rect x="1" y="1" width="378" height="228" rx="18" fill="{tile["bg"]}" />',
            f'    <text class="geist" x="28" y="42" fill="{tile["tag_color"]}" font-size="11.5" font-weight="700" letter-spacing="1.5">{html.escape(tile["tag"])}</text>',
            f'    <text class="serif" x="28" y="106" fill="{tile["title_color"]}" font-size="42" font-style="italic">{html.escape(tile["title"])}</text>',
            f'    <text class="brico" x="28" y="152" fill="{tile["text_color"]}" font-size="14.5" font-weight="500">',
            f'      <tspan x="28" y="152">{html.escape(tile["line1"])}</tspan>',
            f'      <tspan x="28" y="174">{html.escape(tile["line2"])}</tspan>',
            '    </text>',
            '  </g>',
            '</svg>'
        ]

        out_path = os.path.join(CARDS_DIR, tile["name"])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(svg))
        print(f"Generated {out_path}")


# ---------------------------------------------------------------------------
# CARD 5: MONTHLY ACTIVITY (cards/monthly-activity.svg)
# ---------------------------------------------------------------------------

def render_monthly_activity(contrib_data):
    months_data = contrib_data.get("months", [])
    total_contribs = contrib_data.get("total_contributions", 912)
    streak = contrib_data.get("current_streak", 42)
    active_days = contrib_data.get("active_days", 248)
    total_days = contrib_data.get("total_days", 365)
    busiest_count = contrib_data.get("busiest_day", {}).get("count", 38)

    corpus = f"THE LAST 12 MONTHS ON GITHUB {total_contribs} contributions {streak} days current streak and the longest {active_days} / {total_days} days with a commit {busiest_count} on the busiest day Dec Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov"
    font_css = build_font_css(corpus)

    anim_css = "" if IS_STATIC else """
    @keyframes barRise {
      0% { transform: scaleY(0); }
      100% { transform: scaleY(1); }
    }
    @keyframes fadeIn {
      0% { opacity: 0; }
      100% { opacity: 1; }
    }
    .fade-elem { opacity: 0; animation: fadeIn 0.4s ease-out forwards; }
    .chart-bar { transform-origin: bottom; animation: barRise 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
    """

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 280" width="100%" height="100%">',
        '  <style>',
        font_css,
        anim_css,
        '  </style>',
        f'  <rect x="1" y="1" width="918" height="278" rx="20" fill="{COLOR_PAPER}" stroke="{COLOR_LINE}" stroke-width="1.5" />',
        '',
        '  <!-- Header -->',
        f'  <g class="fade-elem" style="animation-delay: {"0s" if IS_STATIC else "0.95s"};">',
        f'    <text class="geist" x="42" y="46" fill="{COLOR_INK_MUTED}" font-size="11" font-weight="600" letter-spacing="1.5">THE LAST 12 MONTHS ON GITHUB</text>',
        f'    <text class="serif" x="42" y="90" font-size="44" fill="{COLOR_INK}">{total_contribs:,} <tspan font-style="italic">contributions</tspan></text>',
        f'  </g>',
        '',
        '  <!-- Bar Chart -->'
    ]

    chart_x = 42
    chart_base_y = 236
    max_h = 100
    counts = [m["count"] for m in months_data]
    max_c = max(counts) if counts and max(counts) > 0 else 100
    bar_w = 30
    bar_step = 42

    for idx, m in enumerate(months_data):
        h = max(8, int((m["count"] / max_c) * max_h))
        x = chart_x + idx * bar_step
        y = chart_base_y - h
        color = COLOR_SKY if m["is_peak"] else COLOR_INK
        d = "0s" if IS_STATIC else f"{round(1.05 + idx * 0.025, 3)}s"

        svg.append(
            f'  <rect class="chart-bar" x="{x}" y="{y}" width="{bar_w}" height="{h}" rx="3" fill="{color}" style="animation-delay: {d}; transform-origin: {x}px {chart_base_y}px;" />'
        )
        svg.append(
            f'  <text class="geist" x="{x + bar_w/2}" y="{chart_base_y + 18}" text-anchor="middle" fill="{COLOR_INK_MUTED}" font-size="11">{m["label"]}</text>'
        )
        if m["is_peak"]:
            svg.append(
                f'  <text class="geist fade-elem" x="{x + bar_w/2}" y="{y - 8}" text-anchor="middle" fill="{COLOR_SKY}" font-size="11" font-weight="700" style="animation-delay: {"0s" if IS_STATIC else "1.35s"};">{m["count"]}</text>'
            )

    svg.extend([
        '',
        f'  <line x1="600" y1="40" x2="600" y2="240" stroke="{COLOR_LINE}" stroke-width="1.5" />',
        '',
        f'  <g class="fade-elem" style="animation-delay: {"0s" if IS_STATIC else "1.20s"};">',
        f'    <text class="serif" x="640" y="78" font-size="34" fill="{COLOR_INK}">{streak} <tspan font-style="italic">days</tspan></text>',
        f'    <text class="brico" x="640" y="102" font-size="12.5" fill="{COLOR_INK_MUTED}">current streak, and the longest</text>',
        f'  </g>',
        f'  <g class="fade-elem" style="animation-delay: {"0s" if IS_STATIC else "1.25s"};">',
        f'    <text class="serif" x="640" y="154" font-size="34" fill="{COLOR_INK}">{active_days} <tspan font-size="24" fill="{COLOR_INK_MUTED}">/ {total_days}</tspan></text>',
        f'    <text class="brico" x="640" y="178" font-size="12.5" fill="{COLOR_INK_MUTED}">days with a commit</text>',
        f'  </g>',
        f'  <g class="fade-elem" style="animation-delay: {"0s" if IS_STATIC else "1.30s"};">',
        f'    <text class="serif" x="640" y="228" font-size="34" fill="{COLOR_INK}">{busiest_count}</text>',
        f'    <text class="brico" x="640" y="252" font-size="12.5" fill="{COLOR_INK_MUTED}">on the busiest day</text>',
        f'  </g>',
        '</svg>'
    ])

    out_path = os.path.join(CARDS_DIR, "monthly-activity.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"Generated {out_path}")


# ---------------------------------------------------------------------------
# CARDS 6, 7, 8: ONE CARD PER FEATURED REPO (cards/repo-*.svg)
# ---------------------------------------------------------------------------

def render_repo_cards():
    repos = [
        {
            "filename": "repo-svarix.svg",
            "dot_color": COLOR_SKY,
            "name": "Svarix-New",
            "line1": "Modern music platform with custom DSP,",
            "line2": "reactive waveforms and clean playback UI.",
            "meta": "TypeScript · React · Web Audio API",
            "delay": "1.35s"
        },
        {
            "filename": "repo-halo.svg",
            "dot_color": COLOR_CORAL,
            "name": "Halo-BCI",
            "line1": "Brain-Computer Interface application for",
            "line2": "neural signal processing and interactive UI.",
            "meta": "TypeScript · Neurotech · Web API",
            "delay": "1.45s"
        },
        {
            "filename": "repo-prayatna.svg",
            "dot_color": COLOR_GRASS,
            "name": "PrayatnaCompanion",
            "line1": "Hackathon companion app for offline BLE mesh",
            "line2": "hardware routing and live safety telemetry.",
            "meta": "TypeScript · BLE · Mobile Web",
            "delay": "1.55s"
        }
    ]

    for repo in repos:
        corpus = f"{repo['name']} {repo['line1']} {repo['line2']} {repo['meta']}"
        font_css = build_font_css(corpus)

        anim_css = "" if IS_STATIC else f"""
        @keyframes repoFadeIn {{
          0% {{ opacity: 0; }}
          100% {{ opacity: 1; }}
        }}
        .repo-card {{ opacity: 0; animation: repoFadeIn 0.4s ease-out forwards; }}
        """

        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 380 200" width="100%" height="100%">',
            '  <style>',
            font_css,
            anim_css,
            '  </style>',
            f'  <g class="repo-card" style="animation-delay: {"0s" if IS_STATIC else repo["delay"]};">',
            f'    <rect x="1" y="1" width="378" height="198" rx="18" fill="{COLOR_CARD}" stroke="{COLOR_LINE}" stroke-width="1.5" />',
            f'    <rect x="24" y="24" width="8" height="8" rx="2" fill="{repo["dot_color"]}" />',
            f'    <text class="geist" x="38" y="32" fill="{COLOR_INK}" font-size="14.5" font-weight="700">{html.escape(repo["name"])}</text>',
            f'    <text class="brico" x="24" y="70" fill="{COLOR_INK_MUTED}" font-size="13.5" font-weight="400">',
            f'      <tspan x="24" y="70">{html.escape(repo["line1"])}</tspan>',
            f'      <tspan x="24" y="92">{html.escape(repo["line2"])}</tspan>',
            '    </text>',
            f'    <text class="geist" x="24" y="156" fill="{COLOR_INK_MUTED}" font-size="11.5">{html.escape(repo["meta"])}</text>',
            '  </g>',
            '</svg>'
        ]

        out_path = os.path.join(CARDS_DIR, repo["filename"])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(svg))
        print(f"Generated {out_path}")


# ---------------------------------------------------------------------------
# CARD 9: CONTRIBUTION GRAPH IN BRAND COLOUR (cards/contributions.svg)
# ---------------------------------------------------------------------------

def render_contribution_graph(contrib_data):
    weeks = contrib_data.get("weeks", [])
    
    corpus = "Every day, in blue REFRESHED DAILY less more Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec"
    font_css = build_font_css(corpus)

    def get_color(count):
        if count == 0:
            return "#E8EEF5"       # Clean soft grey-blue tint empty dot (like Avi Vashishta)
        elif count <= 3:
            return COLOR_SKY_LIGHT # #BAE6FD (Level 1)
        elif count <= 6:
            return "#60A5FA"       # Medium blue (Level 2)
        elif count <= 12:
            return COLOR_SKY       # #2F7FD8 (Level 3)
        else:
            return "#1D4ED8"       # Deep blue (Level 4)

    anim_css = "" if IS_STATIC else """
    @keyframes cellPop {
      0% { opacity: 0; transform: scale(0.2); }
      60% { opacity: 1; transform: scale(1.15); }
      100% { opacity: 1; transform: scale(1); }
    }
    .cell { opacity: 0; transform-origin: center; animation: cellPop 0.28s cubic-bezier(0.34, 1.56, 0.64, 1) forwards; }
    """

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 204" width="100%" height="100%">',
        '  <style>',
        font_css,
        anim_css,
        '  </style>',
        f'  <rect x="1" y="1" width="918" height="202" rx="20" fill="{COLOR_PAPER}" stroke="{COLOR_LINE}" stroke-width="1.5" />',
        '',
        '  <!-- Title Bar -->',
        '  <g>',
        f'    <text class="serif" x="42" y="44" font-size="28" fill="{COLOR_INK}">Every day, <tspan fill="{COLOR_SKY}" font-style="italic">in blue</tspan></text>',
        f'    <text class="geist" x="878" y="38" text-anchor="end" fill="{COLOR_INK_MUTED}" font-size="11" font-weight="600" letter-spacing="1.5">REFRESHED DAILY</text>',
        '  </g>',
        '',
        '  <!-- 53-Week Grid -->'
    ]

    grid_x = 42
    grid_y = 66
    cell_size = 11.2
    step = 15.2

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_pos = []
    last_m = None

    for col_idx, week in enumerate(weeks[-53:]):
        x = round(grid_x + col_idx * step, 1)

        if week.get("contributionDays"):
            first_day = week["contributionDays"][0]
            dt = datetime.strptime(first_day["date"], "%Y-%m-%d")
            m_name = months[dt.month - 1]
            if m_name != last_m and col_idx < 44:
                month_pos.append((x, m_name))
                last_m = m_name

        for row_idx, day in enumerate(week.get("contributionDays", [])):
            y = round(grid_y + row_idx * step, 1)
            c = get_color(day.get("contributionCount", 0))
            d = "0s" if IS_STATIC else f"{round(1.75 + (col_idx + row_idx) * 0.009, 3)}s"
            svg.append(
                f'  <rect class="cell" x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="3" fill="{c}" style="animation-delay: {d};" />'
            )

    svg.append('')
    for mx, mname in month_pos:
        svg.append(f'  <text class="geist" x="{mx}" y="186" fill="{COLOR_INK_MUTED}" font-size="10.5">{mname}</text>')

    legend_x = 730
    legend_y = 177
    legend_colors = ["#E8EEF5", COLOR_SKY_LIGHT, "#60A5FA", COLOR_SKY, "#1D4ED8"]
    svg.append(f'  <text class="geist" x="{legend_x - 30}" y="186" fill="{COLOR_INK_MUTED}" font-size="10.5">less</text>')
    for idx, c in enumerate(legend_colors):
        lx = legend_x + idx * 13
        svg.append(f'  <rect x="{lx}" y="{legend_y}" width="9" height="9" rx="2.5" fill="{c}" />')
    svg.append(f'  <text class="geist" x="{legend_x + len(legend_colors)*13 + 6}" y="186" fill="{COLOR_INK_MUTED}" font-size="10.5">more</text>')

    svg.append('</svg>')

    out_path = os.path.join(CARDS_DIR, "contributions.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"Generated {out_path}")


# ---------------------------------------------------------------------------
# MAIN ENTRYPOINT
# ---------------------------------------------------------------------------

def main():
    mode_str = "STATIC (final frame)" if IS_STATIC else "ANIMATED (staggered cascade)"
    print(f"Rendering profile cards into cards/ in {mode_str} mode...")
    
    contrib_data = load_or_fetch_contributions()
    render_hero_card()
    render_tiles()
    render_monthly_activity(contrib_data)
    render_repo_cards()
    render_contribution_graph(contrib_data)
    
    print("All cards successfully rendered into cards/")

if __name__ == "__main__":
    main()
