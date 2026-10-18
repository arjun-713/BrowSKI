# BROWSKI browser companion

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A person assigning tasks to an agent while watching their own Chrome browser.
No more specific audience segment was supplied for this sidebar update.

## Product Purpose

Draft a browser task, provide reference context, and follow the runtime's public
decisions, actions, verification results, and requests for confirmation.

## Capabilities and Constraints

- This is the production WXT/React extension in `mango`, as selected by the user.
- The extension presents state and brokers attachment. Rust owns browser truth,
  execution and verification; Python owns agent decisions and orchestration.
- Keep the existing explicit tab-attachment and consequential-action approvals.
- The composer supports slash shortcuts, selected tab/link references, and
  bounded text-file context through the existing 4,000-character task boundary.
- Mentions share a title and URL; they do not read the source page or grant control.
- Reference files support TXT, Markdown, CSV, and JSON. PDF/image interpretation
  and uploading files into websites are outside the present capability.
- Public decision summaries are distinct from hidden model reasoning.
- Software tests with synthetic providers do not establish live task reliability.

## Brand Commitments

The user requested a clean browser sidebar comparable in feel to Perplexity
Comet, with orange activity feedback in the page instead of blue.

## Evidence on Hand

The runtime event contract is in `src/protocol.ts`. Component tests live beside
the panel; packaged Chromium acceptance tests are in
`../python/tests/extension/test_browser_e2e.py`. `../ARCHITECTURE_PLAN.md` is the
architecture authority.
