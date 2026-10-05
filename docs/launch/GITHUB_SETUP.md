# GitHub settings to change by hand

Do not apply these from a script during review. The repository is already public at https://github.com/Satwik-P28/tracejit. v0.1.0 is already published.

## Description

```text
Reuse unmodified Linux x86_64 commands only when observed dependencies still pass synchronous guards.
```

The current description is close. This one drops the implication that the project is a general build cache.

## Website

Leave blank. There is no project site. Do not point the website field at a social post.

## Social preview

Export `docs/assets/social-preview.svg` to a 1280×640 PNG and upload it as the social preview. The image includes the synthetic 312.913 ms → 3.972 ms result and the 7.396 ms loss. Do not replace it with a 78x-only image.

## Topics

GitHub allows 20. Use only these:

```text
rust
linux
systems-programming
performance
caching
memoization
ptrace
seccomp
landlock
dependency-analysis
incremental-computation
developer-tools
process-tracing
```

Remove `build-systems` and `optimization` if they are still set. Shell and `cc` are refused, so a build-systems topic overclaims. `optimization` is too vague to be a search term anyone should land on.

## Features

- Issues: on. Templates already exist for Break TraceJIT, performance, compatibility, and syscall coverage.
- Discussions: off until there is a maintainer habit of answering them. Issues are enough for the first announcement. Turn Discussions on later if questions are crowding bug reports. Do not turn them on in order to ask for stars.
- Projects, Wikis: off.
- Sponsorships: leave off unless there is a real funding link. Do not add an empty sponsor button.
- Releases: keep. The next release is a manual `workflow_dispatch` of "Release binary", then a draft the maintainer publishes. See `LAUNCH_CHECKLIST.md`.
- Security advisories: enable private vulnerability reporting so `SECURITY.md` has a place to send secret-bearing reports.

## Pull requests

No required setting can be changed from git. After this tree is pushed, require the CI workflow to pass before merge if branch protection is not already on. Do not require conversations to be resolved if you are the only reviewer and it slows fixes.

## README link check

The default branch README is the landing page. The announcement should go out only after this tree is the default branch and Linux CI is green.
