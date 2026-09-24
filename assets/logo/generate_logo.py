#!/usr/bin/env python3
"""Generate opngx logo — vector master + raster assets at all OS sizes.

Design: Pristine-black rounded square (#050505) with coffee-green accents,
central white 8-blade shutter (camera) + green center, "opngx" wordmark
where "gx" is accent green. Works at 16px (shutter reads as camera) to
1024px (full detail). Also generates light variant for docs.

The SVG is the source of truth; all PNGs are rasterized from it via
rsvg-convert (fallback to PIL drawing if unavailable). ICO is composed
via Pillow.
"""
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "logo"
ASSETS.mkdir(parents=True, exist_ok=True)

# Colors from QSS theme
BG_DARK = "#050505"
BG_CARD = "#0d0f0d"
BORDER = "#1f261f"
BORDER_LIGHT = "#2f4a2c"
GREEN = "#4d8248"
GREEN_LIGHT = "#7fb069"
GREEN_HOVER = "#57914f"
WHITE = "#ffffff"
MUTED = "#94a3b8"

def shutter_blades_svg(cx=512, cy=420, outer_r=200, inner_r=54, blades=8):
    """Return SVG <g> with 8 white shutter blades + center green dot."""
    parts = []
    for i in range(blades):
        # Blade centered at angle; pizza-slice shape
        # Start at top (-90 deg) and go clockwise
        theta = math.radians(-90 + i * 360 / blades)
        # Blade spans one sector; add slight overlap for visual solidity
        a0 = theta - math.radians(22.5)
        a1 = theta + math.radians(22.5)
        # Outer arc points
        x0 = cx + outer_r * math.cos(a0)
        y0 = cy + outer_r * math.sin(a0)
        x1 = cx + outer_r * math.cos(a1)
        y1 = cy + outer_r * math.sin(a1)
        # Slight inner cut to leave center hole for green dot
        ix0 = cx + inner_r * math.cos(a0)
        iy0 = cy + inner_r * math.sin(a0)
        ix1 = cx + inner_r * math.cos(a1)
        iy1 = cy + inner_r * math.sin(a1)
        # Quadrilateral blade
        d = f"M {ix0:.2f} {iy0:.2f} L {x0:.2f} {y0:.2f} L {x1:.2f} {y1:.2f} L {ix1:.2f} {iy1:.2f} Z"
        parts.append(f'<path d="{d}" fill="white" stroke="{BG_DARK}" stroke-width="3" stroke-linejoin="round"/>')
    # Center green dot with white rim
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner_r}" fill="{GREEN}" stroke="white" stroke-width="7"/>')
    # Inner highlight dot
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner_r*0.38:.1f}" fill="white" opacity="0.92"/>')
    return "\n    ".join(parts)

def make_svg_dark():
    blades = shutter_blades_svg()
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">opngx — pixel-exact high-speed footage extractor</title>
  <desc id="desc">Rounded square app icon: pristine-black with 8-blade white shutter and coffee-green center, opngx wordmark below</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0d0f0d"/>
      <stop offset="100%" stop-color="#050505"/>
    </linearGradient>
    <!-- subtle outer glow for dark mode depth -->
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="12" stdDeviation="18" flood-color="#000" flood-opacity="0.55"/>
    </filter>
  </defs>

  <!-- Outer rounded square — the app shape -->
  <rect x="12" y="12" width="1000" height="1000" rx="228" ry="228" fill="url(#bg)" stroke="#1f261f" stroke-width="14" filter="url(#glow)"/>

  <!-- Inner housing circle for shutter -->
  <circle cx="512" cy="420" r="236" fill="#070807" stroke="#1f261f" stroke-width="3" opacity="0.98"/>

  <!-- Shutter blades -->
  <g id="shutter">
    {blades}
  </g>

  <!-- Wordmark -->
  <text x="512" y="760" text-anchor="middle" font-family="'Inter','Segoe UI','Ubuntu','DejaVu Sans',sans-serif" font-size="176" font-weight="800" letter-spacing="-7" fill="white">opn<tspan fill="{GREEN_LIGHT}">gx</tspan></text>

  <!-- Tagline -->
  <text x="512" y="822" text-anchor="middle" font-family="'Inter','Segoe UI',sans-serif" font-size="36" font-weight="600" letter-spacing="13" fill="#7d8a7d">PIXEL — EXACT</text>

  <!-- Speed accent — 3 short ticks at top-right of housing -->
  <g opacity="0.95">
    <rect x="742" y="248" width="48" height="8" rx="4" fill="{GREEN_LIGHT}"/>
    <rect x="742" y="268" width="32" height="8" rx="4" fill="{GREEN_LIGHT}" opacity="0.72"/>
    <rect x="742" y="288" width="20" height="8" rx="4" fill="{GREEN_LIGHT}" opacity="0.45"/>
  </g>
