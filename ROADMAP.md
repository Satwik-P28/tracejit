# Roadmap

The following work is deliberately outside V1:

- automatic parallelization and speculative execution
- partial-subgraph caching
- GPU and CUDA tracing
- distributed caching and remote execution
- Kubernetes integration
- model routing and semantic LLM caching
- GitHub pull-request automation
- graphical web interfaces
- macOS and Windows support
- source-code rewriting
- automatic network replay

Potential tracing backends such as eBPF require an explicit correctness and event
loss design before they can supplement ptrace. None of these items is implemented
or implied by the current CLI.

