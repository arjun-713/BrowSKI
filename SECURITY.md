# Security

Browser agents interact with credentials, private pages, downloads, uploads,
external communication, and potentially consequential actions (purchases, form
submissions, messages sent as the user). This project treats that as
safety-critical surface even though full safety policy is not implemented in
the scaffold (v0.1).

## Current scope (scaffold)

- The runtime launches a real Chromium, navigates to arbitrary URLs, and
  reads page state. It does not yet fill forms, upload files, or call LLMs.
- No credential storage, token vault, or PII filtering exists yet — do not
  feed secrets through the agent until the privacy modules land (see
  `docs/architecture/privacy-and-vision.md` and the roadmap, phase 10).
- Example and test code navigates only to public pages.

## Future safety direction (not yet implemented)

- Explicit user confirmation for consequential actions (submit, purchase,
  send, delete).
- Scoped permissions per task (allowed domains, actions, data).
- Local PII/secret detection and a token vault before any remote model call.
- Audit traces of every action and its verification evidence.

## Responsible disclosure

If you find a security vulnerability, please report it privately to the
maintainers through the repository’s private vulnerability reporting
mechanism (GitHub Security Advisories) rather than opening a public issue.
Include reproduction steps, affected version/commit, and impact assessment.
No security contact email is published for this project yet; do not invent
one — use the repository’s advisory workflow.
