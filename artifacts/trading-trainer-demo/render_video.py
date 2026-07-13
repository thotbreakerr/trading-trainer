"""Render a concise captioned product demo from captured app screens."""

from __future__ import annotations

import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
STILLS = ROOT / "stills"
COMPOSITED = ROOT / "composited"
OUTPUT = ROOT / "trading-trainer-demo.mp4"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
TRANSITION = 0.65
SEGMENTS = ROOT / "segments"

FONT_REGULAR = Path("C:/Windows/Fonts/segoeui.ttf")
FONT_SEMIBOLD = Path("C:/Windows/Fonts/seguisb.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/seguibl.ttf")


@dataclass(frozen=True)
class Scene:
    source: str
    title: str
    subtitle: str
    duration: float
    anchor: str = "bottom-left"


SCENES = [
    Scene("intro.png", "", "", 3.4),
    Scene(
        "01-market-day.png",
        "Coach the live market",
        "Watch delayed real data, visible risk limits, and setup callouts.",
        4.0,
        "bottom-left",
    ),
    Scene(
        "02-morning-plan.png",
        "Plan before the open",
        "Map gaps, relative volume, key levels, and the day’s focus list.",
        4.2,
        "bottom-left",
    ),
    Scene(
        "03-planning-commitments.png",
        "Commit before the tape answers",
        "Record bias, invalidation, expected setup, and confidence.",
        3.8,
        "bottom-right",
    ),
    Scene(
        "04-daily-workout.png",
        "Train what is weakest",
        "Adaptive daily blocks turn recent decisions into deliberate practice.",
        4.2,
        "bottom-right",
    ),
    Scene(
        "05-scenarios.png",
        "Build pattern recognition",
        "Filter cached history and keep the outcome hidden for an honest read.",
        4.0,
        "bottom-right",
    ),
    Scene(
        "06-blind-replay.png",
        "Replay the chart, not the answer",
        "Step through real historical bars and define the risk before acting.",
        4.8,
        "top-right",
    ),
    Scene(
        "08-coach-reveal.png",
        "Reveal the coached outcome",
        "Compare the setup, trigger, R outcome, and grade after the decision.",
        3.8,
        "top-right",
    ),
    Scene(
        "09-journal.png",
        "Measure process over time",
        "Track grades, expectancy, cumulative R, and every reviewed decision.",
        4.5,
        "bottom-right",
    ),
    Scene(
        "10-decision-review.png",
        "Review execution—not just P&L",
        "MFE, MAE, available R, efficiency, notes, mistakes, and tags.",
        4.4,
        "top-right",
    ),
    Scene("outro.png", "", "", 3.8),
]


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def gradient_background() -> Image.Image:
    top = (14, 18, 34)
    bottom = (6, 9, 20)
    image = Image.new("RGB", (WIDTH, HEIGHT), top)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom, strict=True))
        draw.line((0, y, WIDTH, y), fill=color)
    for x in range(0, WIDTH, 96):
        draw.line((x, 0, x, HEIGHT), fill=(25, 31, 52), width=1)
    for y in range(0, HEIGHT, 96):
        draw.line((0, y, WIDTH, y), fill=(25, 31, 52), width=1)
    return image


def draw_market_trace(draw: ImageDraw.ImageDraw) -> None:
    prices = [660, 648, 654, 628, 635, 602, 610, 570, 582, 548, 526, 540, 505, 480,
              494, 456, 438, 452, 420, 390, 402, 370, 342, 356, 318, 294, 306, 280]
    points = []
    x0, step = 150, 59
    for i, value in enumerate(prices):
        x = x0 + i * step
        y = 260 + value
        points.append((x, y))
        bullish = i == 0 or prices[i] < prices[i - 1]
        color = (60, 210, 177) if bullish else (239, 83, 97)
        draw.line((x, y - 38, x, y + 38), fill=(*color, 130), width=3)
        draw.rounded_rectangle((x - 8, y - 19, x + 8, y + 19), radius=3, fill=color)
    draw.line(points, fill=(96, 117, 255), width=4, joint="curve")


