from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS_SIZE = (1280, 640)
SAFE_MARGIN = 40
BACKGROUND = "#071018"
TITLE = "Mini EQ"
SUBTITLE_LINES = (
    "System-wide",
    "parametric EQ",
    "for PipeWire desktops",
)
FOOTER_LINES = (
    "GTK / Libadwaita",
    "WirePlumber + filter-chain",
)


def _font_path(preferred: str) -> str | None:
    fc_match = shutil.which("fc-match")
    if fc_match is not None:
        result = subprocess.run(
            [fc_match, "-f", "%{file}\n", preferred],
            check=False,
            capture_output=True,
            text=True,
        )
        path = result.stdout.strip()
        if path:
            return path

    common = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    for candidate in common:
        if Path(candidate).exists():
            return candidate
    return None


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVu Sans:style=Bold" if bold else "DejaVu Sans"
    path = _font_path(family)
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(path, size=size)


def _fit_screenshot(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail(max_size, Image.Resampling.LANCZOS)
    return fitted


def render_social_preview(screenshot_path: Path, output_path: Path) -> None:
    canvas = Image.new("RGBA", CANVAS_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(92, bold=True)
    subtitle_font = _load_font(39)
    footer_font = _load_font(29)

    draw.text((70, 82), TITLE, font=title_font, fill="#F1F5FB")
    draw.text((70, 230), "\n".join(SUBTITLE_LINES[:2]), font=subtitle_font, spacing=6, fill="#95D5FF")
    draw.text((70, 338), SUBTITLE_LINES[2], font=subtitle_font, fill="#D4DBE8")
    draw.text((70, 402), "\n".join(FOOTER_LINES), font=footer_font, spacing=8, fill="#92A2B9")

    screenshot = Image.open(screenshot_path).convert("RGBA")
    screenshot = _fit_screenshot(screenshot, (680, 380))

    frame_padding = 12
    frame_size = (
        screenshot.width + frame_padding * 2,
        screenshot.height + frame_padding * 2,
    )
    frame_pos = (CANVAS_SIZE[0] - SAFE_MARGIN - frame_size[0], 102)
    shadow_offset = (10, 14)

    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (
            frame_pos[0] + shadow_offset[0],
            frame_pos[1] + shadow_offset[1],
            frame_pos[0] + frame_size[0] + shadow_offset[0],
            frame_pos[1] + frame_size[1] + shadow_offset[1],
        ),
        radius=18,
        fill=(0, 0, 0, 110),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow)

    frame = Image.new("RGBA", frame_size, "#0F1723")
    frame_draw = ImageDraw.Draw(frame)
    frame_draw.rounded_rectangle(
        (0, 0, frame.width - 1, frame.height - 1), radius=18, fill="#0F1723", outline="#253244"
    )

    screenshot_mask = Image.new("L", screenshot.size, 0)
    mask_draw = ImageDraw.Draw(screenshot_mask)
    mask_draw.rounded_rectangle((0, 0, screenshot.width - 1, screenshot.height - 1), radius=12, fill=255)
    frame.paste(screenshot, (frame_padding, frame_padding), screenshot_mask)

    canvas.alpha_composite(frame, frame_pos)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, optimize=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a social preview image from the public Mini EQ screenshot.")
    parser.add_argument("screenshot", nargs="?", default="docs/screenshots/mini-eq.png", help="Input screenshot path")
    parser.add_argument("output", nargs="?", default="docs/social-preview.png", help="PNG output path")
    args = parser.parse_args(argv)

    screenshot_path = Path(args.screenshot).expanduser()
    output_path = Path(args.output).expanduser()
    render_social_preview(screenshot_path, output_path)
    print(f"saved social preview to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
