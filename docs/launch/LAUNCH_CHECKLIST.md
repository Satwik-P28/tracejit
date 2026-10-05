# Launch checklist

Nothing in this file posts, emails, or publishes a release. Do these in order.

## Before any public post

- [x] Push to the default branch. v0.1.1 is commit `31c36d1`.
- [x] Linux x86_64 CI on that commit: fmt, clippy, workspace tests, `linux_integration`, and `./scripts/demo.sh`.
- [x] Description, topics, and private vulnerability reporting are set. Discussions are off. v0.1.0 was not moved.
- [x] v0.1.1 is published. The v0.1.0 binary does not have this `explain` summary, these `doctor` sentences, the shared-mmap refusal, or the vDSO time redirect.
- [ ] Upload `docs/assets/social-preview.png` (1280×640) in the repository settings. The API used for the rest of the metadata does not accept that image.

## Release commands, if a new version is approved

Do not run these until the version in `Cargo.toml` is bumped and `RELEASE_NOTES.md` describes that version.

```bash
# On GitHub: Actions → Release binary → Run workflow, on the commit you intend to ship.
# Then, after the artifact is reviewed locally:
gh release create vX.Y.Z --draft --title "TraceJIT vX.Y.Z" --notes-file RELEASE_NOTES.md
# Attach dist/tracejit-vX.Y.Z-x86_64-unknown-linux-gnu.tar.gz and dist/SHA256SUMS.
# Publish the draft only after sha256sum -c succeeds on a second machine.
```

v0.1.0 already exists. Do not recreate it. The candidate is v0.1.1.

## Post order

1. Update the repository. Wait a day if CI or the demo misbehaves. Fix that before writing posts.
2. Show HN, using title 1 in `HACKER_NEWS.md`. Stay on the thread.
3. One programming-community post at most the same day, if that community's rules allow it. Prefer r/rust or a blog link over a five-subreddit burst.
4. The X thread only if a real terminal recording exists.
5. LinkedIn only if you want that audience. It is optional.
6. Outreach notes the week after, a few people, each with a question from `OUTREACH.md`. No star asks.

## Do not

- Do not buy stars, replies, or traffic.
- Do not post the same text to every subreddit.
- Do not claim production users, contributors, or deployments.
- Do not hide the 7 ms regression.
