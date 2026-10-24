---
name: BROWSKI side panel
description: Night Receipt. A matte printer housing that prints each browser task as a thermal receipt, stamped Verified or Not verified.
colors:
  housing: "#0d0c0b"
  surface: "#171513"
  tape: "#1a1815"
  soft: "#24211d"
  rule: "#2d2924"
  rule-strong: "#4b453d"
  bone-ink: "#efe9dd"
  faded-ink: "#a39b8e"
  ember: "#ff7a1a"
  ember-hover: "#ff9a4d"
  ember-soft: "#2b1a0e"
  ember-ink: "#1b0d03"
  print-slot: "#050404"
  verified-green: "#7fd39a"
  verified-soft: "#142319"
  fault-red: "#ff8f80"
  housing-light: "#e8e4dc"
  surface-light: "#f6f3ed"
  tape-light: "#fbf9f4"
  soft-light: "#ebe6dd"
  rule-light: "#d9d2c6"
  rule-strong-light: "#a39a8b"
  ink-light: "#1c1915"
  faded-ink-light: "#5d564c"
  ember-light: "#c0520e"
  ember-hover-light: "#9f4209"
  ember-soft-light: "#fbe8d7"
  ember-ink-light: "#ffffff"
  print-slot-light: "#2a2622"
  verified-green-light: "#1f6a3e"
  verified-soft-light: "#e4f2e8"
  fault-red-light: "#ad3528"
typography:
  display:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "22px"
    fontWeight: 400
    lineHeight: 1.25
  wordmark:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "16.5px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.04em"
  order-line:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "16.5px"
    fontWeight: 400
    lineHeight: 1.45
  print-line-live:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  print-line:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  stamp:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.1em"
  data:
    fontFamily: "Departure Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 400
    fontFeature: "tnum"
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 620
    lineHeight: 1.35
  answer:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  tape: "3px"
  stamp: "4px"
  chip: "6px"
  control: "8px"
  slip: "10px"
  panel: "12px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ember}"
    textColor: "{colors.ember-ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.ember-hover}"
    textColor: "{colors.ember-ink}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.soft}"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.ember}"
    padding: "0 2px"
    height: "32px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.faded-ink}"
    rounded: "{rounded.control}"
    size: "32px"
  icon-button-hover:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.bone-ink}"
  send-button:
    backgroundColor: "{colors.ember}"
    textColor: "{colors.ember-ink}"
    rounded: "9px"
    size: "36px"
  send-button-disabled:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.faded-ink}"
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.panel}"
    padding: "16px 12px 8px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
    height: "40px"
  tape:
    backgroundColor: "{colors.tape}"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.tape}"
    padding: "18px 16px 20px"
  print-line:
    textColor: "{colors.faded-ink}"
    typography: "{typography.print-line}"
    padding: "7px 0"
  print-line-live:
    textColor: "{colors.bone-ink}"
    typography: "{typography.print-line-live}"
  hold-slip:
    backgroundColor: "{colors.ember-soft}"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.slip}"
    padding: "14px 14px 12px"
  stamp-verified:
    backgroundColor: "{colors.verified-soft}"
    textColor: "{colors.verified-green}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "5px 10px 5px 8px"
  stamp-unverified:
    backgroundColor: "transparent"
    textColor: "{colors.faded-ink}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "5px 10px 5px 8px"
  context-chip:
    backgroundColor: "{colors.soft}"
    textColor: "{colors.bone-ink}"
    rounded: "{rounded.control}"
    padding: "3px 4px 3px 8px"
    height: "28px"
---

# Design System: BROWSKI side panel

## Overview

**Creative North Star: "Night Receipt"**

The panel is a matte black printer housing and every task is a strip of dark thermal tape it prints. The header is the printer mouth: a recessed print-head slot runs across its bottom edge and lights ember orange while the agent works. The user's request prints first as the order line, each public step prints as a numbered line, a risky action halts the tape at a hold slip, and the answer arrives below a torn edge as the receipt total, with a rubber stamp that reads Verified or Not verified and a dashed footer of counts. The direction refuses the chat-bubble AI sidebar: there are no message bubbles, no avatars facing each other, no typing dots.

The system is dark first. A light variant follows `prefers-color-scheme` and re-inks the same objects (warm grey housing, near-white tape, burnt ember) without changing any shape or behaviour. Density is close to a developer tool: 13px printed lines, 11px data, generous dashed and dotted rules between items instead of cards. Motion is mechanical and short: lines feed up 6px into place, the print head sweeps, the stamp lands with a rotation, LEDs breathe. Everything stops under `prefers-reduced-motion`.

The stamp is a truth display, not decoration. It reads Verified only when the runtime's independent verdict says so; every other outcome prints a muted Not verified stamp beside the plain outcome label. Synthetic preview fixtures render the same stamp and must never be presented as evidence of live-model success.

