# Launch checklist

Nothing in this file posts, emails, or publishes a release. Do these in order.

## Before any public post

- [ ] Review this working tree. The live GitHub README does not include it until it is committed and pushed.
- [ ] Push to the default branch.
- [ ] Wait for GitHub Actions CI on that commit: fmt, clippy, `cargo test --workspace`.
- [ ] On Linux x86_64, run `cargo test -p tracejit-cli --test linux_integration -- --nocapture` and `./scripts/demo.sh`. The release workflow runs both. A macOS checkout cannot.
- [ ] Read the README once as a stranger. Confirm the 78.780x row and the 0.929468x row are both visible, and that the transform is called synthetic.
- [ ] Export `docs/assets/social-preview.svg` to a 1280×640 PNG and upload it. Settings are in `GITHUB_SETUP.md`.
- [ ] Apply the description and topic changes in `GITHUB_SETUP.md`. Remove `build-systems`.
- [ ] Enable private vulnerability reporting so `SECURITY.md` is true.
- [ ] Announce 0.1.1 only after that GitHub Release exists. The v0.1.0 binary does not have this `explain` summary, these `doctor` sentences, or the shared-mmap refusal. Do not move the `v0.1.0` tag.

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
