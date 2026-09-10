# executor

Validated browser actions: click/type/select/check/scroll/press/navigate/wait.

## May

- Define the `BrowserAction` vocabulary and `ActionResult` evidence shape.
- (Later) carry out validated actions against a live session.

## May NOT

- Perform agent reasoning or LLM calls.
- Treat a completed tool call as verified success — verification owns that
  (see `verification`).