</svg>
'''

def make_svg_light():
    # Light variant for docs/README on white backgrounds
    blades = shutter_blades_svg()
    # Recolor blades stroke to light bg, center same green
    blades_light = blades.replace(f'stroke="{BG_DARK}"', 'stroke="white"')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bgL" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#f8fafc"/>
    </linearGradient>
  </defs>
  <rect x="12" y="12" width="1000" height="1000" rx="228" ry="228" fill="url(#bgL)" stroke="#e2e8f0" stroke-width="14"/>
  <circle cx="512" cy="420" r="236" fill="#f1f5f9" stroke="#e2e8f0" stroke-width="3"/>
  <g id="shutter">
    {blades_light}
  </g>
  <text x="512" y="760" text-anchor="middle" font-family="'Inter','Segoe UI',sans-serif" font-size="176" font-weight="800" letter-spacing="-7" fill="#0f172a">opn<tspan fill="{GREEN}">gx</tspan></text>
  <text x="512" y="822" text-anchor="middle" font-family="'Inter','Segoe UI',sans-serif" font-size="36" font-weight="600" letter-spacing="13" fill="#64748b">PIXEL — EXACT</text>
</svg>
'''

def make_icon_svg():
    """App icon — mark only (no text) for perfect legibility at 16px.
    Shutter centered, larger, fills the square. This is what ships as
    .ico / .png for Windows taskbar, macOS Dock, Linux dash, Qt window."""
    blades = shutter_blades_svg(cx=512, cy=512, outer_r=280, inner_r=72, blades=8)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">opngx icon</title>
  <desc id="desc">Pristine-black rounded square with 8-blade white shutter and coffee-green center</desc>
  <defs>
    <linearGradient id="bgIcon" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0d0f0d"/>
      <stop offset="100%" stop-color="#050505"/>
    </linearGradient>
    <filter id="glowIcon" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="12" stdDeviation="18" flood-color="#000" flood-opacity="0.55"/>
    </filter>
  </defs>
  <rect x="12" y="12" width="1000" height="1000" rx="228" ry="228" fill="url(#bgIcon)" stroke="#1f261f" stroke-width="14" filter="url(#glowIcon)"/>
  <circle cx="512" cy="512" r="310" fill="#070807" stroke="#1f261f" stroke-width="4" opacity="0.98"/>
  <g id="shutter">{blades}</g>
  <!-- speed ticks -->
  <g opacity="0.95">
    <rect x="742" y="268" width="56" height="10" rx="5" fill="{GREEN_LIGHT}"/>
    <rect x="742" y="292" width="38" height="10" rx="5" fill="{GREEN_LIGHT}" opacity="0.72"/>
    <rect x="742" y="316" width="24" height="10" rx="5" fill="{GREEN_LIGHT}" opacity="0.45"/>
  </g>
