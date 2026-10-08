# ADR-016: Explicit extension-owned tab lifecycle

Status: Accepted

## Context

Attached mode starts from a user-selected Chrome tab. The runtime must keep
that tab under the user's control while allowing browser tasks that need a
second page. Forwarding generic `Target.*` CDP commands would give the agent
browser-wide target access and expose Chrome target identities.

## Decision

The extension owns a bounded tab map for one attachment. Rust continues to
own the single semantic browser session and addresses tabs through opaque
target and session IDs. The initial tab uses the attachment UUID as its opaque
target suffix; supporting tabs receive fresh opaque IDs. Chrome tab IDs remain
inside the extension and are stored only in session-scoped extension state.

The bridge exposes only four synthetic operations: create a supporting tab
from a credential-free HTTP(S) URL, activate an owned target, close one
supporting target, and detach all debuggers. The map holds at most eight tabs,
including the initial tab. Generic `Target.*` commands remain unavailable.
Screenshot capture is limited to the current viewport in PNG format.

The agent cannot close the initially attached user tab. Closing a supporting
tab removes only that tab from the map. Navigating a supporting tab outside
its creation origin invalidates that tab. A user closing or detaching the
initial tab ends the attachment and detaches supporting debuggers.

On runtime shutdown, the extension detaches all owned debuggers and leaves all
tabs open, including supporting tabs. A new session does not inherit the old
ownership map. The extension may restore the map after a background worker
restart only when the stored attachment, owner session, tab identities,
debugger attachments, and tab origins all match. Otherwise it detaches the
initial attachment and requires the user to attach again.

## Consequences

- One Rust-owned semantic browser engine handles the initial and supporting
  tabs; Python and TypeScript do not create parallel browser sessions.
- Browser APIs and Chrome numeric tab IDs remain behind the extension's
  attachment-scoped map.
- Supporting tabs remain open after runtime shutdown and can be closed by the
  user in Chrome.
- The capability does not provide arbitrary browser target discovery or
  browser-wide CDP access.