**Key Characteristics:**

- Matte housing, dark thermal tape, bone ink, one ember orange.
- Departure Mono for everything the printer prints; system sans for prose and controls.
- Hierarchy by ink weight: the live line prints largest and brightest, history fades.
- Perforations (dashed), dotted line separators, a zig-zag torn edge and a rotated stamp carry the receipt metaphor.
- Depth is light, not shadow: the print head and live elements glow.

## Colors

A near-monochrome warm-black palette with exactly one hot accent; colour is earned by state, never by decoration.

### Primary

- **Ember** (`ember`, light `ember-light`): the print head while printing, the live step's number, icon and block cursor, the working agent mark, the hold slip border and countdown, the Send/Stop key, primary buttons, focus rings, text caret, links and text actions. `ember-hover` is the hover state (lighter in dark, deeper in light). `ember-ink` is text on ember fills.
- **Ember Glow** (`rgb(255 122 26 / 55%)` dark, `rgb(214 96 20 / 35%)` light; CSS `--glow`): the halo under live elements only. It lives in the sidecar's shadow list.
- **Ember Soft** (`ember-soft`): the hold slip's fill and text selection.

### Secondary

- **Verified Green** (`verified-green` on `verified-soft`): the Verified stamp and the settings safety note icon. It appears nowhere else.

### Tertiary

- **Fault Red** (`fault-red`): failed step lines, inline errors, the offline status dot and the print head when offline.

### Neutral

- **Housing** (`housing`): the panel body, header, composer dock and the torn edge's cut-out.
- **Tape** (`tape`): the receipt strip; the only large lighter plane.
- **Surface** (`surface`): composer box, inputs, command menu.
- **Soft** (`soft`): hover fills, context chips, inline code, disabled Send.
- **Rule / Rule Strong** (`rule`, `rule-strong`): dotted step separators and dashed perforations; strong also draws step numbers, control borders and scrollbar thumbs.
- **Bone Ink / Faded Ink** (`bone-ink`, `faded-ink`): primary text and the live line; everything secondary, including printed history.
- **Print Slot** (`print-slot`): the recessed slot under the header; it stays dark in light mode (`print-slot-light`) because it is a physical opening.

### Named Rules

**The One Ember Rule.** Ember marks what is live, what needs the user, and what the user can act on. A resting surface is never filled with ember just to be branded.

**The Honest Stamp Rule.** Green is reserved for the Verified stamp. An unverified, partial, blocked, failed or stopped result stamps in faded ink, never green and never ember.

## Typography

**Print Font:** Departure Mono, self-hosted (`public/fonts/DepartureMono-Regular.woff2`, SIL OFL 1.1, licence alongside), falling back to `ui-monospace, monospace`. One weight. CSS `--print`; `--mono` is an alias of it.
**Prose Font:** system sans (`ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`), with `font-synthesis: none`.

**Character:** a pixel-cut printer face for what the machine prints, plain system sans for what people read at length. The contrast is the metaphor: printed matter versus explanation.

### Hierarchy

- **Display** (Print, 22px, 1.25, balanced, max 16ch): the idle printer's headline only.
- **Wordmark** (Print, 16.5px, 1, +0.04em): BROWSKI in the header.
- **Order line** (Print, 16.5px, 1.45): the user's task at the top of the tape.
- **Live print line** (Print, 15px, 1.5): the current step, with a blinking ember block cursor.
- **Print line** (Print, 13px, 1.5): completed steps.
- **Data** (Print, 10.5 to 12px, tabular numerals): step numbers, host and time meta, the run meter, countdown, run stats, history timestamps, kbd, code.
- **Stamp** (Print, 11px, uppercase, +0.1em).
- **Title** (Sans, 620, 16px, 1.35): hold slip question and page headings.
- **Answer** (Sans, 15px, 1.6): the receipt total; lists and tables inside it.
- **Body** (Sans, 13 to 14px, 1.5 to 1.65): run heading, composer text, notices, step detail.
- **Label** (Sans, 11 to 12px): footnotes, composer hints, chips, settings labels (13px, 550).

Sans weights in use are 400, 550, 560, 600 and 620; Departure Mono has only its regular weight, so emphasis in printed matter comes from size and ink colour.

### Named Rules

**The Printed Matter Rule.** If the printer would print it (wordmark, task, step, stamp, counts, timings, hosts), it is set in Departure Mono. If a person explains something (answer prose, reasons, settings, notices, buttons), it is system sans.

**The Ink Ramp Rule.** Step hierarchy is a ramp, not a set of badges: past lines in faded ink at 13px, the last line in bone ink, the live line at 15px with ember number and cursor.

## Layout