</svg>
'''

def make_wordmark_svg():
    # Horizontal wordmark for README/docs header: icon left + text right
    # Icon mini 120x120 with same shutter, text "opngx" beside
    blades_mini = shutter_blades_svg(cx=60, cy=60, outer_r=44, inner_r=12, blades=8)
    # Simplify blades for mini: keep same but smaller
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="520" height="120" viewBox="0 0 520 120" xmlns="http://www.w3.org/2000/svg">
  <rect x="2" y="2" width="116" height="116" rx="26" fill="{BG_DARK}" stroke="{BORDER}" stroke-width="3"/>
  <g transform="translate(0,0)">
    {blades_mini}
  </g>
  <text x="136" y="78" font-family="'Inter','Segoe UI',sans-serif" font-size="72" font-weight="800" letter-spacing="-3" fill="#0f172a">opn<tspan fill="{GREEN}">gx</tspan></text>
  <text x="136" y="102" font-family="'Inter','Segoe UI',sans-serif" font-size="16" font-weight="600" letter-spacing="6" fill="#64748b">PIXEL-EXACT • ULTRA-FAST</text>
</svg>
'''

def write_svg(path, content):
    Path(path).write_text(content, encoding="utf-8")
    print(f"wrote {path}")

def rasterize(svg_path, png_path, size):
    """Use rsvg-convert if available, else fall back to ImageMagick convert."""
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(png_path), str(svg_path)],
            check=True, capture_output=True,
        )
        return True
    except Exception:
        pass
    try:
        subprocess.run(
            ["convert", "-background", "none", "-resize", f"{size}x{size}", str(svg_path), str(png_path)],
            check=True, capture_output=True,
        )
        return True
    except Exception as e:
        print(f"rasterize failed for {size}: {e}")
        return False

def main():
    dark_svg = ASSETS / "logo-dark.svg"
    light_svg = ASSETS / "logo-light.svg"
    word_svg = ASSETS / "wordmark.svg"
    icon_svg = ASSETS / "icon.svg"  # app icon — mark only

    write_svg(dark_svg, make_svg_dark())
    write_svg(light_svg, make_svg_light())
    write_svg(word_svg, make_wordmark_svg())
    write_svg(icon_svg, make_icon_svg())

    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    for sz in sizes:
        out = ASSETS / f"icon-{sz}.png"
        ok = rasterize(icon_svg, out, sz)
        print(f"{'OK' if ok else 'FAIL'} {out} ({sz}x{sz})")

    # Also wordmark PNG at native 520x120 and 2x
    for scale, name in [(1, "wordmark.png"), (2, "wordmark@2x.png")]:
        w, h = 520*scale, 120*scale
        out = ASSETS / name
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(w), "-h", str(h), "-o", str(out), str(word_svg)],
                check=True, capture_output=True,
            )
            print(f"OK {out} ({w}x{h})")
        except Exception:
            print(f"FAIL {out}")

    # ICO: Windows multi-res (16,24,32,48,64,128,256)
    try:
        from PIL import Image
        ico_sizes = [16, 24, 32, 48, 64, 128, 256]
        imgs = []
        for sz in ico_sizes:
            p = ASSETS / f"icon-{sz}.png"
            if p.exists():
                im = Image.open(p).convert("RGBA")
                imgs.append(im)
        if imgs:
            # Pillow's ICO writer expects the largest first
            imgs_sorted = sorted(imgs, key=lambda im: im.width, reverse=True)
            ico_path = ASSETS / "icon.ico"
            # Save with all sizes embedded
            imgs_sorted[0].save(ico_path, sizes=[(im.width, im.height) for im in imgs_sorted])
            print(f"OK {ico_path} ({len(imgs_sorted)} sizes)")
            # Also copy to root assets/icon.ico and python assets for PyInstaller
            # Provide convenience copies
            for dst in [ROOT / "assets" / "icon.ico", ROOT / "assets" / "logo" / "app.ico"]:
                try:
                    import shutil
                    shutil.copy2(ico_path, dst)
                except Exception:
                    pass
    except Exception as e:
        print(f"ICO generation failed: {e}")

    # Also ensure a 256 PNG at assets/icon.png for Qt window icon (fallback)
    try:
        import shutil
        shutil.copy2(ASSETS / "icon-256.png", ASSETS / "icon.png")
        shutil.copy2(ASSETS / "icon-256.png", ROOT / "assets" / "icon.png")
        print("OK icon.png (256)")
    except Exception:
        pass

if __name__ == "__main__":
    main()
