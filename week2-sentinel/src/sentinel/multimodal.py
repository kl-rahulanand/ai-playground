"""Section 5 — multimodal input (text incident + dashboard image).

Run it:
    uv run python -m sentinel.generate_dashboard   # once, to create the PNG
    uv run python -m sentinel.multimodal

We send the incident TEXT and the dashboard IMAGE in the same user turn and ask
Claude to attribute each observation to its source. The curriculum requires us to
record:
  * which observations came from the text,
  * which came from the image,
  * which conclusions were inferred,
  * whether any unsupported information was introduced.

To make that checkable, we use structured output whose schema forces the model to
separate observations by source. Then the APPLICATION evaluates the result — image
interpretation is still model output and must be verified, not trusted.
"""

from __future__ import annotations

import base64
import json

from pydantic import BaseModel, Field

from .client import build_client, map_api_exception
from .config import INCIDENTS_DIR, load_settings, read_incident
from .contract import _strictify
from .failures import SentinelFailure

DASHBOARD = INCIDENTS_DIR / "inc-104-dashboard.png"


class SourcedObservations(BaseModel):
    text_observations: list[str] = Field(
        description="Observations drawn ONLY from the incident text."
    )
    image_observations: list[str] = Field(
        description="Observations drawn ONLY from the dashboard image."
    )
    inferred_conclusions: list[str] = Field(
        description="Conclusions reasoned from text+image, not directly stated in either."
    )
    uncertainty: str = Field(description="What remains unresolved across both inputs.")


def _schema() -> dict:
    s = SourcedObservations.model_json_schema()
    _strictify(s)
    return s


PROMPT = (
    "You are given an incident description (text) and a monitoring dashboard "
    "(image) for the same incident, INC-104. Report your observations, keeping "
    "strictly separate: what comes only from the text, what comes only from the "
    "image, and what you infer from combining them. Do not state anything not "
    "present in one of the two sources. If a number or category is only in the "
    "image, put it under image_observations."
)


def run():
    settings = load_settings()
    client = build_client(settings)
    incident_text = read_incident("inc-104")

    if not DASHBOARD.exists():
        raise SystemExit("Run `uv run python -m sentinel.generate_dashboard` first.")

    image_b64 = base64.standard_b64encode(DASHBOARD.read_bytes()).decode("utf-8")

    try:
        resp = client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": f"{PROMPT}\n\nIncident text:\n\n{incident_text}"},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": _schema()}},
        )
    except Exception as exc:
        raise map_api_exception(exc) from exc

    text = next((b.text for b in resp.content if b.type == "text"), "")
    obs = SourcedObservations.model_validate_json(text)
    return obs, resp.usage


# The ground truth we baked into the image (for the application's own evaluation).
IMAGE_ONLY_FACTS = ["120", "850", "62", "27", "p99", "breakdown", "db timeout"]
TEXT_FACTS = ["0.4", "9%", "dep-1842", "10:01", "10:04", "provider", "credential"]


def evaluate(obs: SourcedObservations) -> None:
    """Application-side evaluation: did the model attribute sources plausibly, and
    did it introduce anything unsupported? Heuristic, printed for the record."""
    joined_img = " ".join(obs.image_observations).lower()
    joined_txt = " ".join(obs.text_observations).lower()

    print("\n--- application evaluation ---")
    hit_img = [k for k in IMAGE_ONLY_FACTS if k in joined_img]
    print(f"image-only facts surfaced under image_observations: {hit_img}")

    # A leak: image-only numbers claimed as text observations = misattribution.
    leaks = [k for k in ("120", "850", "62%", "27%") if k in joined_txt]
    print(f"possible misattributions (image numbers under text): {leaks or 'none'}")

    # Credential mention should NOT appear as an image observation (it's text-only).
    if "credential" in joined_img:
        print("WARNING: 'credential' (text-only) attributed to the image.")
    else:
        print("no text-only 'credential' leak into image observations.")


def main() -> int:
    settings = load_settings()
    print(f"→ model={settings.model}  image={DASHBOARD.name}\n")
    try:
        obs, usage = run()
    except SentinelFailure as f:
        print("FAILED:\n", f)
        return 1

    print(f"tokens in/out = {usage.input_tokens}/{usage.output_tokens}\n")
    print("TEXT observations:")
    for o in obs.text_observations:
        print(f"  - {o}")
    print("\nIMAGE observations:")
    for o in obs.image_observations:
        print(f"  - {o}")
    print("\nINFERRED conclusions:")
    for o in obs.inferred_conclusions:
        print(f"  - {o}")
    print(f"\nUNCERTAINTY: {obs.uncertainty}")

    evaluate(obs)

    # Save for the deliverable.
    out = INCIDENTS_DIR.parent / "results" / "multimodal-observations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obs.model_dump(), indent=2), encoding="utf-8")
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
