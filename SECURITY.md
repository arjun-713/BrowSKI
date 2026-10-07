# Security

Browser agents interact with credentials, private pages, downloads, uploads,
external communication, and potentially consequential actions (purchases, form
submissions, messages sent as the user). This project treats that as
safety-critical surface even though full safety policy is not implemented in
the scaffold (v0.1).

## Current implementation scope

- Rust owns Chromium control, semantic observation, typed actions, and
  deterministic verification; Python owns orchestration and provider policy.
- GPT-6 Luna is the active generative reasoning path. Laya is shadow-only and
  Jev is disabled by current product policy. Do not enable either as an action
  authority without reviewed evidence.
- The typed `ProviderBoundary` supports `standard`, `privacy_first`, and
  `offline` modes. Privacy-first tokenization is heuristic and must not be
  treated as a guarantee that every sensitive value is detected.
- High-risk browser actions are subject to a graph-level confirmation
  interrupt. The browser-code execution route is disabled until a restricted
  evaluator can enforce its capabilities.
- Product security remains incomplete. The authenticated extension host,
  bridge-only socket service, and Linux host installer are implemented; the
  attached-browser backend, keyring integration, retention cleanup, and
  end-to-end secret-leak tests remain outstanding.

## Required security direction

- Explicit user confirmation for consequential actions (submit, purchase,
  send, delete).
- Scoped permissions per task (allowed domains, actions, data).
- Local PII/secret detection and tokenization through the provider boundary.
- Audit traces of every action and its verification evidence.

See the [internal threat model](docs/security/threat-model.md) for attacks,
controls, gaps, and residual risk. See
[`docs/architecture/browser-extension.md`](docs/architecture/browser-extension.md)
for the extension permission and transport boundary.

## Responsible disclosure

If you find a security vulnerability, please report it privately to the
maintainers through the repository’s private vulnerability reporting
mechanism (GitHub Security Advisories) rather than opening a public issue.
Include reproduction steps, affected version/commit, and impact assessment.
No security contact email is published for this project yet; do not invent
one — use the repository’s advisory workflow.
