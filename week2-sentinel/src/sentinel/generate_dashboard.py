"""Generate a FICTIONAL incident dashboard image for INC-104.

Run it:
    uv run python -m sentinel.generate_dashboard

The image is designed to overlap PARTLY with the text incident and add some
detail that exists ONLY in the image, so the multimodal exercise can test which
observations Claude draws from text vs image, and whether it invents anything.

  Shared with the text : error-rate spike ~10:04, deploy dep-1842 at 10:01,
                         database latency rising, payment-provider errors.
  Image-only detail    : the error-type BREAKDOWN (DB timeouts dominate), and
                         concrete latency numbers. None of this is in inc-104.md.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402

from .config import INCIDENTS_DIR  # noqa: E402

OUT = INCIDENTS_DIR / "inc-104-dashboard.png"


def build() -> Path:
    # X axis: minutes 09:55 .. 10:15 (UTC)
    mins = list(range(55, 76))  # 55..75 -> 09:55 .. 10:15
    labels = [f"{'09' if m < 60 else '10'}:{m % 60:02d}" for m in mins]

    # Error rate (%): flat ~0.4 until 10:03, spike to ~9 by 10:05, plateau.
    err = []
    for m in mins:
        if m < 63:
            err.append(0.4)
        elif m < 65:
            err.append(0.4 + (m - 62) * 4.3)
        else:
            err.append(9.0)

    # DB p99 latency (ms): rises around 10:01-10:04.
    lat = []
    for m in mins:
        if m < 61:
            lat.append(120)
        elif m < 64:
            lat.append(120 + (m - 60) * 240)
        else:
            lat.append(850)

    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(9, 9), gridspec_kw={"height_ratios": [3, 2, 2]}
    )
    fig.suptitle("checkout-api — INC-104 dashboard (FICTIONAL)", fontsize=14, fontweight="bold")

    # Panel 1: error rate with deploy + alert markers
    ax1.plot(range(len(mins)), err, color="#d6336c", linewidth=2, label="checkout error rate %")
    ax1.axvline(mins.index(61), color="#495057", linestyle="--", label="deploy dep-1842 (10:01)")
    ax1.axvline(mins.index(64), color="#e8590c", linestyle=":", label="alert fired (10:04)")
    ax1.set_ylabel("error rate (%)")
    ax1.set_title("Checkout error rate: 0.4% → 9%")
    ax1.legend(fontsize=8, loc="upper left")
    ax1.grid(alpha=0.3)

    # Panel 2: DB p99 latency (image-only numbers)
    ax2.plot(range(len(mins)), lat, color="#1c7ed6", linewidth=2)
    ax2.axvline(mins.index(61), color="#495057", linestyle="--")
    ax2.set_ylabel("DB p99 (ms)")
    ax2.set_title("Database p99 latency: 120ms → 850ms  [image-only detail]")
    ax2.grid(alpha=0.3)

    # Panel 3: error-type breakdown at 10:05 (IMAGE-ONLY — not in the text)
    types = ["DB timeout", "Provider 5xx", "Validation", "Other"]
    share = [62, 27, 4, 7]
    colors = ["#1c7ed6", "#f08c00", "#adb5bd", "#ced4da"]
    ax3.barh(types, share, color=colors)
    for i, v in enumerate(share):
        ax3.text(v + 1, i, f"{v}%", va="center", fontsize=9)
    ax3.set_xlim(0, 75)
    ax3.set_xlabel("share of failed checkouts (%)")
    ax3.set_title("Failure breakdown at 10:05  [image-only detail]")

    for ax in (ax1, ax2):
        ax.set_xticks(range(0, len(mins), 2))
        ax.set_xticklabels(labels[::2], rotation=45, fontsize=7)

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=110)
    plt.close(fig)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({path.stat().st_size} bytes)")
