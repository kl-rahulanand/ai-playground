# Section 5 — Multimodal input (text + dashboard image)

We sent the INC-104 text and a fictional dashboard image
(`incidents/inc-104-dashboard.png`) in a single user turn, using an `image`
content block (base64 PNG) followed by a `text` block. Structured output forced
the model to separate observations by source.

## The image was designed as a test

| In the text | Only in the image |
|---|---|
| error 0.4%→9%, deploy dep-1842 @10:01, DB latency rising, provider errors, prior credential incident | DB p99 **120ms→850ms**, failure **breakdown**: DB timeout 62%, Provider 5xx 27%, Validation 4%, Other 7% |

If the model is faithful, the image-only numbers must appear under
*image_observations* and never be invented or misattributed.

## Recorded result (from the live run)

- **From the text:** the six brief facts, the director's question, and the
  "initial reports, not confirmed" caveat — all correct.
- **From the image:** the deploy/alert markers, the DB p99 120→850ms figure, and
  the full failure breakdown (62% / 27% / 4% / 7%). All the image-only detail was
  attributed to the image.
- **Inferred (not stated in either):** a temporal chain deploy→latency→errors;
  that DB timeouts are the dominant failure mode; that provider 5xx may be a
  secondary effect of DB timeouts. All hedged ("suggesting", "may").
- **Unsupported information introduced:** none detected. The application check
  found all image-only facts under image_observations, no image numbers
  misattributed to the text, and the text-only "credential" detail did not leak
  into image observations.

## The point

Image interpretation is **still model-generated output**. The model read the
chart correctly this time, but the application verified it rather than trusting
it: `multimodal.evaluate()` cross-checks the model's source attribution against
the facts we know are in each input. A dashboard reading that invented a number,
or blamed the provider because the bar "looked bigger", would be caught the same
way we catch an unsupported textual conclusion.

Note the token shape: the image cost ~1930 input tokens for a small PNG — images
are not free, and a larger dashboard would cost more.

## Run it

```bash
uv run python -m sentinel.generate_dashboard   # (re)create the PNG
uv run python -m sentinel.multimodal           # sourced observations + evaluation
```
Output is saved to `results/multimodal-observations.json`.