def create_title_card(path: Path, outro: bool = False) -> None:
    image = gradient_background().convert("RGBA")
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((1180, -300, 2200, 720), fill=(76, 91, 255, 88))
    glow_draw.ellipse((-420, 600, 620, 1500), fill=(39, 195, 163, 40))
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(90)))
    draw = ImageDraw.Draw(image)
    draw_market_trace(draw)

    eyebrow = "DAY TRADING TRAINER"
    headline = "Plan. Practice. Review. Repeat." if outro else "Learn the market\nwithout risking the lesson."
    subtitle = (
        "A local-first training system built on actual market data."
        if outro
        else "Real historical replays. A live market coach. Decision-focused feedback."
    )
    draw.text((146, 142), eyebrow, font=font(FONT_BOLD, 24), fill=(122, 137, 255))
    draw.multiline_text(
        (140, 206), headline, font=font(FONT_BOLD, 76), fill=(245, 247, 255), spacing=6
    )
    draw.text((146, 410), subtitle, font=font(FONT_REGULAR, 31), fill=(183, 190, 210))

    chips = (
        ["LOCAL-FIRST", "ACTUAL MARKET DATA", "TRAINING SIMULATOR"]
        if outro
        else ["PLAN", "PRACTICE", "REVIEW"]
    )
    x = 146
    chip_font = font(FONT_SEMIBOLD, 22)
    for chip in chips:
        bounds = draw.textbbox((0, 0), chip, font=chip_font)
        width = bounds[2] - bounds[0] + 48
        draw.rounded_rectangle(
            (x, 482, x + width, 540), radius=29, fill=(30, 36, 60, 235), outline=(92, 109, 255)
        )
        draw.text((x + 24, 494), chip, font=chip_font, fill=(224, 228, 255))
        x += width + 16
    image.convert("RGB").save(path, quality=96)


def fit_screen(source: Image.Image) -> Image.Image:
    source = source.convert("RGB")
    if source.size == (WIDTH, HEIGHT):
        return source
    ratio = max(WIDTH / source.width, HEIGHT / source.height)
    size = (round(source.width * ratio), round(source.height * ratio))
    scaled = source.resize(size, Image.Resampling.LANCZOS)
    left = (scaled.width - WIDTH) // 2
    top = (scaled.height - HEIGHT) // 2
    return scaled.crop((left, top, left + WIDTH, top + HEIGHT))


def caption_box(image: Image.Image, title: str, subtitle: str, anchor: str) -> Image.Image:
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    box_w, box_h, margin = 1050, 158, 48
    x = margin if anchor.endswith("left") else WIDTH - margin - box_w
    y = margin if anchor.startswith("top") else HEIGHT - margin - box_h
    draw.rounded_rectangle(
        (x, y, x + box_w, y + box_h), radius=20, fill=(7, 10, 23, 226), outline=(91, 108, 255, 210), width=2
    )
    draw.rounded_rectangle((x + 18, y + 22, x + 25, y + box_h - 22), radius=3, fill=(91, 108, 255, 255))
    draw.text((x + 48, y + 25), title, font=font(FONT_BOLD, 39), fill=(247, 248, 255, 255))
    wrapped = "\n".join(textwrap.wrap(subtitle, width=78))
    draw.multiline_text(
        (x + 49, y + 88), wrapped, font=font(FONT_REGULAR, 25), fill=(194, 201, 221, 255), spacing=4
    )
    return Image.alpha_composite(canvas, overlay).convert("RGB")


def prepare_composites() -> list[Path]:
    COMPOSITED.mkdir(exist_ok=True)
    create_title_card(COMPOSITED / "intro.png")
    create_title_card(COMPOSITED / "outro.png", outro=True)
    prepared: list[Path] = []
    for scene in SCENES:
        destination = COMPOSITED / scene.source
        if scene.source not in ("intro.png", "outro.png"):
            source = fit_screen(Image.open(STILLS / scene.source))
            caption_box(source, scene.title, scene.subtitle, scene.anchor).save(destination, quality=96)
        prepared.append(destination)
    return prepared


def render(paths: list[Path]) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    SEGMENTS.mkdir(exist_ok=True)
    segment_paths: list[Path] = []
    for index, (scene, path) in enumerate(zip(SCENES, paths, strict=True)):
        frames = round(scene.duration * FPS)
        increment = 0.00022 if index % 2 == 0 else 0.00016
        fade = 0.38
        fade_out = max(scene.duration - fade, 0)
        filters = (
            f"scale={WIDTH}:{HEIGHT},"
            f"zoompan=z='min(zoom+{increment},1.035)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"fade=t=in:st=0:d={fade:.2f},"
            f"fade=t=out:st={fade_out:.2f}:d={fade:.2f},format=yuv420p"
        )
        segment = SEGMENTS / f"{index:02d}.mp4"
        segment_paths.append(segment)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(path),
                "-vf",
                filters,
                "-frames:v",
                str(frames),
                "-r",
                str(FPS),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(segment),
            ],
            check=True,
        )

    concat_file = SEGMENTS / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(OUTPUT),
        ],
        check=True,
    )


def main() -> None:
    paths = prepare_composites()
    render(paths)
    print(OUTPUT)


if __name__ == "__main__":
    main()
