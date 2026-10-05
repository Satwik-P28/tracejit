# After the announcement

## First response

Answer technical objections with the file that already states the limitation. If the objection is right and the docs are wrong, fix the docs or the code before writing a longer defense. A stale-reuse report jumps the queue. Ask for a minimal command, the commit, and the `explain` output, then turn it into a fixture.

Do not argue a benchmark number that is not in `benchmarks/results/`. If someone cannot reproduce the demo, treat that as an onboarding bug.

## What to collect

Write down, in an issue or a private note, not in the README:

- commands people actually tried
- the classification they got
- whether `doctor` was understandable
- which sentence in the README they misunderstood

That list is the second-wave work. Do not invent a follow-up feature to have something to post.

## Second wave

A follow-up post is justified only by a change that landed. The honest candidates are already in `ROADMAP.md`: a modeled syscall with a fixture, an explicit `UNKNOWN` for shared mmap writes, or a released binary whose `explain` matches the README. "We are excited about the response" is not a second wave.

## If it is quiet

Leave it. Do not solicit stars. A later technical post can stand on a real patch. Silence is not a reason to widen the claims.
