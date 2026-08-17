# Prompt comparison

All six runs returned valid JSON and followed the requested structure. The main differences were in confidence, handling of missing evidence, and rollback advice.

| Approach | What worked well | Main problems | Overall result |
|---|---|---|---|
| Zero-shot | Listed several possible causes and acknowledged that the root cause was not confirmed. | Both runs favored the deployment with medium confidence. They claimed failures started immediately after deployment, although only the alert time was supplied. They also suggested that a successful rollback would confirm the cause, which is too strong. | Well structured, but too quick to connect the deployment to the failures. |
| One-shot | Both runs used low confidence, selected no leading cause, separated competing explanations, and suggested comparing old and new versions before rollback. | The previous credential incident was omitted from the known facts. A few phrases still implied timing that was not fully established. | The most cautious and consistent approach. |
| Few-shot | Considered deployment, database, and payment-provider explanations and included rollback risks and preconditions. | The two runs were less consistent: one selected no leading cause, while the other favored the deployment. Some claims, such as failures starting immediately after deployment, were unsupported. | Broader analysis, but the extra examples did not remove unsupported conclusions. |

## Key findings

- Valid JSON made the responses easier to compare, but did not guarantee that every claim was supported.
- The one-shot approach handled uncertainty best in these runs.
- The zero-shot runs were strongly influenced by the timing of the deployment.
- The few-shot runs covered more alternatives, but disagreed about whether the deployment was the leading explanation.
- A rollback result would strengthen or weaken the deployment hypothesis; it would not prove the root cause by itself.

Overall, the examples improved structure and caution, but consistency did not automatically make the conclusions more accurate.
