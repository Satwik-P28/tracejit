# Optimization report

Local working tree. Nothing here was posted, released, or pushed.

## CRITICAL

| Problem | Change | Reason | Expected impact | Validation |
| --- | --- | --- | --- | --- |
| The 78.780x result could be read as a production speedup. The workload is 250,000,000 synthetic mix rounds. | README, BENCHMARKS.md, social preview, and launch copy now say synthetic, and they keep the 7.396 ms → 7.957 ms loss in the same view. | A skeptical reader will open `main.c`. Hiding the construction would fail that read. | The large number stays usable because the loss and the construction are visible. | Numbers copied from `benchmarks/results/break-even.md` and `latest.md`. Not remeasured. |
| `mmap` is ignored, and `Guard::NoUnexpectedEffects` always passes. Neither was obvious in the old README. | ARCHITECTURE.md, SAFETY.md, README limitations, ROADMAP, and RED_TEAM.md state both. | Shipping a launch that says "safe" without these holes would not survive review. | Reviewers can reject the tool for a stated reason instead of discovering a buried one. | Read `is_known_internal_syscall` and the `NoUnexpectedEffects` match arm. No behavior change. |
| `PROJECT_STATE.md` said the v0.1.0 release did not exist. It does. | Rewrote the release and blocker section. | A stale status file undermines the rest of the docs. | Maintainers stop waiting to create a release that is already public. | `gh release view v0.1.0` showed the archive and checksum. |

## HIGH IMPACT

| Problem | Change | Reason | Expected impact | Validation |
| --- | --- | --- | --- | --- |
| The README explained the mechanism before the result, and it did not show the refusal case. | Replaced README with a short hook, install, demo, both measurements, safety, and explicit non-goals. | Five-second comprehension was the launch requirement. | A new reader can see what it does, the win, and the loss without scrolling through crates. | Read-through against the CLI help and the result files. |
| `explain` dumped debug structures and environment-bearing guard values. | Source builds print READ/EXEC/WRITE lines and guard names. Environment values are not printed in that summary. | The dependency picture is the technical demo. | `./scripts/demo.sh` shows the graph on a source build. v0.1.0 does not. | Unit test `dependency_summary_names_effects_without_environment_values`. |
| Unsupported machines got "requires Linux x86_64" without saying reuse cannot continue. | `doctor` names the OS and architecture and says tracing and reuse are unavailable. Linux ptrace failures say not to guess. Missing Landlock says `GUARDED` can continue and `PROVEN` cannot. | First-run failures were the onboarding gap. | macOS and locked-down containers fail in plain language. | Unit test `unsupported_platform_explains_why_reuse_is_unavailable` on non-Linux. Linux wording not executed here. |

## MEDIUM

| Problem | Change | Reason | Expected impact | Validation |
| --- | --- | --- | --- | --- |
| Demo script did not show the untraced command. | `scripts/demo.sh` times one direct run, then the existing miss, hit, explain, and mutation checks. | The story needs "slow, then reused, then invalidated." | Linux CI still asserts the same cache strings. | `sh -n` only on this machine. |
| Comparisons, adversarial narrative, and a dependency schematic were missing. | `docs/COMPARISONS.md`, `docs/ADVERSARIAL.md`, `docs/DEPENDENCY_GRAPH.md`. | Reviewers ask "why not Bazel" immediately. | The niche is stated as whole-command observation, not as a replacement. | Compared with the fixture test names and `cases.json`. |
| Contributor entry points were thin. | SECURITY.md, CODE_OF_CONDUCT.md, pull-request template, CHANGELOG, concrete ROADMAP, proposed issues. | Launch traffic needs a place to put a safety bug. | Reports have a path that does not ask for stars. | Not filed on GitHub. |

## OPTIONAL

| Problem | Change | Reason | Expected impact | Validation |
| --- | --- | --- | --- | --- |
| Launch copy lived in four short files and did not cover the requested channels. | `docs/launch/` holds the HN, Reddit, X, LinkedIn, outreach, blog, checklist, 30-day plan, metrics, and red team. | Distribution had to be prepared without being sent. | The maintainer can post without inventing claims in the moment. | Drafts quote only the published medians. |
| No social image source. | `docs/assets/social-preview.svg` and a storyboard. | GitHub's preview is a manual upload. | The image includes the loss. | SVG is text. PNG export is still manual. |
| Old `launch/*.md` drafts would contradict the new ones. | Replaced with pointers. | Two Show HN posts will drift. | One canonical draft. | Pointers only. |

## Not done, on purpose

- No new benchmark run. This machine is macOS.
- No mmap enforcement patch. The safe change is a behavior change that needs a Linux fixture.
- No release, tag move, or post.
- No topic or description edit on GitHub. Those steps are in `GITHUB_SETUP.md`.
