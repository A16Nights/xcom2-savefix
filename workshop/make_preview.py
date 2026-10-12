"""Generate ModPreview.jpg for the workshop item.

Kept out of the repository: it needs Pillow, and the repository's shipped
tools are deliberately standard-library only. Run it once, commit the JPG.

    python make_preview.py [out.jpg]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W = H = 1024
BG_TOP = (14, 17, 22)
BG_BOTTOM = (22, 27, 34)
FG = (230, 237, 243)
MUTED = (125, 138, 152)
ACCENT = (255, 176, 0)      # XCOM-ish amber
GREEN = (63, 185, 80)
RED = (248, 81, 73)
PANEL = (13, 17, 23)

FONTS = r"C:\Windows\Fonts"


def font(name, size):
    for candidate in (name, "segoeui.ttf"):
        path = os.path.join(FONTS, candidate)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "ModPreview.jpg"

    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)

    # Vertical gradient background.
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        d.line([(0, y), (W, y)], fill=c)

    # Amber rule at the very top.
    d.rectangle([0, 0, W, 6], fill=ACCENT)

    f_kicker = font("segoeuib.ttf", 26)
    f_title = font("segoeuib.ttf", 104)
    f_sub = font("segoeuib.ttf", 46)
    f_body = font("segoeui.ttf", 30)
    f_mono = font("consola.ttf", 27)
    f_mono_b = font("consolab.ttf", 27)
    f_small = font("segoeui.ttf", 24)

    def center(text, y, f, fill, x=W // 2):
        w = d.textbbox((0, 0), text, font=f)[2]
        d.text((x - w // 2, y), text, font=f, fill=fill)
        return w

    y = 68
    center("XCOM 2  \u00b7  WAR OF THE CHOSEN", y, f_kicker, MUTED)
    y += 54
    center("SAVEFIX", y, f_title, FG)
    y += 118
    center("Beyond 65535", y, f_sub, ACCENT)

    # Divider.
    y += 78
    d.line([(260, y), (W - 260, y)], fill=(48, 54, 61))

    # Body text.
    y += 44
    for line in [
        "Long-modded campaign hit a wall:",
        "the save loads but the game refuses it.",
    ]:
        center(line, y, f_body, MUTED)
        y += 42

    # Symptom chips.
    y += 30
    chip_f = font("segoeuib.ttf", 25)
    chips = [("SAVE OUT OF DATE", RED), ("LOAD FAILED", RED)]
    total = 0
    widths = []
    for label, _ in chips:
        w = d.textbbox((0, 0), label, font=chip_f)[2] + 44
        widths.append(w)
        total += w + 18
    total -= 18
    cx = W // 2 - total // 2
    for (label, colour), w in zip(chips, widths):
        d.rounded_rectangle([cx, y, cx + w, y + 52], radius=26,
                            outline=colour, width=2, fill=(38, 16, 18))
        tw = d.textbbox((0, 0), label, font=chip_f)[2]
        d.text((cx + (w - tw) // 2, y + 11), label, font=chip_f, fill=colour)
        cx += w + 18

    # The actual change, in a panel.
    y += 96
    px0, px1 = 112, W - 112
    panel_h = 210
    d.rounded_rectangle([px0, y, px1, y + panel_h], radius=14,
                        fill=PANEL, outline=(48, 54, 61), width=2)

    ty = y + 30
    d.text((px0 + 34, ty), "before", font=f_small, fill=MUTED)
    d.text((px0 + 132, ty), "cmp dword [rbp+0x38], 0x10000", font=f_mono, fill=FG)
    d.text((px0 + 640, ty), "65536", font=f_mono, fill=RED)

    ty += 58
    d.text((px0 + 34, ty), "after", font=f_small, fill=MUTED)
    d.text((px0 + 132, ty), "cmp dword [rbp+0x38], 0x400000", font=f_mono_b, fill=GREEN)
    d.text((px0 + 640, ty), "4 MiB", font=f_mono_b, fill=GREEN)

    ty += 62
    d.text((px0 + 34, ty), "1 byte of XCom2.exe changes. Saves are never touched.",
           font=f_body, fill=MUTED)

    # Footer facts.
    y += panel_h + 60
    for line in [
        "Auto-detects your install  \u00b7  works on base game and WotC",
        "Backs up the original  \u00b7  one-command restore",
    ]:
        center(line, y, f_body, MUTED)
        y += 44

    y += 26
    center("github.com/A16Nights/xcom2-savefix", y, font("segoeuib.ttf", 28), ACCENT)

    # Bottom rule.
    d.rectangle([0, H - 6, W, H], fill=ACCENT)

    img.save(out, "JPEG", quality=92, optimize=True)
    print("wrote %s  %dx%d  %d bytes" % (out, W, H, os.path.getsize(out)))


if __name__ == "__main__":
    main()
