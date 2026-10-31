"""Render the theoretical savings model as a normal grouped bar chart."""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


WIDTH = 1600
HEIGHT = 900
COLORS = {"background": "#F7F9FA", "panel": "#FFFFFF", "ink": "#15252C", "muted": "#61727A", "grid": "#E4EAEC", "line": "#D5E0E3", "baseline": "#6B45A8", "hybrid": "#078C86"}


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value: float, suffix: str = "") -> str:
    if abs(value) >= 1_000_000_000:
        text = f"{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1000:
        text = f"{value / 1000:.1f}k"
    elif abs(value) < 100:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{value:,.0f}"
    return f"{text}{suffix}"


def _text(x: float, y: float, value: str, size: int, fill: str = "ink", weight: int = 400, anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" fill="{COLORS[fill]}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{_escape(value)}</text>'


def _rect(x: float, y: float, width: float, height: float, fill: str, radius: int = 0, stroke: str | None = None) -> str:
    stroke_markup = f' stroke="{COLORS[stroke]}" stroke-width="1"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{COLORS[fill]}"{stroke_markup}/>'


def _panel(x: float, y: float, width: float, height: float, title: str, unit: str, before: float, after: float, formatter: str = "number") -> str:
    plot_x, plot_y, plot_w, plot_h = x + 60, y + 62, width - 88, height - 112
    maximum = max(before, after, 1.0) * 1.15
    chart = [_rect(x, y, width, height, "panel", 14, "line"), _text(x + 22, y + 32, title, 19, "ink", 700), _text(x + width - 22, y + 31, unit, 12, "muted", 500, "end")]
    for tick in range(0, 5):
        value = maximum * tick / 4
        gy = plot_y + plot_h - plot_h * tick / 4
        chart.append(f'<line x1="{plot_x}" y1="{gy:.2f}" x2="{plot_x + plot_w}" y2="{gy:.2f}" stroke="{COLORS["grid"]}" stroke-width="1"/>')
        chart.append(_text(plot_x - 10, gy + 4, _fmt(value), 11, "muted", 400, "end"))
    chart.append(f'<line x1="{plot_x}" y1="{plot_y}" x2="{plot_x}" y2="{plot_y + plot_h}" stroke="{COLORS["line"]}" stroke-width="1"/>')
    chart.append(f'<line x1="{plot_x}" y1="{plot_y + plot_h}" x2="{plot_x + plot_w}" y2="{plot_y + plot_h}" stroke="{COLORS["line"]}" stroke-width="1"/>')
    bar_width = 88
    for center, value, color, label in ((plot_x + plot_w * .35, before, "baseline", "AI only"), (plot_x + plot_w * .68, after, "hybrid", "This app")):
        bar_h = plot_h * value / maximum
        chart.append(_rect(center - bar_width / 2, plot_y + plot_h - bar_h, bar_width, bar_h, color, 5))
        chart.append(_text(center, plot_y + plot_h - bar_h - 9, _fmt(value), 14, color, 700, "middle"))
        chart.append(_text(center, y + height - 19, label, 12, "muted", 500, "middle"))
    return "".join(chart)


def _browser_executable() -> str | None:
    candidates = [shutil.which("chrome"), shutil.which("msedge"), os.environ.get("CHROME_PATH"), r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)


def _render_png(svg_path: Path, png_path: Path) -> None:
    browser = _browser_executable()
    if browser is None:
        raise ValueError("PNG export needs Chrome or Edge. Set CHROME_PATH or export the SVG directly.")
    with tempfile.TemporaryDirectory(prefix="theoretical-savings-") as profile:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={profile}", "--hide-scrollbars", f"--window-size={WIDTH},{HEIGHT}", f"--screenshot={png_path.resolve()}", svg_path.resolve().as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render_svg(report: dict[str, Any]) -> str:
    params = report["parameters"]
    before = report["annual"]["baseline"]
    after = report["annual"]["hybrid"]
    saved_calls = report["savings"]["ai_calls"]["percent"]
    panels = [
        ("AI calls", "annual calls", before["ai_calls"], after["ai_calls"]),
        ("Total tokens", "annual tokens", before["total_tokens"], after["total_tokens"]),
        ("Mean request latency", "milliseconds", before["mean_latency_ms"], after["mean_latency_ms"]),
        ("Compute time", "CPU + GPU hours", before["compute_hours"], after["compute_hours"]),
        ("Electricity cost", "USD", before["electricity_cost_usd"], after["electricity_cost_usd"]),
        ("Carbon footprint", "kg CO2e", before["carbon_kg"], after["carbon_kg"]),
    ]
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        '<title id="title">Theoretical annual savings from routing math locally</title>',
        '<desc id="desc">Normal grouped bar charts compare an AI-only scenario with this app hybrid scenario.</desc>',
        _rect(0, 0, WIDTH, HEIGHT, "background"),
        _text(64, 58, "THEORETICAL SCALE MODEL", 15, "hybrid", 700),
        _text(64, 104, "What this app could save at scale", 38, "ink", 700),
        _text(64, 133, f"Annual projection at {params['requests_per_month']:,} requests per month", 17, "muted"),
        f'<circle cx="1210" cy="62" r="7" fill="{COLORS["baseline"]}"/>' + _text(1226, 67, "AI only", 14, "muted", 500),
        f'<circle cx="1310" cy="62" r="7" fill="{COLORS["hybrid"]}"/>' + _text(1326, 67, "This app", 14, "muted", 500),
        _rect(64, 158, 1472, 38, "panel", 9, "line"),
        _text(84, 183, f"Projected AI call reduction {saved_calls:.1%}  •  Solver coverage {params['solver_coverage']:.0%}  •  Hybrid success rate {report['annual']['hybrid']['success_rate']:.2%}", 14, "muted", 600),
    ]
    positions = [(64, 220), (560, 220), (1056, 220), (64, 515), (560, 515), (1056, 515)]
    for (title, unit, before_value, after_value), (x, y) in zip(panels, positions):
        svg.append(_panel(x, y, 480, 250, title, unit, before_value, after_value))
    svg.extend([
        _text(64, 806, f"Energy: {_fmt(before['energy_kwh'])} kWh → {_fmt(after['energy_kwh'])} kWh  •  Compute: {_fmt(before['compute_hours'])} h → {_fmt(after['compute_hours'])} h", 14, "muted", 500),
        _text(1536, 806, "Illustrative, not measured provider data", 14, "muted", 500, "end"),
        _text(64, 844, "Electricity uses 300 W accelerator power, 65 W solver host power, 0.12 USD/kWh, and 400 g CO2e/kWh. Change the parameters before presenting the result.", 13, "muted"),
        "</svg>",
    ])
    return "".join(svg)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render theoretical benchmark savings as grouped bar charts")
    parser.add_argument("report", default="docs/evidence/theoretical-savings.json", nargs="?")
    parser.add_argument("--output", default="docs/evidence/theoretical-savings.svg")
    parser.add_argument("--png", help="optional presentation PNG path; requires Chrome or Edge")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_svg(report), encoding="utf-8")
        if args.png:
            png = Path(args.png)
            png.parent.mkdir(parents=True, exist_ok=True)
            _render_png(output, png)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"theoretical graph failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