A single full-height column at Chrome side-panel widths (verified at 340px and 400px). Header (min 60px) on top, a scroll area in the middle, the composer dock pinned at the bottom with safe-area padding. While a receipt is printing alone, the scroll area drops its vertical padding so the tape feeds straight out of the printer mouth and runs to the composer with no dead floor.

The tape is inset 4px from the housing edges inside a 12px gutter, padded 18/16/20px. Step lines are a three-column grid: 22px number, 18px icon, flexible copy, 6px gaps, 7px vertical padding. The token scale in use is 8/16/24px (`spacing`); most other measured values in the stylesheets are literal pixels (6, 10, 12, 14, 18, 22) rather than token references. Long words wrap anywhere; answer tables scroll horizontally inside their own wrapper rather than widening the page.

## Elevation & Depth

Flat by default, with depth expressed as light and recess rather than lift. The housing, tape and controls sit on one plane separated by tone and rules. The print head is cut into the housing with an inset shadow. Live elements emit an ember glow. Only two things truly float: the hold slip (an ember ring plus a soft ember drop) and the slash command menu (a dark drop shadow).

### Shadow Vocabulary

- **Print slot recess** (`inset 0 2px 3px rgb(0 0 0 / 70%), 0 1px 0 var(--line)`): the header slot.
- **Print head beam** (`0 0 10px 1px var(--glow), 0 2px 16px 2px var(--glow)`): the sweeping light while running.
- **LED glow** (`0 0 14px 0 var(--glow)`, smaller `0 0 8px` variants): working agent mark, active status dot, live cursor, Stop key.
- **Hold slip** (`0 0 0 3px` ember at 12%, `0 12px 32px -16px var(--glow)`): the approval card.
- **Focus halo** (`0 0 0 3px` ember at 14 to 16%): composer and inputs on focus.
- **Menu drop** (`0 12px 36px -8px rgb(0 0 0 / 55%)`): command menu.

### Named Rules

**The Glow Means Live Rule.** A glow says the agent is doing something or waiting on the user. When the task is idle, nothing glows.

## Shapes

Small, mechanical corners. Controls round at 8px, the composer and setup notice at 12px, the hold slip at 10px, the stamp at 4px, the Send key at 9px, chips and the agent mark at 6px, the brand tile at 7px. The tape has square top corners (it comes out of a slot) and a 3px bottom radius. Status dots and the engine dot are circles.

Receipt geometry carries the identity: 1px dashed rules are perforations (below the order line, between example tasks and history rows, above the receipt footer), 1px dotted rules separate printed lines, a 2px solid bone rule sits above the answer like a total line, and the torn edge is a 9px zig-zag cut by a conic-gradient mask at a 12px period that reveals the housing behind it. The stamp is drawn with a doubled border (2px border plus a 1px inset ring) and printed rotated -2.5deg.

## Components

### Buttons

- **Shape:** 8px corners, 40px minimum height, 16px side padding, sans 13px at 600.
- **Primary:** ember fill, ember-ink text, ember border; hover moves to `ember-hover`. Used for Approve action and primary settings actions.
- **Secondary:** transparent with a `rule-strong` border and bone ink; hover fills `soft`. Decline uses it.
- **Text button:** ember text, 32px tall, underline on hover. Copy answer, Run again, settings links.
- **Icon button:** 32px square, faded ink; hover or pressed fills `soft` and turns bone.
- **Disabled:** 45% opacity, not-allowed cursor.
- **Focus:** 2px ember outline with 3px offset, everywhere.

### Send / Stop key

A 36px square with 9px corners in the composer's bottom right. Ember with ember-ink glyph; hover `ember-hover`; press scales to 0.96. Disabled it becomes `soft` with faded ink. While a task runs it becomes Stop and gains the LED glow.

### Composer (keypad)

Surface fill, `rule-strong` border, 12px corners, textarea 14px/1.65 sans growing from 56 to 180px. Focus turns the border ember with a 3px ember halo; invalid turns it fault red. A toolbar holds attach, mention and slash icon buttons on the left and the character count (11px tabular) plus Send on the right. Below the box: the engine chip (11px, a 5px ember dot, hover `soft`) and an 11px hint. Context references above the box are `soft` chips with 8px corners and a 24px remove button. The slash menu floats above with the menu drop shadow and `soft` selection.

### Inputs / Fields

40px tall, 8px corners, `rule-strong` border on `surface`. Focus: ember border plus a 3px ember halo at 16%. Selects use a custom chevron tinted to faded ink per scheme. Checkboxes take `accent-color` ember. Disabled at 60% opacity.

### Header (printer mouth)

A three-column grid: brand tile (28px, 7px corners) plus the Departure Mono wordmark; a status pill (7px dot, 12px sans) that brightens to bone with a breathing ember dot while active and turns fault red when offline; icon buttons for new task, history and settings. The print-head slot (5px tall, 8px side inset) runs along the bottom edge. Running: a 34%-wide ember beam with faded ends sweeps across it (2.4s, alternate). Awaiting approval: the full slot lights and pulses (1.1s). Paused: dim at 45%. Offline: fault red at 60%.

