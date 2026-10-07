# Extension UI direction

Use a restrained Vercel monochrome direction for this developer-facing panel.

- Type: system sans for controls and body; system monospace for protocol data.
- Colors: near-black ink (`#111111`), white canvas (`#ffffff`), neutral gray
  separators, and one calm green state accent (`#18794e`).
- Radius: 4px and 6px only.
- Spacing: 4px base scale (`4`, `8`, `12`, `16`, `24`, `32`).
- Motion: short opacity and transform feedback for connection transitions;
  honor reduced motion and avoid decorative animation.

The panel prioritizes the connection state, current task controls, pending
confirmation, and runtime event history. Until the native host reports a
session, controls describe unavailable behavior and cannot imply a task ran.
