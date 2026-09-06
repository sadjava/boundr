# Design Spec — Boundr Labeling Tool (v2: warm light theme)

Rebuilt around your four colors — wine maroon `#810B38`, dark maroon-brown
`#541A1A`, tan/beige `#E6D5C4`, cream `#FAF6F0` — as a light, warm,
Christmas-adjacent palette. Four colors aren't enough for a full system
(no hover states, no way to separate "destructive" from "brand," no way to
tell seven action types apart on the timeline), so I derived tints/shades
from your base and added a small number of new hues only where functionally
required. Every addition is called out below.

---

## 1. Color

### Surfaces (light, warm cream — near-white, not gray)
| Token | Hex | Source | Use |
|---|---|---|---|
| `bg-app` | `#FAF6F0` | **your cream, lifted toward white** | Outermost background |
| `bg-panel` | `#FFFCFA` | near-white cream | Top bar, side panel, timeline panel — sits slightly lighter than `bg-app` so panels read as raised, without a drop shadow |
| `bg-panel-raised` | `#F3E8DA` | between cream/tan | Row hover, dropdown open state, input fields |
| `bg-canvas-well` | `#2B1512` | new — near-black warm brown | Video preview surround only (see note) |
| `border-hairline` | `#E6D5C4` | **your tan, lightened** | 1px dividers between panels/rows |
| `border-strong` | `#D2BDA6` | darkened tan | Input borders, unfocused control outlines |

**Note on the canvas well:** the video preview frame stays dark even though
the rest of the UI is light. This isn't inconsistency — it's standard
practice in every video tool (Premiere, Resolve, etc.): a dark surround
prevents the UI's color from biasing how the editor perceives the footage's
actual color, and it reduces glare during long sessions. Using a warm
near-black (brown-black, not gray-black) keeps it from feeling like a cold
hole punched in a warm page — it reads as a stage the video sits on.

### Text
| Token | Hex | Source | Use |
|---|---|---|---|
| `text-primary` | `#541A1A` | **your dark maroon-brown** | Headings, labels, values — replaces black; softer, warmer, still >7:1 contrast on cream |
| `text-secondary` | `#86604F` | tint of text-primary toward beige | Metadata, timestamps, secondary labels |
| `text-tertiary` | `#B49984` | lighter tint | Placeholder text, disabled state, "none" values |

### UI accent — one job only: interactive / selected / primary action
| Token | Hex | Source | Use |
|---|---|---|---|
| `accent-primary` | `#810B38` | **your wine maroon** | Primary button fill (Run model), focus rings, playhead, selection outline |
| `accent-primary-hover` | `#9E1345` | lightened | Hover |
| `accent-primary-active` | `#690930` | darkened | Pressed |
| Text on accent fill | `#FFFCFA` | cream tint | Always cream text on a wine-filled button, never cool white |

### Semantic status — reserved, never reused elsewhere
| Token | Hex | Use |
|---|---|---|
| `status-success` | `#2F5233` (deep pine green — fits the Christmas palette) | "Completed" badge only |
| `status-warning` | `#B8860B` (dark gold) | "In progress" / unsaved state |
| `status-danger` | `#B3261E` (brick red — new; kept distinct in hue from the wine accent so "delete" never gets mistaken for "primary action") | Delete/Remove buttons, destructive confirms |
| `status-danger-bg` | `#B3261E14` | Destructive button hover fill (8% alpha) |

Why not use your dark maroon-brown for danger: it's already carrying
`text-primary`, and reusing one hex for both "body text" and "this will
delete your data" is exactly the kind of collapsed-meaning problem the
original orange had. Brick red is close enough to feel like it belongs to
the palette, far enough in hue from wine to never be confused with a
primary button.

### Action-type categorical palette (7, for the timeline)
This is the one place the palette needs real hue variety — these are what
the user scans to tell action types apart, so they can't all cluster in one
warm-brown range or they'll be indistinguishable at a glance.

| # | Name | Hex |
|---|---|---|
| 1 | Terracotta | `#C1502E` |
| 2 | Marigold | `#C9932B` |
| 3 | Moss Green | `#5C6B3D` |
| 4 | Rust | `#8C4A2F` |
| 5 | Dusty Rose | `#B5657A` |
| 6 | Deep Plum | `#5B3A5E` |
| 7 | Bronze Ochre | `#8A6D3A` |

Deliberately kept distinct from `accent-primary` (wine) and `status-danger`
(brick red) so neither "selected" nor "delete" ever gets misread as an
action-type color.