### Tape and printed lines (signature)

The tape holds the order line, a run heading (24px agent mark, `soft` at rest and ember with glow while working, plus a 13px status sentence and a pause control), the printed step list, an optional "show steps" text toggle, and a right-aligned run meter (11px data, for example "6 lines · 56s"). Each step line feeds in (`translateY(6px)` to rest, 360ms `cubic-bezier(0.16, 1, 0.3, 1)`). Step details open as a disclosure with a rotating chevron and an indented note behind a 1px `rule-strong` left rule. Failed lines print in fault red with an inline error. Only public step goals are shown; hidden reasoning has no surface.

### Hold slip (approval)

The tape halts at an ember-soft slip with an ember border and 10px corners. It is focused on arrival. Header row: info icon, the action phrased as a question (title type), and a Departure Mono countdown in ember. A 2px drain bar shrinks linearly to the deadline. Then the site host (data type with globe icon), the public reason in ember, Approve action (primary) and Decline (secondary), and a footnote stating the permission covers this action only. Expired disables both buttons and says the agent must ask again.

### Result receipt

A torn edge, then the answer under a 2px bone rule. Answers render paragraphs, bullet and numbered lists, safe links and pipe tables; tables are sans 13px with tabular numerals, a `rule-strong` header rule, dashed row rules and right-aligned numeric columns. The verdict row prints the stamp (lands from -9deg at 1.35 scale over 420ms) and, when not a clean success, a plain outcome label (Partially completed, Blocked, Task failed, Stopped). The verdict reason follows when it differs from the answer. A dashed footer carries run stats in data type ("9 steps · 8 actions · 11 model calls · 1m 33s") and the Copy answer and Run again text buttons.

### Idle printer (empty state)

The Departure Mono display headline, a 14px faded lede capped at 36ch, and example tasks as a perforated list of 46px rows (icon, text, chevron) that turn ember on hover. Setup and connection problems appear as a tape-coloured notice with a 12px radius, an ember icon, a title, a short explanation, a text action and an optional technical-detail disclosure in data type. A consent line closes the view.

### History

A perforated list of past receipts: icon, a truncated 13.5px task title, a data-type timestamp, and a chevron; hover turns the row ember. An empty history shows a short bone heading and faded explanation.

### Settings

Groups separated by 1px rules with 24px vertical padding and faded 13px section titles, labelled 40px inputs, toggles with ember checkboxes, a green-iconed safety note, an Advanced disclosure and an About definition list (80px term column).

### Page presence (in-page overlay)

Rendered in a closed shadow root over the user's tab while a task holds it. Working: a breathing ember edge (inset 2px ring plus two inner glows, 2.6s) with a beam of light travelling the border (conic gradient clipped to a 4px ring, 4.8s per lap). Awaiting approval: the beam stops and the edge deepens into a slow strong pulse (3px ring, 2.4s) so it reads as "your turn". Paused: static at 45%. A bottom-centre pill (dark `#141210` fill, ember-tinted border and glow, 12.5px sans) carries a breathing LED, a one-line status and an ember Stop key (28px, 7px corners) that accepts only trusted clicks. The overlay uses literal colour values because page styles cannot reach panel tokens, and it stays dark whatever the page's scheme. Reduced motion removes the sweep and all breathing.

## Do's and Don'ts

### Do:

- **Do** print every machine-produced string (task, steps, counts, timings, hosts, stamp) in Departure Mono and every explanation in system sans.
- **Do** keep the live step the largest, brightest line on the tape, with ember number and the blinking block cursor.
- **Do** separate receipt items with dashed perforations and dotted line rules instead of cards or bubbles.
- **Do** stamp Verified in green only on an independent runtime verdict; everything else stamps Not verified in faded ink with a plain outcome label.
- **Do** give every new live or waiting state a glow, and remove it the moment the state ends.
- **Do** re-ink, not reshape, for the light scheme: change token values under `prefers-color-scheme: light`, keep geometry and motion identical.
- **Do** keep every animation behind the global `prefers-reduced-motion` cut-off.

### Don't:

- **Don't** render messages as chat bubbles, facing avatars or typing indicators; the thread is a receipt.
- **Don't** fill a resting surface with ember, or use ember for success; ember is live, waiting or actionable.
- **Don't** use green for anything except the Verified stamp and the safety note.
- **Don't** add drop shadows to lift ordinary surfaces; depth is recess and glow.
- **Don't** show hidden reasoning, or present synthetic preview fixtures as proof that a live task succeeded.
- **Don't** introduce a second display face or a bold weight of Departure Mono; it ships one regular weight.
