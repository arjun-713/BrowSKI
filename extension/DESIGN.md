---
name: BROWSKI sidebar
description: A quiet browser workspace for tasks, context, and public runtime activity.
colors:
  accent: "#b94e16"
  accent-dark: "#963b0e"
  accent-soft: "#fff0e5"
  paper: "#faf9f7"
  surface: "#ffffff"
  soft: "#f1efec"
  ink: "#292723"
  muted: "#6c675f"
  line: "#e4e0da"
  line-strong: "#c8c1b7"
  success: "#286345"
  success-soft: "#edf5ee"
  danger: "#9d3227"
  danger-soft: "#fff0ee"
  page-activity: "#f47b35"
  page-badge: "#38261d"
typography:
  headline:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "24px"
    fontWeight: 550
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  title:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  body:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.6
  supporting:
    fontSize: "13px"
    lineHeight: 1.6
  label:
    fontSize: "12px"
    fontWeight: 550
  metadata:
    fontSize: "11px"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "11px"
rounded:
  control: "6px"
  context: "8px"
  container: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  send-button:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.context}"
    size: "34px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.container}"
    padding: "12px"
  reference-chip:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.context}"
    padding: "3px 4px 3px 8px"
  command-option-selected:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px"
    height: "52px"
  decision-summary:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.context}"
    padding: "10px 12px"
---

# Design System: BROWSKI sidebar

## Overview

**Creative North Star: "A quiet browser workspace"**

A quiet browser workspace following the user's Comet reference. White and warm offwhite surfaces keep the page primary; compact controls frame an open activity feed and a bottom-anchored composer. System type, fine separators, and small corners make the interface feel familiar and precise.

Orange identifies sending and agent activity, with restrained supporting use for focus, attachment cues, and approval emphasis. Green and red retain their existing connection, verification, and failure meanings. Public decision summaries, actions, and verification stay visibly distinct.

**Key Characteristics:**

- Warm neutral surfaces with ink text and muted supporting copy.
- Open chronological activity rather than a stack of decorative cards.
- A persistent multiline composer with removable reference chips.
- Small, purposeful motion with a steady reduced-motion alternative.

## Colors

### Primary

Burnt orange (`accent`) gives send and running states their emphasis; its darker
variant handles hover and its pale tint supports approval and brand cues. The
brighter `page-activity` orange marks the page edge against a dark `page-badge`.
Focus outlines and carets reuse the accent without turning neutral controls into
primary actions.

### Neutral

Warm paper forms the canvas; white surfaces carry the header, composer, fields,
and menu. Soft inset gray groups task context, reference chips, and decision
summaries. Ink carries primary text; muted warm gray carries metadata and helper
copy. Fine and stronger line colors separate sections and outline fields.

### Status

Forest green and its pale tint identify successful connection or verification
states. Brick red and its pale tint identify failures and inline errors. Status
meaning is also expressed through text and icons.

**The Activity Accent Rule.** Reserve strong orange emphasis for sending, running activity, and approval attention; use neutral surfaces for ordinary controls and references.

## Typography

Use the system sans stack for both interface and reading. Monospace is reserved
for data and keyboard hints. No separate display face is used.

- **Headline:** the empty-state invitation uses the headline token; supporting
  copy stays within (32ch) and uses a relaxed line height (1.65).
- **Title:** section headings use the title token; the compact brand heading is
  (15px), weight (700), with tracking (-0.025em).
- **Body:** task text and the textarea use the body token. Event titles are
  (14px), weight (550), line height (1.45).
- **Supporting:** event descriptions use supporting text; the panel base uses
  the same size with line height (1.5).
- **Label and metadata:** controls use label text; timestamps, counts, and helper
  copy use metadata. Counts and timestamps use tabular numerals.

## Layout

