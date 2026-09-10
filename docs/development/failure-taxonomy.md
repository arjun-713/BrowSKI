# Failure taxonomy

Every failure carries a kind, evidence, and an owning component. Low-level
kinds are retried mechanically in Rust (bounded); the rest escalate to the
Python agent for replan/alternate-strategy/escalate decisions.

| Kind | Meaning | Owner |
|---|---|---|
| GROUNDING | Could not locate the target element/action | observation + element-registry (Rust) |
| PLANNING | Plan was wrong, incomplete, or contradictory | planner (Python) |
| MEMORY | Lost, bloated, or corrupted working memory | memory (Python) |
| EXECUTION | Action dispatch/transport failed | executor + browser-core (Rust) |
| VERIFICATION | Postcondition did not hold / UNCERTAIN | verification (Rust) |
| RECOVERY | Recovery itself failed or exhausted bounds | recovery (both levels) |
| VISION | Screenshot/perception path failed | vision module (Python, Ph.7) |
| NAVIGATION | Navigation never reached the expected URL/state | browser-core (Rust) |
| FRAME | Frame detached, missing, or cross-origin blocked | browser-core (Rust) |
| TAB | Tab target gone, crashed, or un-attachable | browser-core (Rust) |
| UPLOAD | File upload failed | executor (Rust, later) |
| DOWNLOAD | Download failed / unreachable | executor (Rust, later) |
| AUTH | Login/session/auth wall encountered | agent (Python, escalate to user) |
| TIMEOUT | Bounded wait exceeded | whoever set the bound |
| STAGNATION | Repeated actions / unchanged state | progress (Python) |
| SITE_BLOCK | Bot detection, rate limit, access denied | agent (Python, alternate strategy) |
| MODEL_FORMAT | Model output unparseable / schema-violating | providers (Python) |
| SAFETY | Action refused on safety grounds | agent (Python) + future policy |
| UNKNOWN | Unclassified; attach evidence, classify later | reporter adds evidence |

Rust’s mechanical classifier (`crates/recovery`) maps transport/CDP errors
onto the closest low-level kind (`StaleNode→GROUNDING`,
`DetachedFrame→FRAME`, `NavigationRace→NAVIGATION`, `Timeout→TIMEOUT`,
`TargetGone→TAB`, `ProtocolError→EXECUTION`); anything else escalates as
`UNKNOWN` with the raw message preserved.
