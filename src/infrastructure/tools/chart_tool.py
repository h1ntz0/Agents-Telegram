"""Chart generation tool supporting QuickChart URL rendering and ASCII/text representations."""

import json
import urllib.parse
from typing import Any, Dict, List, Union
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult

PALETTE = [
    "rgba(54, 162, 235, 0.8)",
    "rgba(255, 99, 132, 0.8)",
    "rgba(255, 206, 86, 0.8)",
    "rgba(75, 192, 192, 0.8)",
    "rgba(153, 102, 255, 0.8)",
    "rgba(255, 159, 64, 0.8)",
    "rgba(46, 204, 113, 0.8)",
    "rgba(231, 76, 60, 0.8)",
]


def render_ascii_bar_chart(labels: List[str], values: List[float], title: str = "", max_bar_width: int = 20) -> str:
    """Render a text-based ASCII bar chart with formatted values and proportions."""
    if not labels or not values:
        return "(empty dataset)"

    pairs = list(zip(labels, values))
    max_val = max(abs(v) for v in values) if values else 1.0
    if max_val == 0:
        max_val = 1.0
    max_label_len = max(len(str(lbl)) for lbl in labels)

    lines: List[str] = []
    if title:
        lines.append(f"📊 {title}")
        lines.append("-" * max(len(title) + 4, max_label_len + max_bar_width + 16))

    for lbl, val in pairs:
        bar_len = int(round((abs(val) / max_val) * max_bar_width))
        bar_str = "█" * max(1 if val > 0 else 0, bar_len)
        val_str = f"{val:g}"
        lines.append(f"{str(lbl):<{max_label_len}} │ {bar_str:<{max_bar_width}} ({val_str})")

    return "\n".join(lines)


def build_quickchart_url(
    labels: List[str],
    values: List[float],
    chart_type: str = "bar",
    title: str = "",
    dataset_label: str = "Values",
    width: int = 500,
    height: int = 300,
) -> str:
    """Construct a QuickChart URL with Chart.js payload."""
    clean_type = chart_type.lower().strip()
    is_multi_color = clean_type in ("pie", "doughnut", "polararea")
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(values))] if is_multi_color else PALETTE[0]

    chart_config: Dict[str, Any] = {
        "type": clean_type,
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": dataset_label,
                    "data": values,
                    "backgroundColor": colors,
                    "borderColor": "rgba(255, 255, 255, 0.8)" if is_multi_color else "rgba(54, 162, 235, 1)",
                    "borderWidth": 1,
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"display": True}
            }
        }
    }

    if title:
        chart_config["options"]["title"] = {"display": True, "text": title}

    config_str = json.dumps(chart_config, separators=(",", ":"))
    encoded = urllib.parse.quote(config_str)
    return f"https://quickchart.io/chart?c={encoded}&w={width}&h={height}&bkg=white"


class ChartTool(BaseTool):
    """Generates QuickChart visual charts and ASCII text charts."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="generate_chart",
            description="Generate visual charts (bar, line, pie, doughnut, radar) with QuickChart URL and ASCII text representation.",
            parameters={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "doughnut", "radar", "polarArea"],
                        "description": "The type of chart to generate (default: 'bar')."
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title or heading."
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of category labels for X-axis / slices."
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Numerical data points corresponding to labels."
                    },
                    "dataset_label": {
                        "type": "string",
                        "description": "Label for the series (default: 'Values')."
                    }
                },
                "required": ["labels", "values"]
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    def generate_quickchart_url(
        self,
        labels: List[str],
        values: List[float],
        chart_type: str = "bar",
        title: str = "",
        dataset_label: str = "Values",
        width: int = 500,
        height: int = 300,
    ) -> str:
        """Helper method for generating QuickChart URL."""
        return build_quickchart_url(
            labels=labels,
            values=values,
            chart_type=chart_type,
            title=title,
            dataset_label=dataset_label,
            width=width,
            height=height
        )

    def render_ascii_bars(
        self,
        labels: List[str],
        values: List[float],
        title: str = "",
        max_width: int = 20,
    ) -> str:
        """Helper method for generating ASCII bar chart."""
        return render_ascii_bar_chart(
            labels=labels,
            values=values,
            title=title,
            max_bar_width=max_width
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        chart_type = str(arguments.get("chart_type", "bar")).lower().strip()
        title = str(arguments.get("title", "")).strip()
        dataset_label = str(arguments.get("dataset_label", "Values")).strip()

        raw_labels = arguments.get("labels", [])
        raw_values = arguments.get("values", [])

        # Parse string inputs if passed as comma-separated
        if isinstance(raw_labels, str):
            labels = [s.strip() for s in raw_labels.split(",") if s.strip()]
        elif isinstance(raw_labels, list):
            labels = [str(x).strip() for x in raw_labels]
        else:
            labels = []

        if isinstance(raw_values, str):
            val_strs = [s.strip() for s in raw_values.split(",") if s.strip()]
            values: List[float] = []
            for vs in val_strs:
                try:
                    values.append(float(vs))
                except (ValueError, TypeError):
                    return ToolResult(content="Error: Values must be numbers.", is_error=True)
        elif isinstance(raw_values, list):
            values = []
            for v in raw_values:
                try:
                    if isinstance(v, (int, float)):
                        values.append(float(v))
                    elif isinstance(v, str) and v.replace(".", "", 1).replace("-", "", 1).isdigit():
                        values.append(float(v))
                    else:
                        return ToolResult(content="Error: Values must be numbers.", is_error=True)
                except (ValueError, TypeError):
                    return ToolResult(content="Error: Values must be numbers.", is_error=True)
        else:
            values = []

        if not labels or not values:
            return ToolResult(content="Error: 'labels' and 'values' must contain non-empty data arrays.", is_error=True)

        if len(labels) != len(values):
            return ToolResult(content="Error: Labels count does not match values count.", is_error=True)

        quickchart_url = self.generate_quickchart_url(
            labels=labels,
            values=values,
            chart_type=chart_type,
            title=title,
            dataset_label=dataset_label
        )

        ascii_chart = self.render_ascii_bars(
            labels=labels,
            values=values,
            title=title,
            max_width=20
        )

        header = f"📊 {title}\n" if title else ""
        content = (
            f"{header}"
            f"🖼️ Visual Chart (QuickChart):\n{quickchart_url}\n\n"
            f"```\n{ascii_chart}\n```"
        )

        return ToolResult(
            content=content,
            metadata={
                "chart_type": chart_type,
                "url": quickchart_url,
                "labels": labels,
                "values": values
            }
        )