A full-height flex column (100dvh, minimum height 420px) places a compact header
above the independently scrolling activity region and persistent bottom composer.
The header uses (20px) horizontal padding; the feed uses (20px) padding. The
composer sits in a paper-colored surround with (12px) padding and bottom safe-area
allowance. The feed is an open vertical sequence with a narrow icon rail and fine
connectors, spaced (24px) between events.

At widths up to (340px), header and feed gutters shrink to (12px). At heights up
to (600px), the empty state tightens, its heading becomes (20px), the textarea
minimum becomes (48px), and the extra attachment hint hides. Otherwise the
textarea spans (72–180px) and can be resized vertically. Long content wraps;
reference and menu labels truncate within their available width. The command
menu opens above the composer and scrolls within the smaller of (360px) or
(45dvh); keyboard selection must stay visible.

## Elevation & Depth

The sidebar is flat by default. Surface tone, separators, and a single field
outline provide structure. The command menu alone floats above the composer with
a soft shadow; the page badge has a smaller shadow for legibility over websites.
Exact shadow and motion values live in the sidecar.

**The Flat Workspace Rule.** Use surface tone and fine separators for structure. Lift only the command menu and page activity badge.

## Shapes

Use the control, context, and container corner tokens for small controls, chips
and insets, and larger composer/menu/approval surfaces respectively. Borders are
fine (1px). Tiny state dots remain circular; keyboard hints have compact (4px)
corners. The page feedback frame uses a thin (3px) orange edge with (5px) corners.

## Components

### Buttons and fields

Primary actions use orange with white text and darken on hover. Secondary actions
use a white surface and stronger outline; destructive actions use red text and a
pale error hover. Standard buttons have a minimum height (36px); compact runtime
and tab actions are smaller. Icon tools are neutral (32px square); send is an
orange square using the send-button token. Disabled send becomes soft gray.
Pressed primary controls shift down (1px). Keyboard focus uses a visible accent
outline (2px, offset 3px). Settings inputs are outlined, at least (38px) high,
with control corners.

### Composer and context

A white outlined multiline composer shifts its border to orange on focus and red
on invalid input. Enter sends; Shift+Enter adds a line; IME composition never
sends. Drafting works offline; sending requires the existing runtime session.
`/` opens shortcuts; `@` searches HTTP(S) tabs or accepts a supplied link. Arrow
keys navigate, Enter selects, and Escape dismisses the menu. Selected items have
a soft neutral fill. Removable chips wrap above the textarea.

Tab/link references share their selected title and URL on send; they neither
read the page nor attach or authorize control of a tab. Text-file references
support TXT, Markdown, CSV, and JSON, with at most five files and the existing
(4,000-character) serialized task boundary. Preserve the existing explicit tab
attachment and approval controls; these references are context only.

### Activity and approvals

Public decision summaries use a soft inset disclosure with a rotating chevron;
actions and verification use separate labeled timeline events. Running icons are
orange, completed icons green, and failed icons red. Approval requests use a pale
orange outlined container. The interface presents runtime state: Rust owns browser
truth, execution, and verification; Python owns agent decisions and orchestration.

### Page activity feedback

A pointer-transparent orange frame and “BROWSKI is working” badge appear only on
owned tabs while a connected session is running. They clear on pause, approval,
completion, stop, detach, or disconnection. The frame gently fades over (1.8s);
reduced motion makes it steady. Sidebar state transitions use (160ms) feedback
and stop under reduced motion. This indicator is presentation only.

## Do's and Don'ts

### Do:

- **Do** keep public decisions, actions, and verification distinguishable in the activity feed.
- **Do** keep the composer at the bottom while the activity region scrolls independently.
- **Do** preserve visible keyboard focus, selected-option visibility, readable wrapping, and reduced-motion behavior.
- **Do** keep reference selection visually distinct from explicit tab attachment and control.

### Don't:

- **Don't** turn ordinary controls or reference chips into orange calls to action.
- **Don't** add decorative cards, gradients, display fonts, or entrance choreography to this quiet workspace.
- **Don't** present a public decision summary as hidden reasoning or the page indicator as browser observation or control.
