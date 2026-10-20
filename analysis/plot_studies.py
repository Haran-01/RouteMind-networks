"""Export measured study figures with ReportLab charts and bundled Sharp rasterization."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from reportlab import Version
from reportlab.graphics import renderSVG
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String, Rect
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors

PALETTE = [colors.HexColor(value) for value in ["#1464a5", "#bd520b", "#16734b", "#843b91"]]
METRICS = [("realtime_p95_delay_ms", "Realtime p95 delay (ms)"),
           ("bulk_payload_goodput_mbps", "TCP payload goodput (Mbps)"),
           ("route_changes", "Controlled path changes")]
SCENARIOS = ["congestion", "burst", "combined"]


def csv_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def chart(drawing, x, y, width, height, series, title, ticks, labels=None, joined=False, ymax=None, yticks=None):
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = x, y, width, height
    plot.joinedLines = joined
    plot.data = [[(point[0], point[1]) for point in points] for points in series]
    xmin, xmax = min(ticks), max(ticks)
    margin = (xmax-xmin) * .06 if xmax > xmin else .2
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = xmin-margin, xmax+margin
    plot.xValueAxis.valueSteps = ticks
    plot.xValueAxis.labels.fontSize = 8
    if labels is not None:
        plot.xValueAxis.labelTextFormat = lambda value: labels[int(round(value))]
        plot.xValueAxis.labels.angle = 28
        plot.xValueAxis.labels.boxAnchor = "ne"
    else:
        plot.xValueAxis.labelTextFormat = lambda value: f"{value:g}"
    upper = max(point[3] if point[3] is not None else point[1] for points in series for point in points)
    lower = min(point[2] if point[2] is not None else point[1] for points in series for point in points)
    ymin = 0
    if ymax is None:
        step = 10 ** math.floor(math.log10(max(upper, .1))) / 2
        ymax = math.ceil(upper * 1.06 / step) * step
        ymin = min(0, math.floor(lower/step)*step)
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = ymin, ymax
    plot.yValueAxis.valueSteps = yticks or [ymin+(ymax-ymin) * index / 4 for index in range(5)]
    plot.yValueAxis.labels.fontSize = 8
    plot.yValueAxis.labelTextFormat = lambda value: f"{value:g}"
    plot.yValueAxis.visibleGrid = True
    plot.yValueAxis.gridStrokeColor = colors.HexColor("#dddddd")
    plot.yValueAxis.gridStrokeWidth = .3
    for index, points in enumerate(series):
        color = PALETTE[index]
        plot.lines[index].strokeColor = color
        plot.lines[index].strokeWidth = 1.2
        marker = makeMarker("FilledCircle")
        marker.fillColor = color
        marker.strokeColor = color
        marker.size = 4.5
        plot.lines[index].symbol = marker
        for xv, _, low, high in points:
            if low is None or high is None:
                continue
            xp = x + (xv-(xmin-margin)) / (xmax-xmin+2*margin) * width
            yp_low, yp_high = y + (low-ymin)/(ymax-ymin)*height, y + (high-ymin)/(ymax-ymin)*height
            drawing.add(Line(xp, yp_low, xp, yp_high, strokeColor=color, strokeWidth=.8))
            drawing.add(Line(xp-2, yp_low, xp+2, yp_low, strokeColor=color, strokeWidth=.8))
            drawing.add(Line(xp-2, yp_high, xp+2, yp_high, strokeColor=color, strokeWidth=.8))
    drawing.add(plot)
    drawing.add(String(x+width/2, y+height+16, title, fontSize=10, textAnchor="middle"))


def figure(title, legend):
    drawing = Drawing(960, 340)
    drawing.add(Rect(0, 0, 960, 340, fillColor=colors.white, strokeColor=None))
    drawing.add(String(480, 320, title, fontSize=14, textAnchor="middle"))
    for index, label in enumerate(legend):
        x = 170 + index * 215
        drawing.add(Line(x, 36, x+17, 36, strokeColor=PALETTE[index], strokeWidth=2))
        drawing.add(String(x+23, 32, label, fontSize=10))
    drawing.add(String(480, 12, "Points are run-level means; error bars: 95% Student t. Delay excludes lost packets; see delivery in reports.",
                       fontSize=8, textAnchor="middle"))
    return drawing


def point(rows, variant, scenario, metric, x, offset=0):
    row = next(row for row in rows if row["variant"] == variant and row["scenario"] == scenario and row["metric"] == metric)
    return (x+offset, float(row["mean"]), float(row["ci95_low"]) if row["ci95_low"] else None,
            float(row["ci95_high"]) if row["ci95_high"] else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=["all", "ablations", "sensitivity", "topology", "rank"], default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = Path(sys.executable).resolve().parent.parent
    node, sharp = bundle / "node/bin/node.exe", bundle / "node/node_modules/sharp"
    if not node.exists() or not sharp.exists():
        raise SystemExit("PNG rendering requires the bundled Node/Sharp runtime; SVG chart source uses ReportLab")
    generated = []

    def save(name, drawing, inputs):
        svg, png = output / f"{name}.svg", output / f"{name}.png"
        renderSVG.drawToFile(drawing, str(svg))
        code = "const sharp=require(process.argv[1]); sharp(process.argv[2],{density:144}).png().toFile(process.argv[3]).catch(e=>{console.error(e);process.exit(1)});"
        subprocess.run([str(node), "-e", code, str(sharp), str(svg), str(png)], check=True)
        generated.append({"name": name, "svg": str(svg), "png": str(png),
                          "input_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
                          "svg_sha256": hashlib.sha256(svg.read_bytes()).hexdigest(),
                          "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest()})
        print("Figure:", png)

    if args.only in {"all", "ablations"}:
        root = args.results / "phase2-ablations"
        rows = csv_rows(root / "comparison.csv")
        drawing = figure("Independent mechanism removals - five paired realizations per scenario", SCENARIOS)
        variants = ["default", "no-smoothing", "no-hysteresis", "no-dwell", "shared-objective"]
        for panel, (metric, title) in enumerate(METRICS):
            series = [[point(rows, variant, scenario, metric, index, (sindex-1)*.10)
                       for index, variant in enumerate(variants)] for sindex, scenario in enumerate(SCENARIOS)]
            chart(drawing, 45+320*panel, 100, 255, 180, series, title, list(range(5)),
                  ["Default", "No EWMA", "No hyst.", "No dwell", "Shared"])
        save("ablations", drawing, [root/"manifest.json", root/"comparison.csv"])

    if args.only in {"all", "sensitivity"}:
        root = args.results / "phase3-heldout"
        rows = csv_rows(root / "comparison.csv")
        for factor, ids, values, label in [
                ("alpha", ["alpha-01", "default", "alpha-1"], [.1, .3, 1], "EWMA alpha"),
                ("dwell", ["dwell-0", "default", "dwell-3"], [0, 1.5, 3], "Minimum dwell (s)"),
                ("threshold", ["threshold-0", "default", "threshold-025"], [0, .12, .25], "Improvement threshold")]:
            drawing = figure(f"Held-out sensitivity: {label} - n=5 per scenario", SCENARIOS)
            for panel, (metric, title) in enumerate(METRICS):
                series = [[point(rows, variant, scenario, metric, value) for variant, value in zip(ids, values)]
                          for scenario in SCENARIOS]
                x = 45+320*panel
                chart(drawing, x, 100, 255, 180, series, title, values, joined=True)
                drawing.add(String(x+127, 68, label, fontSize=10, textAnchor="middle"))
            save(f"sensitivity-{factor}", drawing, [root/"manifest.json", root/"comparison.csv"])

    if args.only in {"all", "topology"}:
        root = args.results / "phase4-topologies"
        rows = csv_rows(root / "comparison.csv")
        topologies = ["parallel", "extended", "detour"]
        modes = ["static", "adaptive", "stable", "class-aware"]
        for scenario in ["congestion", "burst"]:
            drawing = figure(f"Topology check: {scenario} - n=3 paired realizations per topology/mode", topologies)
            for panel, (metric, title) in enumerate(METRICS):
                series = [[point(rows, f"{topology}-{mode}", scenario, metric, index, (tindex-1)*.08)
                           for index, mode in enumerate(modes)] for tindex, topology in enumerate(topologies)]
                chart(drawing, 45+320*panel, 100, 255, 180, series, title, list(range(4)),
                      ["Static", "Adaptive", "Stable", "Class-aware"])
            save(f"topologies-{scenario}", drawing, [root/"manifest.json", root/"comparison.csv"])

    if args.only in {"all", "rank"}:
        root = args.results / "phase4-rank"
        manifest = json.loads((root / "manifest.json").read_text())
        assert manifest["status"] == "complete"
        drawing = Drawing(960, 340)
        drawing.add(Rect(0, 0, 960, 340, fillColor=colors.white, strokeColor=None))
        drawing.add(String(480, 320, "Fixed-rank boundary: a physical detour exists - one deterministic trial per condition", fontSize=14, textAnchor="middle"))
        inputs = [root/"manifest.json"]
        for panel, mode in enumerate(["adaptive", "class-aware"]):
            series = []
            for prefix in ["constrained", "unconstrained"]:
                child = root / f"{prefix}-{mode}"
                matrix = json.loads((child / "manifest.json").read_text())
                case = child / matrix["completed"][0]
                offers = csv_rows(case / "udp-offers.csv")
                received = {row["sequence"] for row in csv_rows(case / "realtime-packets.csv")}
                points = []
                for second in range(1, 23):
                    cohort = [offer for offer in offers if second <= float(offer["time"]) < second+1]
                    ratio = sum(offer["sequence"] in received for offer in cohort)/len(cohort)
                    points.append((second+.5, ratio, None, None))
                series.append(points)
                inputs += [case/"udp-offers.csv", case/"realtime-packets.csv"]
            x = 65+480*panel
            chart(drawing, x, 100, 350, 180, series, f"{mode}: delivery by 1-second transmit cohort", [2, 6, 10, 14, 18, 22], joined=True, ymax=1.04, yticks=[0, .25, .5, .75, 1])
            drawing.add(String(x+175, 70, "Transmit time (s)", fontSize=9, textAnchor="middle"))
            for stamp, label in [(14.07, "link down"), (20.11, "link up")]:
                xp = x+(stamp-.8)/22.4*350
                drawing.add(Line(xp, 100, xp, 280, strokeColor=colors.grey, strokeWidth=.8, strokeDashArray=[3, 3]))
                drawing.add(String(xp+3, 265, label, fontSize=8))
        for index, label in enumerate(["Fixed-rank enabled", "Unconstrained"]):
            x = 265+300*index
            drawing.add(Line(x, 42, x+20, 42, strokeColor=PALETTE[index], strokeWidth=2))
            drawing.add(String(x+27, 39, label, fontSize=10))
        drawing.add(String(480, 15, "Delivery includes source rejections. Each condition has the same 2,199 offers. No confidence interval for one deterministic trial.", fontSize=8, textAnchor="middle"))
        save("rank-boundary", drawing, inputs)

    provenance = {"plotter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "chart_library": f"ReportLab {Version}", "renderer": "bundled Node/Sharp", "figures": generated}
    (output / "manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
