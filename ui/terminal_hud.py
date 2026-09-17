from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

console = Console()

# Confidence colour bands
def _conf_style(conf: float) -> str:
    if conf >= 0.80:
        return "bold green"
    elif conf >= 0.55:
        return "bold yellow"
    return "bold red"


def create_hud_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=4),
    )
    layout["main"].split_row(
        Layout(name="state",    ratio=1),
        Layout(name="decision", ratio=1),
    )
    return layout


def update_hud(
    layout: Layout,
    state_yaml: str,
    decision: dict,
    latency_ms: float,
    actions: list,
    standing_orders: str,
):
    # ── Header ──────────────────────────────────────────────────────────────
    layout["header"].update(
        Panel(
            Text("⚡ ViZDoom × Jev SystemOne  |  5 Hz Autonomous Agent", justify="center", style="bold cyan"),
        )
    )

    # ── Situation Report ────────────────────────────────────────────────────
    layout["state"].update(
        Panel(state_yaml, title="[blue]Situation Report[/blue]", border_style="blue")
    )

    # ── Decision DAG ────────────────────────────────────────────────────────
    dt = Text()
    if decision:
        rows = [
            ("macro_goal", "🎯 Macro Goal"),
            ("target",     "👾 Target"),
            ("movement",   "🏃 Movement"),
            ("rotation",   "🔄 Rotation"),
            ("jump",       "⬆  Jump"),
            ("firing",     "🔫 Firing"),
        ]
        for key, label in rows:
            entry = decision.get(key, {})
            val  = entry.get("value", "—")
            conf = float(entry.get("confidence", 0.0))
            dt.append(f"  {label}: ", style="white")
            dt.append(f"{val}", style=_conf_style(conf))
            dt.append(f"  ({conf:.0%})\n", style="dim")
    else:
        dt.append("  Waiting for API response…", style="italic dim red")

    # Actuation row
    labels = ["ATK", "FWD", "BCK", "←", "→", "⟵", "⟶", "JMP"]
    dt.append("\n  Actuation: ", style="dim")
    for i, (lbl, val) in enumerate(zip(labels, actions or [0]*8)):
        style = "bold yellow" if val else "dim"
        dt.append(f"[{lbl}]" if val else f" {lbl} ", style=style)

    # Latency
    lat_style = "bold green" if latency_ms <= 150 else "bold red"
    dt.append(f"\n\n  API Latency: ", style="dim")
    dt.append(f"{latency_ms:.1f} ms", style=lat_style)

    layout["decision"].update(
        Panel(dt, title="[magenta]Jev Decision DAG[/magenta]", border_style="magenta")
    )

    # ── Footer: Standing Orders ─────────────────────────────────────────────
    layout["footer"].update(
        Panel(
            Text(f"ORDERS: {standing_orders}\n(Type new orders + Enter to update)", style="dim"),
            title="[white]Command Hook[/white]",
            border_style="white",
        )
    )
