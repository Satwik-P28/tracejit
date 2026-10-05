# 30-day plan

Dates are relative to the day the repository state you are announcing is on the default branch and Linux CI is green. Do not start the clock on an unpushed tree.

## T-7 through T-1

- Read `OPTIMIZATION_REPORT.md` and the README as a reviewer who wants the project to be wrong.
- Push. Confirm CI. Run the Linux demo if the push was from a machine that cannot.
- Apply `GITHUB_SETUP.md`.
- Export the social preview. Do not draw a new number on it.
- Draft posts stay drafts. Send zero outreach.
- If the demo or doctor fails on a clean Linux VM, that is the only work that week.

## Launch day

- Post the Show HN text from `HACKER_NEWS.md`. Title 1.
- Watch the thread for several hours. Answer with commits and file names.
- At most one other public post, and only if that community allows it.
- Do not cut a release on launch day unless the binary people are installing is missing a feature the post describes.

## Days 1–3

- Triage issues. Reproducible stale reuse first.
- Note every install failure. Fix the message or the docs if the fix is small and does not change classification.
- Do not promise syscall coverage in the thread unless a patch is up.

## Week 1

- Pick one recorded `UNKNOWN` from `benchmarks/results/break-even.md` and either model it with a fixture or write down why it must stay unknown. That is the week's technical output.
- Thank people who filed fixtures. Credit them in the fixture or the changelog.

## Week 2

- If week 1 produced a real patch and CI is green, write a short follow-up that links the patch. If it did not, do not write the follow-up.
- Start two outreach notes from `OUTREACH.md`, to people whose public work you can cite. Stop if you are sending into a void.

## Weeks 3–4

- Second measured artifact only if you changed the hit path or the workload. Run the existing harness. Commit the generated result files. Do not hand-edit medians.
- Decide whether v0.1.1 is worth cutting. It is worth cutting if `explain` or `doctor` behavior in git has diverged from the binary the README tells people to install, and the Linux release workflow passed.
- Close the month by updating `PROJECT_STATE.md` with what changed and what is still refused. Delete nothing from the loss column.
