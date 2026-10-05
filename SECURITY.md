# Security

TraceJIT can replay a previous command's stdout, stderr, exit status, and output files. A wrong reuse is a correctness bug and, if the command's output is trusted, a security bug.

## Report a suspected unsafe reuse

If the report includes secrets, credentials, or a working exploit against someone else's cache, use a private GitHub security advisory on [Satwik-P28/tracejit](https://github.com/Satwik-P28/tracejit). Do not open a public issue for that.

If the report is a minimal command TraceJIT should have recomputed, and it contains no secrets, use the public Break TraceJIT issue template. Accepted reports become fixtures.

There is no separate security email in this repository. Do not invent one.

## What this project does not claim

- No security audit is claimed.
- `PROVEN` is not a formal proof and not a sandbox product. It means seccomp and Landlock were installed for that run. See [SAFETY.md](SAFETY.md).
- The cache is not encrypted and is not isolated between users. `~/.cache/tracejit` can contain command output and environment values. Do not share that directory across trust boundaries.
- ptrace is a privileged observation mechanism. `tracejit doctor` fails when attach is denied. Do not disable `yama.ptrace_scope` just to make a demo work unless that matches your own policy.

## Cache contents

Treat the cache as sensitive as the commands you trace. `tracejit cache clear` deletes the local store. It does not scrub copies you made elsewhere.
