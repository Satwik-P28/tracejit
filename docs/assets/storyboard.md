# 10–20 second storyboard

Record this on Linux x86_64 with `./scripts/demo.sh`, or with the same commands by hand. Use the synthetic transform. Say on screen that it is synthetic. Cut the typing. Keep the four beats.

| Time | Picture | On-screen text | Why it is not ordinary memoization |
| --- | --- | --- | --- |
| 0–2s | Direct `./transform`. Show the hex line and a wall time around a few hundred milliseconds. | Normal execution | The program is unchanged. Nobody listed its inputs. |
| 2–5s | `tracejit run -- ./transform`. Terminal shows `cache MISS`, `classified GUARDED`. | TraceJIT observes the run | The first run is slower. Tracing is not free. |
| 5–8s | The same command again. `cache HIT`. | Guards passed. Result reused. | Reuse happens only after the checks, not because the argv matched. |
| 8–12s | The published medians, with both rows visible: 312.913 ms → 3.972 ms, and 7.396 ms → 7.957 ms. | One workload got faster. A shorter one did not. | The loss is the credibility. |
| 12–16s | Append a line to `numbers.txt`. | The input changed. | A memoization key of argv alone would not notice. |
| 16–20s | `tracejit run` again. `cache DEOPT`, then a new trace. Not `HIT`. | TraceJIT retraces instead of replaying the stale result. | The interesting part is the refusal. |

Do not overlay 78x without the synthetic label and the short-command loss. Do not show a Python or `cc` speedup. Those commands are refused.

Suggested capture width: 100 columns, dark terminal, no editor chrome. Export a GIF or MP4 outside the git repo. Do not commit a large binary.

The social-preview source is `social-preview.svg`. Export a 1280×640 PNG for GitHub. The SVG is the file to edit.