**Honest caveat:** three of these (Terracotta, Rust, Bronze Ochre) are all
warm orange-browns and will be close for anyone with a red-green color
vision deficiency, or just at a glance on a small chip. Don't rely on hue
alone — every segment block and list row already carries the label text and
a left-border chip (below), so color is always a *second*, not *only*,
signal. If you find users mixing up two adjacent categories in practice,
swap one of the three (Rust is the best candidate to replace) for something
further out, like a slate or navy — a single cool note against seven warms
reads as intentional, not off-brand.

---

## 2. Typography

Unchanged from before — this part isn't a color decision:
- **UI text:** Inter (or system-ui).
- **Timecodes/durations only:** JetBrains Mono, tabular figures, so numbers
  don't jitter as the playhead moves (`0:01 / 0:10`, `0.73s–2.31s`).
- Sentence case throughout — no tracked-out caps. Replace `COMPLETED` with
  a small `status-success` dot + "Completed" in sentence case.

---

## 3. Components

### Buttons
Flat, 4px radius, no shadow, no gradient.
- **Primary** (Run model): `accent-primary` fill, `#FFFCFA` text. Hover →
  `accent-primary-hover`.
- **Secondary** (Previous, Next, Save): transparent, 1px `border-strong`,
  `text-primary` label. Hover → `bg-panel-raised` fill.
- **Destructive** (Delete, Remove): transparent, 1px `status-danger` border,
  `status-danger` text. Hover → `status-danger-bg` fill. Never a resting
  solid-red fill — that's reserved for an actual confirmation step.

### Segments list (right panel)
- 3px left border in the row's categorical hue — primary way to
  differentiate rows.
- Label: `text-primary` 500 weight. The `· none` suffix in `text-tertiary`
  so an unset object visibly reads as empty, not as a filled value.
- Timecodes in JetBrains Mono, `text-secondary`.
- Remove: icon-only `×`, `text-tertiary` at rest, `status-danger` on hover —
  not a permanent red-outlined button per row (twelve resting red buttons
  reads as an alarm panel).
- Selected/active row: `bg-panel-raised` + the row's categorical hue at 10%
  as a full-row wash.

### Timeline track
- Track row label chips: filled in the categorical hue, `text-primary` or
  `bg-panel` text depending on which contrasts better against that hue.
- Empty track background: `bg-panel-raised` (light backgrounds need a
  visible-but-quiet empty state, unlike a dark theme where near-black reads
  as "nothing here" — on cream, pure `bg-app` would look identical to empty
  space, so give tracks a faint raised fill even when unlabeled).
- Segment blocks: 40% opacity fill of the categorical hue (light
  backgrounds need less fill than dark ones for the same visibility — 55%
  from a dark-theme spec would look muddy on cream), 1.5px full-opacity
  border, 3px radius.
- Selected block: 70% fill opacity + 2px `accent-primary` outer ring.
- Keyframe diamonds: 8px, full-opacity categorical hue, with a
  `text-primary` (dark) 1px stroke — not white, since white won't register
  against a light page.
- Playhead: 1px vertical line + small filled triangle, `accent-primary`.
- Time ruler: JetBrains Mono, `text-tertiary`.

### Scrubber
Track: 2px, `border-strong`. Filled portion: `accent-primary`. Thumb: 12px
`accent-primary` circle, grows to 14px only while dragging/hovering.

### Dropdown (Model: Overlap)
`border-strong` outline, `bg-panel-raised` when open, custom chevron.
Highlighted option: `accent-primary` 2px left border on `bg-panel-raised`.

---

## 4. Motion

Same as before — hover/select transitions only (100–150ms), no
load-in animation, scrubber thumb grows only on interaction. Respect
`prefers-reduced-motion`.

---

## 5. Accessibility

- `text-primary` (`#541A1A`) on `bg-app` (`#FAF6F0`) is ~9:1 contrast — well
  above the 4.5:1 floor.
- `text-tertiary` (`#B49984`) on `bg-app` is the tightest pair in the
  system — verify it in your actual renderer at the sizes you use it
  (metadata/placeholder only, never body text).
- Visible focus ring: 2px `accent-primary`, 2px offset, on every
  interactive element.
- See the categorical-palette caveat above — this is the system's real
  accessibility risk area, not the surfaces or text colors.

---

## Summary

Cream and tan carry the whole app as quiet background; wine maroon is the
single accent that means "this is interactive or selected"; brick red and
pine green are locked to destructive/success only; and the seven
terracotta-to-plum hues exist solely so the timeline is scannable — with an
explicit note that three of them are close enough to need the redundant
text/border cues, not color alone.