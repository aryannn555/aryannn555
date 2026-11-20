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
from datetime import datetime, timedelta, timezone
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
    mono_b64 = get_subset_font_b64("GeistMono-Regular.ttf", subset_chars)

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

    if mono_b64:
        css_parts.append(f"""
    @font-face {{
      font-family: 'Geist Mono';
      font-style: normal;
      font-weight: 500;
      src: url('data:font/woff;base64,{mono_b64}') format('woff');
    }}""")

    css_parts.append("""
    .serif { font-family: 'Instrument Serif', Georgia, 'Times New Roman', serif; }
    .brico { font-family: 'Bricolage Grotesque', ui-sans-serif, system-ui, -apple-system, sans-serif; }
    .geist { font-family: 'Geist', system-ui, -apple-system, sans-serif; }
    .mono { font-family: 'Geist Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace; }
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
    """
    Loads contributions from data/contributions.json and refreshes live data via GitHub GraphQL API & Events API.
    Uses smart calendar merging:
    - If GH_PAT is present, queries viewer for complete private + public contributions.
    - If GITHUB_TOKEN or local gh cli is present, queries user(login: "aryannn555").
    - Queries GitHub Events API for recent PushEvents across all repositories.
    - Merges: max(local_day, live_day, push_events_day).
    - Never wipes out historical contributions.
    - Automatically rolls the 365-day calendar forward to today's date every single day.
    - Computes rolling streaks, active days, peak month, and busiest day.
    - Saves updated data to data/contributions.json and renders fresh SVG cards.
    """
    from collections import defaultdict
    json_path = os.path.join(DATA_DIR, "contributions.json")
    local_data = None
    local_map = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            if local_data and "weeks" in local_data:
                for w in local_data["weeks"]:
                    for d in w.get("contributionDays", []):
                        local_map[d["date"]] = d.get("contributionCount", 0)
        except Exception as e:
            print(f"Notice: local contributions cache read failed ({e})")
            local_data = None

    pat_token = os.environ.get("GH_PAT") or os.environ.get("PAT_TOKEN")
    repo_token = os.environ.get("GITHUB_TOKEN")
    token = pat_token or repo_token

    if not token:
        try:
            token = subprocess.check_output(["gh", "auth", "token"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
            if token and not pat_token:
                pat_token = token
        except Exception:
            pass

    fetched_weeks = None
    headers = {
        "User-Agent": "GitHub-Cards-Renderer",
        "Content-Type": "application/json"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 1. Try querying GraphQL
    if token:
        if pat_token:
            try:
                viewer_query = """
                query {
                  viewer {
                    contributionsCollection {
                      contributionCalendar {
                        totalContributions
                        weeks {
                          contributionDays {
                            date
                            contributionCount
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
                    data=json.dumps({"query": viewer_query}).encode("utf-8"),
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    if "data" in res_json and res_json["data"].get("viewer"):
                        cal = res_json["data"]["viewer"]["contributionsCollection"]["contributionCalendar"]
                        fetched_weeks = cal["weeks"]
                        print(f"Fetched viewer contributions via GraphQL with PAT ({cal.get('totalContributions')} contributions)")
            except Exception as e:
                print(f"Viewer GraphQL query with PAT failed ({e}); falling back to user query")

        if not fetched_weeks:
            try:
                user_query = """
                query($login: String!) {
                  user(login: $login) {
                    contributionsCollection {
                      contributionCalendar {
                        totalContributions
                        weeks {
                          contributionDays {
                            date
                            contributionCount
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
                    data=json.dumps({"query": user_query, "variables": {"login": "aryannn555"}}).encode("utf-8"),
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    if "data" in res_json and res_json["data"].get("user"):
                        cal = res_json["data"]["user"]["contributionsCollection"]["contributionCalendar"]
                        fetched_weeks = cal["weeks"]
                        print(f"Fetched user contributions via GraphQL ({cal.get('totalContributions')} contributions)")
            except Exception as e:
                print(f"User GraphQL query failed ({e})")

    # 2. Query GitHub Events API for recent push events across all repositories
    daily_events = defaultdict(int)
    try:
        events_headers = {"User-Agent": "GitHub-Cards-Renderer"}
        if token:
            events_headers["Authorization"] = f"Bearer {token}"
        events_req = urllib.request.Request(
            "https://api.github.com/users/aryannn555/events?per_page=100",
            headers=events_headers
        )
        with urllib.request.urlopen(events_req, timeout=12) as resp:
            events = json.loads(resp.read().decode("utf-8"))
            for e in events:
                if e.get("type") == "PushEvent":
                    dt = e.get("created_at", "")[:10]
                    cnt = max(1, e.get("payload", {}).get("size") or 1)
                    if dt:
                        daily_events[dt] += cnt
            print(f"Fetched push events across {len(daily_events)} active dates from Events API")
    except Exception as e:
        print(f"Events API fetch notice: {e}")

    # 3. Merge live calendar, events, and local baseline
    base_weeks = fetched_weeks or (local_data.get("weeks", []) if local_data else None)
    if base_weeks:
        merged_weeks = []
        all_days = []
        total_count = 0
        active_days = 0
        busiest_count = 0
        busiest_date = ""

        for w in base_weeks:
            m_days = []
            for d in w["contributionDays"]:
                dt = d["date"]
                live_cnt = d.get("contributionCount", 0) if fetched_weeks else 0
                cnt = max(local_map.get(dt, 0), live_cnt, daily_events.get(dt, 0))
                m_day = {
                    "contributionCount": cnt,
                    "date": dt,
                    "weekday": d["weekday"]
                }
                m_days.append(m_day)
                all_days.append(m_day)
                total_count += cnt
                if cnt > 0:
                    active_days += 1
                    if cnt > busiest_count:
                        busiest_count = cnt
                        busiest_date = dt
            merged_weeks.append({"contributionDays": m_days})

        # Generate rolling 12 months sequence ending at current month
        now = datetime.now()
        months_order = []
        for i in range(11, -1, -1):
            m = (now.month - i - 1) % 12 + 1
            months_order.append(datetime(2000, m, 1).strftime("%b"))

        month_totals = {}
        for d in all_days:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            m_label = dt.strftime("%b")
            month_totals[m_label] = month_totals.get(m_label, 0) + d["contributionCount"]

        max_m = max(month_totals.values()) if month_totals else 1
        months_list = []
        for m in months_order:
            cnt = month_totals.get(m, 0)
            months_list.append({"label": m, "count": cnt, "is_peak": (cnt == max_m and cnt > 0)})

        # Compute streak (don't break on today if today has 0 so far)
        check_idx = len(all_days) - 1
        if all_days[check_idx]["contributionCount"] == 0 and check_idx > 0:
            check_idx -= 1
        cur_streak = 0
        while check_idx >= 0 and all_days[check_idx]["contributionCount"] > 0:
            cur_streak += 1
            check_idx -= 1

        longest = 0
        run = 0
        for d in all_days:
            if d["contributionCount"] > 0:
                run += 1
                if run > longest:
                    longest = run
            else:
                run = 0

        record = {
            "username": "aryannn555",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_contributions": total_count,
            "current_streak": cur_streak,
            "longest_streak": longest,
            "active_days": active_days,
            "total_days": len(all_days),
            "busiest_day": {"date": busiest_date, "count": busiest_count},
            "months": months_list,
            "weeks": merged_weeks
        }

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            print(f"Updated {json_path} successfully ({total_count} total contributions, {cur_streak} streak, rolling to {all_days[-1]['date']})")
        except Exception as e:
            print(f"Warning: writing {json_path} failed ({e})")

        return record

    if local_data:
        return local_data

    return {
        "username": "aryannn555",
        "total_contributions": 194,
        "current_streak": 0,
        "longest_streak": 4,
        "active_days": 37,
        "total_days": 365,
        "busiest_day": {"date": "2026-10-31", "count": 29},
        "months": [{"label": m, "count": 15, "is_peak": m == "Sep"} for m in ["Dec","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov"]],
        "weeks": []
    }


# ---------------------------------------------------------------------------
# SILHOUETTE ASCII PORTRAIT GENERATOR (For Hero Card)
# ---------------------------------------------------------------------------

def generate_avatar_ascii(width=58, height=38):
    """
    Returns the user-curated portrait ASCII art from assets/avatar_ascii.txt.
    Falls back to photographic Pillow generation if not present.
    """
    avatar_path = os.path.join(ROOT_DIR, "assets", "avatar.png")
    ascii_cache_path = os.path.join(ROOT_DIR, "assets", "avatar_ascii.txt")

    if os.path.exists(ascii_cache_path):
        try:
            with open(ascii_cache_path, "r", encoding="utf-8") as f_in:
                cached = f_in.read().splitlines()
                if len(cached) == height and len(cached[0]) == width:
                    return cached
        except Exception as e:
            print(f"Notice: reading ascii cache failed: {e}")

    try:
        from PIL import Image, ImageEnhance
        import numpy as np

        if os.path.exists(avatar_path):
            img = Image.open(avatar_path)
            crop = img.crop((150, 60, 690, 710))
            cw, ch = crop.size
            gray = crop.convert("L")
            enhancer = ImageEnhance.Contrast(gray)
            contrasted = enhancer.enhance(1.25)
            enhancer_b = ImageEnhance.Brightness(contrasted)
            brightened = enhancer_b.enhance(1.05)
            arr = np.array(brightened)

            silhouette = [
                (20, 38), (17, 41), (14, 44), (11, 47),
                (9, 49), (8, 50), (8, 50), (8, 50), (8, 50), (8, 50),
                (9, 49), (9, 49), (10, 48), (11, 47), (12, 46), (13, 45),
                (14, 44), (15, 43), (16, 42), (18, 40), (19, 39),
                (20, 38), (21, 37), (22, 36), (22, 36),
                (23, 35), (23, 35), (23, 35), (23, 35), (23, 35),
                (20, 38), (16, 42), (12, 46), (8, 50), (4, 54), (1, 57), (0, 57), (0, 57)
            ]

            RAMP = '@#%xo;:,. '
            rows = []
            for gy in range(height):
                y0 = int(gy * ch / height)
                y1 = int((gy + 1) * ch / height)
                s_min, s_max = silhouette[gy] if gy < len(silhouette) else (0, width - 1)
                line = []
                for gx in range(width):
                    if gx < s_min or gx > s_max:
                        line.append(' ')
                        continue
                    x0 = int(gx * cw / width)
                    x1 = int((gx + 1) * cw / width)
                    block = arr[y0:y1, x0:x1]
                    p = np.mean(block)
                    idx = int(p / 256.0 * len(RAMP))
                    idx = max(0, min(len(RAMP) - 1, idx))
                    line.append(RAMP[idx])
                rows.append(''.join(line))

            with open(ascii_cache_path, "w", encoding="utf-8") as f_out:
                f_out.write("\n".join(rows) + "\n")
            return rows
    except Exception as e:
        print(f"Notice: Pillow ASCII generator fallback triggered ({e})")

    return [" " * width for _ in range(height)]


# ---------------------------------------------------------------------------

# CARD 1: HERO CARD (cards/hero.svg)
# ---------------------------------------------------------------------------

def render_hero_card():
    ascii_rows = generate_avatar_ascii(width=58, height=38)
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
        '  <!-- High-Density Silhouette ASCII Portrait -->',
    ]

    start_x = 565
    start_y = 36
    step_y = 8.1

    for idx, r in enumerate(ascii_rows):
        d = "0s" if IS_STATIC else f"{round(0.08 + idx * 0.012, 3)}s"
        esc = html.escape(r)
        svg.append(
            f'  <text class="mono ascii-row" x="{start_x}" y="{round(start_y + idx * step_y, 1)}" fill="{COLOR_INK}" font-size="7.4" font-weight="500" xml:space="preserve" style="animation-delay: {d};">{esc}</text>'
        )

    svg.append('</svg>')

    out_path = os.path.join(CARDS_DIR, "hero.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg) + "\n")
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
