# Parameter comparison

The same zero-shot prompt and incident were used for each test. Frequency penalty was not available in the interface and was therefore not tested.

| Test | Temperature | Top-p | Min-p | What changed |
|---|---:|---:|---:|---|
| Baseline | 0.2 | 0.9 | 0.05 | The two baseline runs favored the deployment with medium confidence and recommended a conditional rollback. |
| Higher temperature | 0.8 | 0.9 | 0.05 | The response remained valid JSON but became more speculative. It connected the deployment to database latency and mentioned an unsupported high-demand period. |
| Lower top-p | 0.2 | 0.5 | 0.05 | The response was direct and still favored the deployment with medium confidence. It preserved the main facts but continued to rely heavily on timing. |
| Higher min-p | 0.2 | 0.5 | 0.15 | No leading cause was selected, and four hypotheses were listed. However, top-p was also changed from the baseline, so this result cannot be attributed to min-p alone. |

## Findings

- Every run returned valid JSON, but unsupported statements still appeared.
- Higher temperature produced more speculative connections in this sample.
- Lower top-p did not prevent the response from favoring the deployment.
- The min-p run must be treated as a mixed-parameter test because top-p was not reset to `0.9`.
- Frequency penalty is recorded as **not supported**.
- Only one run was collected for each alternative setting, so the results show examples rather than a reliable pattern.

The parameter changes affected wording, confidence, and the number of hypotheses, but none established the root cause.
