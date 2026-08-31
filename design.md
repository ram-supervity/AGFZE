# Adani Command Center Design System (CCDS)

> **Source of truth**: Reverse-engineered directly from the Figma file **"Design System CC"** (`fileKey: xzy7YzlLGft4NqEDpv54jx`), Cover page title: *"Supervity Command Centers — CCDS Components — New design system — Beta version (Adani)"*.
> This document is generated from live Figma data: page metadata, published component/variant names, Figma Variables (Design Tokens + Semantic Colors collections), text styles, and rendered code (CSS/Tailwind) pulled via the Figma MCP server.
> Every token, value, and component listed here was observed directly in the file. Where the MCP could not expose an exact value (e.g., a primitive ramp step's hex when no on-canvas instance used it), the item is listed by **name and description only**, and flagged with an **⚠️ Assumption** callout instead of a fabricated value. Nothing in this document is invented.

**Design System**: Design System CC (CCDS) · **Product**: Supervity Command Centers · **Client**: Adani · **Status**: Beta
**Library key**: `lk-253b8441e4f74b0fb782d0e307cd66a30c42e0e9ff31434665f02ce023244dd048b5f8f82680ebd01ebdac9ae97ad3397836411565b1cc146312968497045638`

---

## Table of Contents

1. [Foundation](#1-foundation)
   1.1 [Brand Philosophy](#11-brand-philosophy)
   1.2 [Design Principles](#12-design-principles)
   1.3 [Color System](#13-color-system)
   1.4 [Typography](#14-typography)
   1.5 [Spacing System](#15-spacing-system)
   1.6 [Radius](#16-radius)
   1.7 [Elevation & Shadow](#17-elevation--shadow)
   1.8 [Borders](#18-borders)
   1.9 [Opacity](#19-opacity)
   1.10 [Icon Sizes](#110-icon-sizes)
   1.11 [Grid System & Breakpoints](#111-grid-system--breakpoints)
   1.12 [Z-Index / Layering](#112-z-index--layering)
   1.13 [Motion & Animation](#113-motion--animation)
   1.14 [Iconography](#114-iconography)
   1.15 [Illustration Guidelines](#115-illustration-guidelines)
2. [Design Tokens](#2-design-tokens)
3. [Components](#3-components)
4. [Layout](#4-layout)
5. [Interaction](#5-interaction)
6. [Accessibility](#6-accessibility)
7. [Documentation & Governance](#7-documentation--governance)
8. [Developer Handoff](#8-developer-handoff)

---

## 1. Foundation

### 1.1 Brand Philosophy

The Cover page of the file frames the system as:

> "Supervity Command Centers — **CCDS Components** — New design system — **Beta version (Adani)**"

CCDS ("Command Center Design System") is the design language for **Supervity's Command Center product**, customized for the **Adani** deployment (beta). A command center is an operations/monitoring surface (ticket queues, SLA tracking, audit trails, AI-assisted triage), so the system is optimized for:

- **Data density with clarity** — compact table rows, small type steps (9–14px) for metadata, larger type reserved for primary headings and hero/marketing surfaces only.
- **Status at a glance** — an unusually large, hue-complete "pill" color system (13 hues × bg/text/border) exists specifically to color-code ticket/record status, priority, and category badges.
- **Speed and confidence in triage workflows** — snappy motion durations (100ms hover/press feedback) and a `information-bold` action color reserved for secondary actions like "Take Over".
- **AI-augmented operations** — a dedicated brand gradient (`#4f39f5 → #cc3478`, violet‑to‑magenta) is reserved for AI-forward actions/labels (e.g., "Ask VIQAI") and an "AI Ready" Empty State variant exists in the core Empty State component.
- **Enterprise theming** — the "Beta version (Adani)" label on the cover, plus the file being a shared **team library** ("Design System CC"), indicates the system is built to be white-labelled per client/tenant on top of a shared token core.

### 1.2 Design Principles

Inferred from consistent, repeated patterns across the file (⚠️ synthesized from evidence, not an explicit "Principles" page found in the file):

| Principle | Evidence in file |
|---|---|
| **Token-driven, not hard-coded** | Dedicated "Spacing & Grid Documentation" page exists purely to document `space.*`, `radius.*`, breakpoints and z-index as tokens. |
| **Systematic states, not one-offs** | Every Button variant is fully cross-multiplied: 4 styles × 5 sizes × 5 states × 5 content-arrangements = **500 documented button symbols** alone. |
| **Composable primitives → semantic → component** | Figma Variables are split into two explicit collections: **"Design Tokens"** (primitives: Gray/Purple/Pink/Red/Green/Blue/Dark Blue/Stone ramps, Space, Radius, Dimension, Icon Size, Opacity, Border Width, Motion) and **"Semantic colors"** (`color/background/*`, `color/text/*`, `color/border/*`, `color/icon/*`, `elevation/surface/*`, `pill/*`). |
| **Accessible defaults, escape hatches for status** | Neutral defaults (`color/text/default #030712`, `color/background/neutral #f3f4f6`) are used broadly; saturated hues are reserved for status/pill contexts only. |
| **Documented, not tribal knowledge** | The file contains a self-referential "✦ Spacing & Grid Documentation" and "✦ Layout System — Showcase" page whose sole purpose is developer/designer education — a strong signal of documentation-first culture. |

### 1.3 Color System

#### 1.3.1 Primitive Color Ramps ("Design Tokens" collection → `color/*`)

Numeric ramps use a **100–1000 scale (11 steps: 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 1000)** — note this is a wider/denser scale than the common Tailwind 50–950 convention. Confirmed ramps found in the library:

| Ramp | Steps observed | Usage description (from Figma variable description) |
|---|---|---|
| `Gray` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000 | Neutral UI chrome — backgrounds, borders, subtle text |
| `Stone` | 200, 500, 700, 800 (partial sample observed) | Warm neutral ramp — alternative to Gray for warmer surfaces |
| `Purple` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 1000 | **Primary brand color** — CTAs, active states, links, focus rings |
| `Pink` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000 | Accent, marketing, discovery — alternative ramp |
| `Red` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000 | Danger, error, destructive action ramp |
| `Green` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000 | Success, confirmation, positive feedback ramp |
| `Blue` | 100, 200, 300, 400, 500, 600, 700, 800, 900, 950 | Information & secondary accent ramp |
| `Dark Blue` | 300, 500, 600, 700 (partial sample observed) | Deep blue ramp — used for charts, dark surfaces |
| `Amber` (pill only, no primitive confirmed) | — | Warning ramp (see Pill tokens below) |

> ⚠️ **Assumption**: The MCP variable search returns token **names + descriptions** but not resolved hex per ramp step (Figma's `get_variable_defs` tool requires an active canvas selection, which is unavailable in this headless flow). Only the hex values below were resolved indirectly, by inspecting components that consume these variables via rendered CSS. **Do not guess intermediate ramp values** — pull the authoritative hex from the Figma Variables panel (`Design Tokens` collection) before implementing.

**Resolved hex values (confirmed via rendered component CSS):**

| Token / context | Resolved value | Where observed |
|---|---|---|
| `color/text/default` | `#030712` | Tertiary button label |
| `color/text/inverse` | `#ffffff` | Primary/Danger/Secondary button labels |
| `color/background/neutral` (≈ `Gray/100`) | `#f3f4f6` | Tertiary button background |
| `color/border/default` (≈ `Gray/200`) | `#e5e7eb` | Tertiary button border, grid/documentation dividers |
| `color/background/danger-bold` | `#d70000` | Danger button background |
| `color/background/information-bold` | `#615fff` | Secondary button background |
| Brand gradient start (≈ `Purple/500`) | `#4f39f5` | Primary button background, "Ask VIQAI" label, doc page H1 gradient |
| Brand gradient end (≈ `Pink/600`) | `#cc3478` | Same gradient, stop at 99.9% |
| Doc-page neutrals | `#6b7280`, `#111827`, `#9ca3af`(approx), `#f9fafb` | Spacing & Grid Documentation page (internal doc styling, Inter font) |

#### 1.3.2 Semantic Color Tokens ("Semantic colors" collection → `color/*`)

Semantic tokens are **aliases that reference the primitive ramps** and are the tokens components should consume — never a raw hex or raw `Gray/500` reference.

**Text**

| Token | Purpose |
|---|---|
| `color/text/default` | Primary UI text (`#030712`) |
| `color/text/subtle` | Secondary/muted text |
| `color/text/inverse` | Text on filled/dark backgrounds (white) |
| `color/text/brand` | Brand-colored text/links |
| `color/text/danger` | Error/destructive text |
| `color/text/success` | Success/confirmation text |
| `color/link/default` | Default hyperlink color |

**Icon**

| Token | Purpose |
|---|---|
| `color/icon/default` | Default icon color |
| `color/icon/subtle` | De-emphasized icon color |
| `color/icon/inverse` | Icon on filled/dark backgrounds |
| `color/icon/brand` | Brand-colored icon |
| `color/icon/danger` | Error icon |
| `color/icon/success` | Success icon |
| `color/icon/warning` | Warning icon |

**Border**

| Token | Purpose |
|---|---|
| `color/border/default` | Default control/card border (`#e5e7eb`) |
| `color/border/bold` | Emphasized border |
| `color/border/brand` | Brand-colored border (e.g., focused/selected) |

**Background**

| Token | Purpose |
|---|---|
| `color/background/Surface-default` | Default page/panel surface |
| `color/background/neutral` | Neutral fill (`#f3f4f6`) |
| `color/background/neutral-bold` | Emphasized neutral fill |
| `color/background/input` | Form input fill |
| `color/background/disabled` | Disabled control fill |
| `color/background/selected` | Selected row/item fill |
| `color/background/brand-bold` | Solid brand fill (primary CTA alt.) |
| `color/background/danger` | Danger tint background |
| `color/background/danger-bold` | Solid danger fill (`#d70000`) |
| `color/background/warning` | Warning tint background |
| `color/background/warning-bold` | Solid warning fill |
| `color/background/success` | Success tint background |
| `color/background/success-bold` | Solid success fill |
| `color/background/information` | Information tint background |
| `color/background/information-bold` | Solid information fill (`#615fff`) |
| `color/background/discovery` | Discovery/AI-adjacent tint background |

**Elevation surfaces** (state-aware surface tokens — see [§1.7](#17-elevation--shadow))

`elevation/surface/default`, `sunken`, `raised`, `raised-hovered`, `raised-pressed`, `overlay`, `overlay-hovered`, `overlay-pressed`, `hovered`, `pressed`

**Pill / status tag color families** (bg + text + border per hue — the color system that powers Badge/Tag/Chip):

| Hue | Tokens |
|---|---|
| `purple` | `pill/purple/bg`, `pill/purple/text`, `pill/purple/border` |
| `pink` | `pill/pink/bg`, `pill/pink/text`, `pill/pink/border` |
| `blue` | `pill/blue/bg`, `pill/blue/text`, `pill/blue/border` |
| `sky` | `pill/sky/bg`, `pill/sky/text`, `pill/sky/border` |
| `red` | `pill/red/bg`, `pill/red/text`, `pill/red/border` |
| `mint` | `pill/mint/bg`, `pill/mint/text`, `pill/mint/border` |
| `teal` | `pill/teal/bg`, `pill/teal/text`, `pill/teal/border` |
| `cyan` | `pill/cyan/bg`, `pill/cyan/text`, `pill/cyan/border` |
| `rose` | `pill/rose/bg`, `pill/rose/text`, `pill/rose/border` |
| `amber` | `pill/amber/bg`, `pill/amber/text`, `pill/amber/border` |
| `green` | `pill/green/bg`, `pill/green/text`, `pill/green/border` |
| `yellow` | `pill/yellow/text` (+ bg/border implied) |
| `orange` | `pill/orange/text` (+ bg/border implied) |

> This is a **13-hue status palette** — one of the richest parts of the system. Use it for Badge/Tag/Chip variants that need distinguishable, non-sequential categories (ticket types, departments, integrations) as opposed to the 5 semantic states (brand/danger/warning/success/information) used for meaning-bearing status (error, success, etc).

#### 1.3.3 Legacy / Screen-Level Token Layer ⚠️ Observation

Real product screens embedded in the file (the ticket-inbox "Menu Bar" and ticket-detail header under the Layout page) render with a **second, numeric-scale token vocabulary** that does not match the `color/*` semantic naming above:

```
--text/primary: #1a1a1a      --text/secondary: #475569      --text/tretiary: #64748b
--border/default: #e2e8f0    --gray/100: #f3f4f6
--primary/50: #f5f3ff  --primary/400: #a78bfa  --primary/800: #5b21b6
--secondary/50: #eff6ff --secondary/400: #60a5fa --secondary/800: #1e40af
--warning/50: #fffbeb  --warning/800: #92400e
--scale/300: 10px  --scale/400: 12px  --scale/500: 14px  --scale/600: 16px
--font-family/heading: 'Funnel Display'
```

> ⚠️ **This looks like an older/parallel token system** (a `primary/50…900`, `secondary/50…900`, `scale/100…900` Tailwind-style vocabulary) still driving some real Command Center screens, while the newer `Design Tokens` + `Semantic colors` Figma Variable collections (documented above) represent the current, canonical system. **Flag for consolidation** — new components should bind to the current `color/*`, `Space/*`, `Radius/*` variables, not the legacy `scale/*` / `primary-50-900` set. Both are documented here for completeness and migration planning.

### 1.4 Typography

#### 1.4.1 Font Families

| Family | Weights observed | Where used |
|---|---|---|
| **Funnel Display** | Light, Regular, Medium, SemiBold, Bold | **Primary UI typeface.** Confirmed on: Button labels, Cover hero headings, ticket header titles, Menu Bar inbox list, all "Command Center" screen text. Referenced via variable `font-family/heading`. |
| **Plus Jakarta Sans** | Bold, SemiBold | Used only on the internal "✦ Spacing & Grid Documentation" page (section titles, gradient headings) — this is a **documentation-page-only typeface**, not applied to shipped components. |
| **Inter** | Regular, Medium | Used only on the internal documentation page for body/caption copy (token labels, grid captions) — likewise **documentation-only**. |

> ⚠️ **Observation**: Named text styles ("Heading/H1/Bold", "Body/Body MD/Medium", etc., see below) do not declare a hardcoded family — they resolve through the `font-family/heading` variable, which is bound to **Funnel Display**. Treat Funnel Display as the system's single product typeface; Plus Jakarta Sans/Inter are meta/documentation-only and should not be shipped in product UI.

#### 1.4.2 Named Text Styles

**Heading scale** (`Heading/H{1-6}/{weight}`), weights: Regular · Medium · Semi Bold · Bold

| Style | Description |
|---|---|
| H1 | Page title |
| H2 | Section title |
| H3 | Sub-section title |
| H4 | Card/panel heading |
| H5 | Widget/sidebar heading |
| H6 | Label-level heading |

**Body scale** (`Body/Body {XS,SM,MD,LG,XL}/{weight}`), weights: Regular · Medium · Semi Bold · Bold

| Style | Description |
|---|---|
| Body XL | Intro paragraphs, marketing copy |
| Body LG | Article body, longer descriptions |
| Body MD | Default UI body text, form labels |
| Body SM | Secondary copy, table cells |
| Body XS | Captions, helper text, metadata |

**Label scale** (`Label/Label {MD,LG}/{weight}`), weights: Regular · Medium · Semi Bold · Bold

| Style | Description |
|---|---|
| Label LG | Large button labels, primary nav |
| Label MD | Default button labels, tab labels |

> ⚠️ **Observed inconsistency**: The rendered Primary Button (MD size) actually uses **`Body/Body MD/Medium`** (16px/20px, weight 500) rather than the `Label/Label MD` style whose own description says "Default button labels." Confirm in Figma whether Buttons should be re-bound to `Label MD` for stricter semantic correctness — documented here as-observed, not corrected.

#### 1.4.3 Confirmed Type Sizes (from rendered instances)

| Context | Size / line-height | Weight | Family |
|---|---|---|---|
| Cover — "CCDS Components" | 124px | Bold | Funnel Display |
| Cover — "New design system" | 96px, tracking 3.84px | Light | Funnel Display |
| Cover — "Supervity Command Centers" | 32px, tracking 0.96px, uppercase | Regular | Funnel Display |
| Cover — "Beta version (Adani)" | 28px, tracking 0.84px, uppercase | Regular | Funnel Display |
| Doc page — H1 gradient title | 40px | Bold | Plus Jakarta Sans (doc-only) |
| Doc page — section title | 22px | Bold | Plus Jakarta Sans (doc-only) |
| Button label (MD) | 16px / 20px | Medium (500) | Funnel Display |
| Ticket header title ("H2/Bold") | 24px | Semibold (600) | Funnel Display, via `font-family/heading` |
| Ticket subtitle ("Subtitle/Medium") | 14px / 20px (`scale/500`) | Medium (500) | Funnel Display |
| Ticket foot text ("Foot/Medium") | 12px / 16px (`scale/400`) | Medium (500) | Funnel Display |
| Inbox item title | 12px / 16px (`scale/400`) | Medium | Funnel Display |
| Inbox item preview / timestamp | 9–11px | Regular | Funnel Display |
| Doc page space/radius labels | 9–14px | Regular/Medium | Inter (doc-only) |

### 1.5 Spacing System

**Collection**: `Design Tokens → float → Space/*` — a **4px base grid, 14 steps, 0 → 80px**.

| Token | Value |
|---|---|
| `space.0` | 0px |
| `space.025` | 2px |
| `space.050` | 4px |
| `space.075` | 6px |
| `space.100` | 8px |
| `space.150` | 12px |
| `space.200` | 16px |
| `space.250` | 20px |
| `space.300` | 24px |
| `space.400` | 32px |
| `space.500` | 40px |
| `space.600` | 48px |
| `space.800` | 64px |
| `space.1000` | 80px |

**Dimension tokens** (component sizing, distinct from spacing):

| Token | Value | Usage |
|---|---|---|
| `Dimension/control-sm` | 28px | Small button / input height |
| `Dimension/control-md` | 36px | Default button / input / select height |
| `Dimension/control-lg` | 44px | Large button, prominent input (touch-friendly) |
| `Dimension/control-xl` | 52px | Extra-large CTA button |

### 1.6 Radius

**Collection**: `Design Tokens → float → Radius/*` — none(0) → full(9999px).

| Token | Value | Usage |
|---|---|---|
| `radius.none` | 0px | — |
| `radius.small` | 4px | — |
| `radius.medium` | 8px | Buttons, cards, most controls (**default**) |
| `radius.large` | 12px | — |
| `radius.xlarge` | 16px | Hero cards, feature surfaces |
| `radius.full` | 9999px ("full") | Pills, avatars, circular controls |

> Observed applied radii on real components: Button = 6px (between `small` and `medium` — a **component-level override**, see [§2.4](#24-component-tokens)); Menu Bar container = 8px; ticket status pill = 6px; grid preview boxes = 8px.

### 1.7 Elevation & Shadow

No dedicated Figma **Effect styles** (drop-shadow presets) were found; elevation is expressed as **semantic surface color tokens** (`elevation/surface/*`) rather than shadow presets, plus one confirmed raw shadow value on a real component:

| Elevation surface token | Semantic meaning |
|---|---|
| `elevation/surface/sunken` | Recessed/inset areas (e.g., search inputs inside a panel) |
| `elevation/surface/default` | Base card/panel surface |
| `elevation/surface/raised` | Elevated card (hover-lift) |
| `elevation/surface/raised-hovered` / `raised-pressed` | Raised surface interaction states |
| `elevation/surface/overlay` | Modal/Drawer/Popover surface |
| `elevation/surface/overlay-hovered` / `overlay-pressed` | Overlay surface interaction states |
| `elevation/surface/hovered` / `pressed` | Generic hover/press surface tint |

**Confirmed shadow value** (Menu Bar / Inbox panel):
```css
box-shadow: 0px 4px 12px 0px rgba(0, 0, 0, 0.03);
```
> ⚠️ **Assumption**: Only one elevation shadow value was directly observed. A full elevation scale (e.g., `elevation.0` … `elevation.4`) likely exists for Cards/Modals/Drawers/Popovers but was not exposed by the available MCP calls. Recommend confirming a shadow scale directly in Figma's Effect Styles panel before hard-coding additional shadow levels.

### 1.8 Borders

| Token | Value | Usage |
|---|---|---|
| `Border Width/none` | 0px | No border |
| `Border Width/thin` | 1px | Default control, divider, card border (also seen at `0.5px` on some button/pill borders — likely a Figma-only hairline rendering artifact of a 1px stroke at certain scale factors) |
| `Border Width/thick` | 2px | Focus ring, selected/active state border |

Border **color** tokens: `color/border/default`, `color/border/bold`, `color/border/brand`, plus the 13 `pill/{hue}/border` tokens (see [§1.3.2](#132-semantic-color-tokens-semantic-colors-collection--color)).

### 1.9 Opacity

**Collection**: `Design Tokens → float → Opacity/*`

| Token | Value | Usage |
|---|---|---|
| `Opacity/0` | 0 | Fully transparent |
| `Opacity/100` | 1 | Fully opaque |
| `Opacity/hover` | 0.08 | Hover overlay on neutral surfaces |
| `Opacity/pressed` | 0.12 | Pressed/active state overlay |
| `Opacity/disabled` | 0.4 | Disabled controls and dimmed content |
| `Opacity/loading` | 0.6 | Loading skeleton placeholder |
| `Opacity/scrim` | 0.5 | Modal / Drawer backdrop scrim |

### 1.10 Icon Sizes

**Collection**: `Design Tokens → float → Icon Size/*`

| Token | Value | Usage |
|---|---|---|
| `Icon Size/small` | 16px | Inline with body text (SM/MD controls) |
| `Icon Size/medium` | 20px | Default standalone icon |
| `Icon Size/large` | 24px | Navigation icons, prominent UI icons |
| `Icon Size/xlarge` | 32px | Feature icons, empty states, onboarding |

### 1.11 Grid System & Breakpoints

**12-column responsive grid, 24px base gutter, fluid margins.** Four documented breakpoints:

| Breakpoint | Token | Min-width | Columns | Gutter | Margin |
|---|---|---|---|---|---|
| Mobile | `sm` | 480px | 4 | 16px | 16px |
| Tablet | `md` | 768px | 8 | 20px | 24px |
| Desktop | `lg` | 1024px | 12 | 24px | 32px |
| Wide | `xl` | 1280px | 12 | 24px | 40px |

### 1.12 Z-Index / Layering

An explicit, documented stacking scale ("prevents z-index wars"):

| Value | Token | Usage |
|---|---|---|
| 0 | `base` | Default document flow |
| 100 | `raised` | Raised cards, sticky headers |
| 200 | `dropdown` | Menus, selects, comboboxes |
| 300 | `sticky` | Sticky navigation elements |
| 400 | `overlay` | Drawers, side sheets |
| 500 | `modal` | Dialogs, confirmations |
| 600 | `popover` | Tooltips, popovers (above modals) |
| 700 | `toast` | Notifications — always on top |

### 1.13 Motion & Animation

**Collection**: `Design Tokens → float/string → Motion/*`

| Token | Value | Usage |
|---|---|---|
| `Motion/duration/instant` | 0ms | No animation, immediate response |
| `Motion/duration/fast` | 100ms | Hover, press feedback (snappy) |
| `Motion/duration/medium` | 200ms | Standard enter/exit transitions |
| `Motion/duration/slow` | 350ms | Large surface animations (modal, sheet) |
| `Motion/easing/linear` | `linear` | Constant-speed (spinners, progress bars) |
| `Motion/easing/standard` | `cubic-bezier(0.2, 0, 0, 1)` | Default for most UI transitions |
| `Motion/easing/enter` | `cubic-bezier(0, 0, 0, 1)` | Elements entering the screen |
| `Motion/easing/exit` | `cubic-bezier(0.2, 0, 1, 1)` | Elements leaving the screen |

**Motion principles** (⚠️ inferred from token intent):
- **Snappy feedback, deliberate transitions**: interactive states (hover/press) resolve in 100ms; structural changes (modal/sheet open) take up to 350ms.
- **Directional easing**: enter/exit use distinct curves rather than a single symmetric ease, matching Material-style "emphasized" motion — entrances decelerate into place, exits accelerate away.
- **Linear reserved for continuous motion** (spinners, indeterminate progress bars) — never for discrete state changes.

### 1.14 Iconography

- **Icon source**: [Lucide Icons](https://lucide.dev/icons/) — this is the icon set the design/dev team is drawing from for this system. Treat it as the canonical glyph library for implementation: any icon referenced as a component instance in Figma should be matched to its equivalent Lucide icon by name/shape when building the corresponding UI in code, rather than hand-drawing or sourcing a glyph from a different icon set.
- Icons are supplied as **component instances** (`icon` instances referenced inside Empty States, ticket header action buttons, Menu Bar search/filter controls), not static SVGs authored ad hoc — confirming a dedicated Icon component/library exists in the file (its own page was not directly reachable via the tools available in this session). ⚠️ The Figma-side icon component wrappers were not directly inspected glyph-by-glyph; **Lucide is the confirmed source of truth for the actual glyphs** per the team's stated intent.
- Icon sizing is token-driven: 16 / 20 / 24 / 32px (`Icon Size/*`, [§1.10](#110-icon-sizes)) — this maps directly onto Lucide's `size` prop (Lucide defaults to 24px/2px stroke; override `size` to match the `Icon Size/*` token in use, and keep `stroke-width` consistent, e.g. `2` at the default scale).
- Icon color follows semantic icon tokens (`color/icon/default|subtle|inverse|brand|danger|success|warning`) rather than raw hex — icons should always recolor via `currentColor` or the bound variable so they track text/semantic state. Lucide icons render as inline SVG with `stroke="currentColor"` by default, which makes this pattern a natural fit — no per-icon color overrides needed, just set the CSS `color` on the wrapping element/semantic token.
- ⚠️ **Assumption**: An icon library page almost certainly exists in Figma (referenced everywhere as instances) but its full glyph set/grid rules could not be enumerated directly in this session — Icon Size tokens above are confirmed, the exact glyph-to-Lucide-name mapping is not. Recommend producing a glyph inventory (Figma icon name → Lucide icon name) as a follow-up so every icon instance has an unambiguous code equivalent.

### 1.15 Illustration Guidelines

- Empty State components use **illustrative icon compositions** (a 48×48px rounded container housing a 20×20px icon instance, per the "No results found" / "All tasks done!" / "AI assistant ready" / "Access restricted" examples) rather than full custom illustrations.
- ⚠️ **Assumption**: No dedicated "Illustration" component set or illustration style guide was found in the reachable parts of the file. The system appears to favor **icon + copy + optional CTA** empty-state compositions over bespoke illustrations — treat any illustration usage as inferred, not confirmed, until validated against the file's Empty State / onboarding pages directly in Figma.

---

## 2. Design Tokens

### 2.1 Token Architecture / Hierarchy

The file organizes tokens into **two Figma Variable collections**, plus text/effect Styles, plus one legacy layer:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PRIMITIVE  — "Design Tokens" collection                  │
│    Gray / Stone / Purple / Pink / Red / Green / Blue /      │
│    Dark Blue color ramps (100–1000) · Space · Radius ·      │
│    Dimension · Icon Size · Opacity · Border Width · Motion  │
└───────────────────────────┬───────────────────────────────────┘
                            │ referenced by
┌───────────────────────────▼───────────────────────────────────┐
│ 2. SEMANTIC   — "Semantic colors" collection                │
│    color/text/* · color/icon/* · color/border/* ·            │
│    color/background/* · elevation/surface/* · pill/{hue}/*  │
└───────────────────────────┬───────────────────────────────────┘
                            │ consumed by
┌───────────────────────────▼───────────────────────────────────┐
│ 3. COMPONENT  — bound inside component instances             │
│    e.g. Button background = color/background/danger-bold     │
│    Button radius = 6px (component override, not a raw token)│
└───────────────────────────┬───────────────────────────────────┘
                            │ modified by
┌───────────────────────────▼───────────────────────────────────┐
│ 4. STATE      — Hover / Pressed / Focused / Disabled variants│
│    layered on top via Opacity/* tokens or explicit color swap│
└─────────────────────────────────────────────────────────────┘

  (parallel, legacy) ⚠️ scale/* · primary-50…900 · secondary-50…900
                        — observed on real screens, not part of the
                        two variable collections above. See §1.3.3.
```

**Alias pattern**: Semantic tokens are named `color/{category}/{intent}` (e.g. `color/background/danger-bold`) and resolve to a primitive ramp step (e.g. `Red/600`). Components must bind to **semantic** tokens only; primitives should never be referenced directly from a component or from application code.

### 2.2 Primitive Tokens (reference table)

| Category | Token pattern | Examples |
|---|---|---|
| Color — Gray | `Gray/{100…1000}` | `Gray/100` (≈`#f3f4f6`, confirmed), `Gray/200` (≈`#e5e7eb`, confirmed) |
| Color — Stone | `Stone/{200,500,700,800,…}` | Warm-neutral alternative to Gray |
| Color — Purple (brand) | `Purple/{100…1000,950}` | `Purple/500`≈`#4f39f5` (confirmed via gradient) |
| Color — Pink (accent) | `Pink/{100…1000}` | `Pink/600`≈`#cc3478` (confirmed via gradient) |
| Color — Red (danger) | `Red/{100…1000}` | drives `color/background/danger*`, `pill/red/*` |
| Color — Green (success) | `Green/{100…1000}` | drives `color/background/success*`, `pill/green/*` |
| Color — Blue (information) | `Blue/{100…950}` | `Blue/?`≈`#615fff` region drives `information-bold` (⚠️ exact step unconfirmed — the resolved hex sits closer to an Indigo/Violet-Blue mix; verify exact step in Figma) |
| Color — Dark Blue (charts) | `Dark Blue/{300,500,600,700}` | Reserved for chart series / dark surfaces |
| Spacing | `Space/{0,025,050,075,100,150,200,250,300,400,500,600,800,1000}` | 0–80px, 4px base grid |
| Radius | `Radius/{none,small,medium,large,xlarge,full}` | 0–9999px |
| Dimension | `Dimension/control-{sm,md,lg,xl}` | 28 / 36 / 44 / 52px |
| Icon Size | `Icon Size/{small,medium,large,xlarge}` | 16 / 20 / 24 / 32px |
| Opacity | `Opacity/{0,100,hover,pressed,disabled,loading,scrim}` | 0 – 1 |
| Border Width | `Border Width/{none,thin,thick}` | 0 / 1 / 2px |
| Motion duration | `Motion/duration/{instant,fast,medium,slow}` | 0 / 100 / 200 / 350ms |
| Motion easing | `Motion/easing/{linear,standard,enter,exit}` | see [§1.13](#113-motion--animation) |

### 2.3 Semantic Tokens (reference table)

See full tables in [§1.3.2](#132-semantic-color-tokens-semantic-colors-collection--color). Summary by category:

| Category | Token count observed | Pattern |
|---|---|---|
| Text | 7+ (`default`, `subtle`, `inverse`, `brand`, `danger`, `success`, link/`default`) | `color/text/{intent}` |
| Icon | 7+ (`default`, `subtle`, `inverse`, `brand`, `danger`, `success`, `warning`) | `color/icon/{intent}` |
| Border | 3+ (`default`, `bold`, `brand`) | `color/border/{intent}` |
| Background | 16+ (`Surface-default`, `neutral`, `neutral-bold`, `input`, `disabled`, `selected`, `brand-bold`, `danger`, `danger-bold`, `warning`, `warning-bold`, `success`, `success-bold`, `information`, `information-bold`, `discovery`) | `color/background/{intent}` |
| Elevation surface | 10 (`sunken`, `default`, `raised`, `raised-hovered`, `raised-pressed`, `overlay`, `overlay-hovered`, `overlay-pressed`, `hovered`, `pressed`) | `elevation/surface/{state}` |
| Pill (status tags) | 13 hues × up to 3 (bg/text/border) = ~30+ | `pill/{hue}/{bg,text,border}` |

### 2.4 Component Tokens

Component-level values that **override or compose** foundation tokens rather than referencing them 1:1 — captured directly from rendered instances:

| Component | Property | Value | Foundation token it deviates from |
|---|---|---|---|
| Button | Corner radius | 6px | Between `radius.small` (4px) and `radius.medium` (8px) — a bespoke button-only radius |
| Button | Horizontal padding | 16px (`space.200`) | ✅ matches token |
| Button | Vertical padding (MD) | 6px | ✅ close to `space.075` (6px) |
| Button Icon-Only (MD) | Size | 36×36px | ✅ matches `Dimension/control-md` |
| Button Icon-Only (LG) | Size | 44×44px | ✅ matches `Dimension/control-lg` |
| Button Icon-Only (XL) | Size | 48×48px | ⚠️ does **not** match `Dimension/control-xl` (52px) — minor scale mismatch, flag for design QA |
| Tertiary Button | Border width | 0.5px | ⚠️ half-pixel hairline — likely a Figma stroke-scaling artifact of `Border Width/thin` (1px) at a non-integer zoom; implement as 1px in code |
| Status pill (ticket header) | Padding | 8px 4px (`space.100`/`space.050`) | ✅ matches tokens |
| Menu Bar panel | Corner radius | 8px | ✅ matches `radius.medium` |
| Menu Bar panel | Border | 1px `color/border/default` (legacy: `#e2e8f0`) | ✅ |
| Menu Bar panel | Shadow | `0px 4px 12px 0px rgba(0,0,0,0.03)` | ⚠️ no matching Effect Style found — see [§1.7](#17-elevation--shadow) |

### 2.5 State Tokens

State changes are implemented via **two different mechanisms** observed in the file — document both, since implementation should pick one consistently:

1. **Opacity-based** (`Opacity/hover` 0.08, `Opacity/pressed` 0.12, `Opacity/disabled` 0.4, `Opacity/loading` 0.6) — an overlay tint approach, suitable for any surface color without needing a discrete "hover color" swatch per component.
2. **Discrete color swap** — the Button component set has fully authored, separate symbols per state (`State=Default|Hover|Pressed|Focused|Disabled`) for every style/size/content combination, i.e., hover/pressed colors are hand-picked per style rather than algorithmically derived from the opacity tokens.

> ⚠️ **Assumption**: Because Button ships discrete state symbols instead of opacity overlays, and no hover/pressed hex could be resolved in this session (only the Default-state hex were pulled), the exact hover/pressed colors per Button style are **not enumerated here** — do not fabricate them. Pull `State=Hover` / `State=Pressed` variants directly from the Button component in Figma before implementing hover/press styles pixel-for-pixel. The **Opacity tokens are confirmed** and are the recommended mechanism for any *new* component's interactive states.

### 2.6 Naming Conventions

| Layer | Convention | Example |
|---|---|---|
| Primitive color | `{Hue}/{100…1000}` | `Purple/500` |
| Semantic color | `color/{category}/{intent[-modifier]}` | `color/background/danger-bold` |
| Elevation | `elevation/surface/{state}` | `elevation/surface/raised-hovered` |
| Pill/status | `pill/{hue}/{bg\|text\|border}` | `pill/amber/text` |
| Spacing | `space.{step}` (dot notation, not slash) | `space.150` = 12px |
| Radius | `radius.{size}` (dot notation) | `radius.medium` = 8px |
| Dimension | `Dimension/control-{size}` | `Dimension/control-lg` |
| Motion | `Motion/{duration\|easing}/{name}` | `Motion/duration/fast` |
| Text style | `{Category}/{Category} {Size}/{Weight}` | `Body/Body MD/Medium`, `Heading/H2/Bold` |
| Component (Figma) | `Property=Value, Property=Value, …` | `Style=Primary, Size=MD, State=Default, Content=Label Only` |

**Rules observed:**
- Color primitives and most float tokens use **`/` as the hierarchy separator** and **PascalCase or Title Case** category names (`Icon Size/small`, `Border Width/thin`).
- The two exceptions are **Space** and **Radius**, which use **dot notation with lowercase** (`space.150`, `radius.medium`) — this inconsistency (`/` vs `.`) exists in the live file and should be **normalized during token export** (recommend standardizing on `/` for the code-facing token set — see [§8](#8-developer-handoff)).
- Component variant properties use **comma-separated `Key=Value` pairs**, alphabetically stable per component (`Style`, `Size`, `State`, `Content` for Button).

### 2.7 Token Hierarchy — Worked Example

```
Purple/500  (primitive, #4f39f5-ish)
   └─ color/background/brand-bold  (semantic alias)
        └─ Button[Style=Primary].background  (component binding, via gradient w/ Pink/600)
             └─ Button[Style=Primary, State=Hover].background  (state override, discrete symbol)
```

### 2.8 Usage Examples

```css
/* ❌ Don't reference a primitive directly in component code */
.button-primary { background: var(--purple-500); }

/* ✅ Do reference the semantic token */
.button-primary { background: var(--color-background-brand-bold); }

/* ✅ Compose state via the Opacity token when no discrete state color exists */
.button-primary:hover {
  background: var(--color-background-brand-bold);
  background-blend-mode: multiply;
  box-shadow: inset 0 0 0 9999px rgba(0,0,0, var(--opacity-hover)); /* 0.08 */
}

/* ✅ Spacing / radius */
.card {
  padding: var(--space-300); /* 24px */
  border-radius: var(--radius-medium); /* 8px */
  border: var(--border-width-thin) solid var(--color-border-default);
}
```

---

## 3. Components

> Each component below was found as a **published `component_set` (or `component`)** in the library (`design_systems/Design System CC/components/*`). Anatomy/variant data is **confirmed** where a real instance or the full variant matrix was inspected; everything else is clearly flagged **⚠️ Assumption** and inferred only from naming conventions and general CCDS patterns — never invented outright.

### 3.1 Button — ✅ Fully confirmed

**Purpose**: Primary interactive trigger for actions (submit, navigate, confirm, destructive actions, AI actions).

**Anatomy**: `[ Icon? ] [ Label? ] [ Icon? ]` inside a single auto-layout container with horizontal padding, vertical padding, gap, and a fixed corner radius.

**Variants (fully cross-multiplied — 4 × 5 × 5 × 5 = 500 documented symbols):**

| Axis | Values |
|---|---|
| `Style` | Primary · Secondary · Tertiary · Danger |
| `Size` | XS · SM · MD · LG · XL |
| `State` | Default · Hover · Pressed · Focused · Disabled |
| `Content` | Label Only · Icon + Label · Label + Icon · Icon + Label + Icon · Icon Only |

**Size specs (confirmed, Label-Only content):**

| Size | Height | Padding (H/V) | Font size |
|---|---|---|---|
| XS | 24px | — | — |
| SM | 26px | — | — |
| MD | 32px | 16px / 6px | 16px/20px Medium |
| LG | 38px | — | — |
| XL | 42px | — | — |

**Icon-Only size specs (confirmed):** XS 20×20 · SM 26×26 · MD 36×36 · LG 44×44 · XL 48×48.

**Style specs (Default state, MD size, confirmed via rendered code):**

| Style | Background | Text color | Notes |
|---|---|---|---|
| Primary | `linear-gradient(99.4deg, #4f39f5 0%, #cc3478 99.9%)` (brand gradient) | `color/text/inverse` (white) | The only gradient-filled button style — reserved for the primary CTA |
| Secondary | `color/background/information-bold` (`#615fff`) | `color/text/inverse` (white) | Solid indigo/violet fill |
| Tertiary | `color/background/neutral` (`#f3f4f6`) + `0.5px` border `color/border/default` (`#e5e7eb`) | `color/text/default` (`#030712`) | Only style with a visible border in Default state |
| Danger | `color/background/danger-bold` (`#d70000`) | `color/text/inverse` (white) | Destructive actions only |

Corner radius: **6px** for all styles/sizes (component-level override, see [§2.4](#24-component-tokens)).

**Usage guidelines**:
- Use **Primary** (gradient) for exactly one CTA per view/section — it visually dominates and should not compete with itself.
- Use **Secondary** for the second-most important action (e.g., "Take Over" in ticket triage).
- Use **Tertiary** for low-emphasis/utility actions (e.g., "Audit History").
- Use **Danger** only for destructive/irreversible actions (delete, reject, close-without-saving).
- Use **Icon Only** content for repeated toolbar actions where the icon is unambiguous; always pair with a Tooltip.

**Accessibility**: Disabled state must drop to `Opacity/disabled` (0.4) and remove pointer affordance; Focused state must render a visible **2px** (`Border Width/thick`) focus ring using `color/border/brand`. Icon-Only buttons **must** carry an `aria-label`/accessible name since there is no visible text.

**Do's / Don'ts**:
- ✅ Do keep one Primary button visible at a time in a given view.
- ✅ Do use Danger + a confirmation Modal for destructive actions.
- ❌ Don't use the brand gradient (Primary) for more than one action in the same view.
- ❌ Don't rely on color alone to convey the Danger style — pair with a "Delete"/"Remove" label.

---

### 3.2 Navigation — `Nav - Buttons`, `nav-items`, `TOP Bar - Nav`

**Purpose**: Primary/side/top navigation affordances for the Command Center shell.

**Confirmed component sets**: `Nav - Buttons` (component_set), `nav-items` (single component), `TOP Bar - Nav` (single component).

> ⚠️ **Assumption**: Full variant/state matrix for these three was not directly enumerated (their master pages were not individually reachable in this session). Based on the naming pattern and the Button component's own state model, assume `nav-items` supports at minimum **Default / Hover / Active(selected) / Disabled** states, and follows the same `color/background/selected` semantic token for the active state as documented in [§1.3.2](#132-semantic-color-tokens-semantic-colors-collection--color).

**Observed usage in context** (Menu Bar "Inbox" list item, confirmed via rendered code):
- Active/hovered list row background: `#f1f2f3` (neutral tint, close to `Gray/100`/`color/background/neutral`)
- Row padding: `6px` horizontal, `8px` vertical (`space.075`/`space.100`)
- Row corner radius: `6px` (matches Button's component-level radius)
- Row title: 12px Medium; row preview text: 9px Regular, `color/text/subtle`-equivalent (`#64748b`)

**Guidelines**: Navigation rows should truncate long labels/previews with ellipsis (confirmed: ticket preview text is truncated with literal `........` in source copy, indicating a truncation pattern is expected at the content layer, not just CSS `text-overflow`).

---

### 3.3 Input — `Input` (component_set)

**Purpose**: Single-line text entry (search, form fields).

**Confirmed from usage** (Menu Bar search field):
- Border: `0.5px` `color/border/default`
- Padding: `10px` horizontal (`space.150`≈12, observed ~10px), `6px` vertical
- Corner radius: `6px`
- Leading icon slot: 14px icon + 6px gap + placeholder text (12px Regular, `color/text/subtle`)
- Placeholder observed: "Search Ticket id..."

> ⚠️ **Assumption**: The full `Input` component set (Default/Hover/Focused/Filled/Error/Disabled states; Size variants; with/without leading icon, trailing icon, or clear button) was **not directly inspected** — only its usage as a search field was visible. Standard CCDS conventions (per Button's 5-state model) imply Input should have **Default / Hover / Focused / Error / Disabled** states, sized via `Dimension/control-{sm,md,lg}` (28/36/44px height) with `color/background/input` fill and `color/border/default` → `color/border/brand` on focus. Confirm the full property set directly against the `Input` page in Figma before implementation.

**Accessibility**: Always pair with a visible or programmatically-associated `<label>`; error state must be announced via `aria-invalid`/`aria-describedby`, not color alone.

---

### 3.4 Select & Dropdown Menu — `Select`, `Dropdown Menu` (component_sets)

**Purpose**: Choose one value from a list (Select) / contextual action menu (Dropdown Menu).

> ⚠️ **Assumption**: Neither component's full anatomy was directly inspected in this session. Based on the z-index scale (`dropdown` = 200, [§1.12](#112-z-index--layering)) and standard select-field conventions observed across the CCDS naming (Input, Checkbox, Radio all exist as siblings), assume:
> - `Select` mirrors `Input` sizing/border/radius conventions, with a trailing chevron icon (`Icon Size/small`).
> - `Dropdown Menu` renders as a `elevation/surface/overlay` panel at `radius.medium`, stacked at z-index `dropdown` (200), with menu items following the same row pattern as `nav-items` (padding, hover tint, 6px radius).
>
> Confirm exact states, sizes, and menu-item anatomy directly in Figma before implementation.

---

### 3.5 Checkbox, Radio, Toggle — component_sets

**Purpose**: Binary/multi selection (Checkbox), single-choice selection (Radio), on/off setting (Toggle).

> ⚠️ **Assumption**: All three exist as confirmed `component_set`s in the library but their variant matrices were not directly inspected. Standard expectation based on sibling components: **Unchecked / Checked / Indeterminate (Checkbox only) / Hover / Focused / Disabled** states, using `color/background/selected` + `color/border/brand` for the checked/on state, and `Opacity/disabled` for the disabled state. Toggle likely uses `radius.full` (pill track) per standard switch anatomy.

---

### 3.6 Card — `Card` (component_set)

**Purpose**: General-purpose content container (list item, dashboard widget shell, form panel).

**Confirmed dimensions (from Skeleton Loader "Card" variants, used as a structural proxy since actual Card content states weren't directly reachable):**

| Size | Width | Height |
|---|---|---|
| SM | 160px | 130px |
| MD | 240px | 182px |
| LG | 320px | 234px |

**Confirmed anatomy pattern (from Skeleton "Card"):** thumbnail/media block (full width, ~100px tall) → title line → subtitle line, stacked with `space.100`-ish gaps.

> ⚠️ **Assumption**: Real Card content (header/body/footer slots, border vs. borderless variants, interactive/clickable state) was not directly inspected. Recommend: `border color/border/default`, `radius.medium` (8px) or `radius.xlarge` (16px) for "hero"/feature cards per the Radius token descriptions, and `elevation/surface/default` → `raised-hovered` on hover for clickable cards.

---

### 3.7 Table — `Table Header Cell`, `Table Body Cell` (component_sets)

**Purpose**: Tabular data display (ticket lists, audit logs, reports).

**Confirmed dimensions (from Skeleton Loader "Table Row" variants, structural proxy):**

| Size | Width | Height |
|---|---|---|
| SM | 240px | 27px |
| MD | 320px | 34px |
| LG | 400px | 45px |

> ⚠️ **Assumption**: `Table Header Cell` and `Table Body Cell` are confirmed as separate component sets (correctly modeling that header styling — likely bold/uppercase/sticky — differs from body cell styling). Typography is inferred to use `Body/Body SM` ("Secondary copy, table cells" — confirmed style description, [§1.4.2](#142-named-text-styles)) for body cells. Column alignment, sort-indicator affordance, sticky-header behavior (`z-index: sticky` = 300, per [§1.12](#112-z-index--layering)), row-hover (`color/background/selected` or `elevation/surface/hovered`), and zebra-striping were not directly confirmed — validate against the `Table Header Cell` / `Table Body Cell` pages before implementation.

---

### 3.8 Tabs — `Tab Item` (component_set)

**Purpose**: Switch between sibling views within the same context (e.g., ticket detail tabs: Details / Audit / AI Chat).

> ⚠️ **Assumption**: Confirmed as a component set; full state/size matrix not directly inspected. Expect **Default / Hover / Active(selected) / Disabled** states with an active-indicator underline or filled-pill treatment, `Label/Label MD` typography, and badge-count support (the design system's Material-influenced lineage per its badge/pill richness makes a numeric badge-on-tab a likely supported variant — confirm directly).

---

### 3.9 Breadcrumb — `Breadcrumb`, `Breadcrumb Item` (component_sets)

**Purpose**: Hierarchical location indicator (e.g., Command Center > Tickets > TKT-2846).

> ⚠️ **Assumption**: Confirmed as two related component sets (a container + an item, matching the Table Header/Body Cell pattern of "container + cell/item" pairs seen elsewhere in this file). Expect items separated by a chevron/slash icon (`Icon Size/small`), with the current/last item styled with `color/text/default` and prior items styled with `color/text/subtle` + `color/link/default` on hover.

---

### 3.10 Pagination — `Pagination`, `Pagination Bar`, `Pagination Button` (component_sets)

**Purpose**: Navigate multi-page data sets (tables, ticket lists).

> ⚠️ **Assumption**: Three related, confirmed component sets exist (a page-number button, a bar/container, and a composed pagination control) — mirroring standard pagination anatomy: previous/next icon buttons + numbered page buttons + optional "Rows per page" selector. Exact states/sizes not directly inspected; expect `Button[Content=Icon Only]` styling reused for prev/next controls.

---

### 3.11 Badge, Tag, Pill — `Badge`, `Tag` (component_sets)

**Purpose**: Compact status/category indicator, powered by the 13-hue pill color system ([§1.3.2](#132-semantic-color-tokens-semantic-colors-collection--color)).

**Confirmed real-world usage** (ticket header "Need Review" status pill):
```css
background: var(--warning-50, #fffbeb);
color: var(--warning-800, #92400e);
padding: 4px 8px;              /* space.050 / space.100 */
border-radius: 6px;
font: 12px Medium Funnel Display;  /* scale/400 */
gap: 6px;                          /* icon + label */
```

**Color system**: Badge/Tag should draw from the **13-hue `pill/{hue}/{bg,text,border}` set** — `purple, pink, blue, sky, red, mint, teal, cyan, rose, amber, green, yellow, orange` — allowing non-sequential categorical color-coding (e.g., ticket type = blue, priority = red, department = teal) distinct from the 5 semantic-meaning colors (danger/warning/success/information/brand).

**Anatomy**: `[ Icon? ] Label [ dismiss-icon? ]` — Tag likely supports a removable/dismissible variant (standard "Tag" vs. "Badge" distinction: Badge = read-only status, Tag = often removable/filterable). ⚠️ Exact Default/Removable variant split not directly confirmed — validate in Figma.

**Usage guidelines**: Reserve semantic colors (danger/success/warning/information) for **meaning** (error, success, pending); use the hue-based pill palette for **categorical** labels where no inherent meaning/urgency exists.

---

### 3.12 Avatar & Avatar Group — `Avatar`, `Avatar Group` (component_sets)

**Purpose**: Represent a user/assignee (Avatar), represent multiple assignees compactly (Avatar Group / stacked avatars).

**Confirmed dimensions (from Skeleton Loader "Avatar" variants, structural proxy):**

| Size | Container width | Height |
|---|---|---|
| SM | 128px (with adjacent text) | 28px |
| MD | 180px | 36px |
| LG | 236px | 48px |

Standalone avatar circle observed at **36×36px** with `radius.full` in the ticket-header usage (`bg-[var(--gray/100,#f3f4f6)] rounded-[40px] size-[36px]`).

**Anatomy**: Circular container (image or initials fallback) at `radius.full`; Avatar Group overlaps circles with a negative margin and a `color/border/inverse`-style ring to separate overlapping avatars (⚠️ overlap/ring treatment inferred from standard avatar-group conventions, not directly confirmed).

---

### 3.13 Tooltip — `Tooltip` (component_set)

**Purpose**: Contextual micro-help on hover/focus, especially for Icon-Only buttons.

> ⚠️ **Assumption**: Confirmed component set; anatomy not directly inspected. Expect a small `elevation/surface/overlay` bubble at `z-index: popover` (600, the highest layer below toast), `radius.small` (4px), `Body XS` typography, appearing after a short hover delay with `Motion/duration/fast` (100ms) transition.

---

### 3.14 Modal — `Modal` (component_set)

**Purpose**: Blocking dialog for confirmations, forms, or focused tasks.

**Confirmed**: `z-index: modal` = 500 ([§1.12](#112-z-index--layering)); backdrop scrim opacity = `Opacity/scrim` (0.5, [§1.9](#19-opacity)); enter/exit animation should use `Motion/duration/slow` (350ms, "large surface animations (modal, sheet)" — explicit token description).

> ⚠️ **Assumption**: Header/body/footer slot anatomy, size variants (SM/MD/LG/fullscreen), and close-affordance placement not directly inspected — but the confirmed z-index + scrim + motion-duration tokens above are explicitly authored *for* modals, giving high confidence in those three values specifically.

---

### 3.15 Drawer — `Drawer/Right/Nav/SM` (component, confirmed path) + implied Drawer family

**Purpose**: Slide-in side panel (navigation, filters, detail views) without fully blocking the page.

**Confirmed**: Exists at minimum as `Drawer/Right/Nav/SM` — a **slash-namespaced component path** indicating the family is organized by `Drawer/{Side}/{Purpose}/{Size}` (e.g., likely siblings `Drawer/Right/Nav/MD`, `Drawer/Left/Filter/SM`, etc. — ⚠️ siblings not directly confirmed, inferred from the namespacing pattern only).

**Confirmed tokens**: `z-index: overlay` = 400 ("Drawers, side sheets" — explicit token description, [§1.12](#112-z-index--layering)); `Motion/duration/slow` (350ms) for the slide-in transition.

---

### 3.16 Toast — `Toast` (component_set)

**Purpose**: Transient, non-blocking notification (success/error/info confirmation after an action).

**Confirmed**: `z-index: toast` = 700 — the **highest layer in the entire stacking scale**, explicitly described as "Notifications - always on top" ([§1.12](#112-z-index--layering)).

> ⚠️ **Assumption**: Variant states (success/error/warning/info) almost certainly map to the 4 semantic `color/background/{success,danger,warning,information}[-bold]` tokens plus their matching icon tokens (`color/icon/success`, etc.) — this is a very high-confidence inference given how completely those 4 semantic families are built out elsewhere, but the Toast component's exact anatomy/variants were not directly inspected.

---

### 3.17 Alert — `Alert` (component_set)

**Purpose**: Inline, persistent status/callout banner (distinct from Toast's transient behavior) — e.g., "This ticket has an SLA breach in 6 hours."

> ⚠️ **Assumption**: Confirmed component set. Expect the same 4 semantic states as Toast (success/danger/warning/information) rendered as a full-width or inline banner with `color/background/{state}` (tint, not `-bold`) background, `color/border/{state}`-equivalent left accent border, and an icon + message + optional inline action/dismiss — a standard Alert/Banner anatomy. Not directly confirmed against the file.

---

### 3.18 Progress Bar & Spinner — `Progress Bar`, `Spinner` (component_sets)

**Purpose**: Determinate (Progress Bar) and indeterminate (Spinner) loading/progress indication.

**Confirmed tokens driving these**: `Motion/easing/linear` is explicitly described as being for **"spinners, progress bars"** — direct evidence these two components exist and use linear, constant-speed animation. `Opacity/loading` (0.6) is explicitly described as the **skeleton placeholder** opacity, which is the adjacent/sibling loading pattern (see [§3.20](#320-skeleton-loader--confirmed)).

> ⚠️ **Assumption**: Exact bar height, track/fill color pairing (`color/background/neutral` track + `color/background/brand-bold` fill is the most likely pairing given the brand-gradient precedent on Buttons), and Spinner diameter/stroke-width were not directly inspected.

---

### 3.19 Divider — ✅ Confirmed

**Purpose**: Visual separator between sections/content groups.

**Confirmed variants** (from the "Divider" component_set showcase):

| Variant | Description |
|---|---|
| `Type=Horizontal` | Default 1px horizontal rule |
| `Type=Vertical` | 1px vertical rule (24×120px sample block) |
| `Type=With Label` | Horizontal rule with a centered text label (e.g., "Section") interrupting the line |
| `Type=Dashed` | Dashed horizontal rule |
| `Type=Gradient` | Gradient-faded horizontal rule |
| `Type=Bold` | Heavier-weight horizontal rule |
| `Type=Subtle` | Lighter-weight/lower-contrast horizontal rule |
| `Type=Spacing SM/MD/LG` | Non-visible spacer variants (10px tall) — used as a layout spacing utility rather than a visible line |

**Usage guidelines**: Use `With Label` to separate named sections within a single panel (e.g., grouping form fields). Use `Spacing SM/MD/LG` variants when a designer needs a Divider-shaped placeholder purely for vertical rhythm, not a visible rule.

---

### 3.20 Skeleton Loader — ✅ Confirmed

**Purpose**: Loading placeholder shown while content streams in, at `Opacity/loading` (0.6).

**Confirmed variants and sizes** (7 content types × 3 sizes = 21 symbols):

| Content type | SM | MD | LG |
|---|---|---|---|
| `Text` | 160×36 | 240×46 | 320×56 |
| `Heading` | 112×28 | 168×34 | 224×40 |
| `Avatar` | 128×28 | 180×36 | 236×48 |
| `Card` | 160×130 | 240×182 | 320×234 |
| `Table Row` | 240×27 | 320×34 | 400×45 |
| `Form` | 160×156 | 240×192 | 320×228 |
| `Dashboard` | 232×192 | 340×278 | 448×364 |

**Usage guidelines**: Match the Skeleton variant/size to the real component it stands in for (e.g., use `Skeleton[Card, MD]` while a `Card[MD]` loads) so layout doesn't shift ("jump") once real content arrives. The `Dashboard` variant is the structural proxy for **KPI/Dashboard widgets** — see [§3.23](#323-kpi--dashboard-cards).

---

### 3.21 Empty State — ✅ Confirmed

**Purpose**: Communicate zero-data / error / permission / first-use states clearly, with a path forward.

**Confirmed variants and sizes** (8 types × 3 sizes = 24 symbols):

| Type | SM | MD | LG | Real copy example (from Layout Showcase) |
|---|---|---|---|---|
| `No Data` | 280×192 | 380×248 | 480×307 | — |
| `No Results` | 280×192 | 380×248 | 480×307 | "No results found" / "Adjust your filters or search terms." / CTA: "Clear filters" |
| `No Connection` | 280×192 | 380×248 | 480×307 | — |
| `Error` | 280×192 | 380×248 | 480×307 | — |
| `No Permissions` | 280×192 | 380×248 | 480×307 | "Access restricted" / "Contact your admin for access." / CTA: "Request access" |
| `First Use` | 280×192 | 380×248 | 480×307 | — |
| `Completed` | 280×192 | 380×248 | 480×307 | "All tasks done!" / "You've completed everything." / CTA: "Back to home" |
| `AI Ready` | 280×182 | 380×234 | 480×287 (slightly shorter — no CTA row) | "AI assistant ready" / "Ask anything about your data." / CTA: "Start chat" |

**Anatomy**: 48×48px rounded icon container (housing a 20×20px icon instance) → Heading (H5/H6-ish, ~21px observed) → supporting Body text (~17px observed) → optional single CTA button/link.

**Usage guidelines**: Always pair the icon + heading + supporting text; the CTA is optional but should be present whenever there's a clear recovery action (e.g., "Clear filters" for No Results, "Request access" for No Permissions). The `AI Ready` variant is visually near-identical to the others but exists as its own type — reserve it specifically for AI/chat entry points, reinforcing the system's AI-forward brand positioning.

---

### 3.22 AI Components — ⚠️ Partially confirmed, largely inferred

The system does not appear to have a dedicated, separately-named "AI Components" page reachable in this session, but AI-specific patterns recur consistently:

- **"Ask VIQAI" action** (confirmed, ticket header): rendered as a Tertiary-style button shell (border `#4f39f5`, 0.5px, radius 6px, padding 8px/4px) with its **label text filled by the brand gradient** (`background-clip: text`, same `#4f39f5 → #cc3478` gradient as the Primary button) instead of a solid color — a distinct, AI-specific "gradient-text" treatment not used anywhere else in the confirmed data. **Recommend formalizing this as a `color/text/ai` or `color/text/brand-gradient` token** and a dedicated `Button[Style=AI]` variant, since it is currently a one-off composition rather than a first-class Button style.
- **"AI Ready" Empty State** (confirmed, [§3.21](#321-empty-state--confirmed)): "AI assistant ready" / "Ask anything about your data." / "Start chat" CTA.
- ⚠️ **Assumption**: Given the product context (Supervity Command Centers, AI-assisted ticket triage), further AI-specific components likely exist (e.g., an AI Chat panel/drawer, streaming message bubbles, a "confidence score" indicator) but were **not directly reachable** in this session and are **not documented with fabricated specs** here. Recommend a follow-up pass directly against Figma pages named "AI" / "Assistant" / "Chat" if they exist.

---

### 3.23 KPI / Dashboard Cards — ⚠️ Inferred from Skeleton Dashboard proxy

No standalone "KPI Card" or "Dashboard Card" component_set was directly reachable, but the **Skeleton Loader's `Dashboard` variant** (232×192 / 340×278 / 448×364 at SM/MD/LG, [§3.20](#320-skeleton-loader--confirmed)) is strong structural evidence that a dashboard-widget-shaped component exists elsewhere in the file, since Skeleton variants are authored to match real components 1:1 in this system.

> ⚠️ **Assumption**: Based on the Dashboard skeleton's aspect ratio (roughly 1.2:1, wider than a Card) and standard KPI-card anatomy, expect: a small eyebrow/label (Body XS), a large metric value (Heading H2/H3 scale), a trend indicator (using `color/text/success` or `color/text/danger` + an up/down icon at `Icon Size/small`), and optionally a small inline sparkline/chart area. **Do not treat these dimensions or this anatomy as confirmed** — validate directly against a "KPI Card" or "Dashboard" page in Figma.

---

### 3.24 Charts / Data Visualization — ⚠️ Token evidence only, no component confirmed

No chart component was directly reachable, but strong token-level evidence confirms charts are a first-class part of the system:

- The **`Dark Blue/{300,500,600,700}` primitive ramp** is explicitly described as **"Deep blue ramp — used for charts, dark surfaces"**.
- The 13-hue **pill palette** (`purple, pink, blue, sky, red, mint, teal, cyan, rose, amber, green, yellow, orange`) is an unusually complete, sequential-friendly set of distinguishable hues — a strong candidate for **categorical chart series colors**, beyond just status pills.

> ⚠️ **Assumption**: No chart component (bar/line/pie/donut) or its axis/legend/tooltip anatomy could be confirmed in this session. Recommend using the `Dark Blue` ramp for single/primary-series charts and the 13-hue pill palette (via its `bg`/primitive equivalents) for multi-series categorical charts, pending direct confirmation against a "Charts" page in Figma.

---

### 3.25 Command Center Components — ✅ Confirmed via real product screens

These are **screen-level compositions** observed directly in the Layout page's embedded product mockups (a ticket-inbox/triage workflow), documenting real, in-context component usage rather than isolated master components:

**Menu Bar (ticket inbox sidebar)** — confirmed, 220×750px panel:
- Header: "Inbox" title (16px Medium) + search input (with leading search icon, placeholder "Search Ticket id...") + a filter/icon-only button.
- List: stacked ticket-preview rows (Ticket ID + timestamp on one line; Subject line; truncated preview line), with the active/current row highlighted via `#f1f2f3` background + `radius.medium` (6-8px).
- Container: `1px` border (`color/border/default`), `radius.medium` (8px), shadow `0 4px 12px rgba(0,0,0,0.03)`.

**Ticket Detail Header** — confirmed, 1066×76px bar:
- Left cluster: 36×36 circular avatar placeholder + title ("Invoice mismatch") + secondary PO reference + metadata row (Ticket ID, TAT/turnaround-time) + a status pill ("Need Review", amber/warning-toned: bg `#fffbeb`, text `#92400e`).
- Right cluster: action button row — **Secondary-style** "Take Over" (blue-toned outline pill button), **Primary-tint** "Audit History" (purple-toned outline pill button), and the **AI-gradient-text** "Ask VIQAI" button (see [§3.22](#322-ai-components--partially-confirmed-largely-inferred)).

**Usage guidelines**: This header pattern — identity/context on the left, a prioritized action cluster on the right, with the highest-priority/AI action rendered distinctly (gradient text) — is the canonical **"record header" pattern** for the Command Center product and should be reused for any entity detail view (tickets, orders, invoices), not just tickets.

---

## 4. Layout

### 4.1 Auto Layout Rules (✅ confirmed pattern, observed across every inspected component)

Every component inspected in this file — Buttons, the Menu Bar panel, the ticket header, status pills, the Spacing Documentation page itself — is built with **Figma Auto Layout** (never absolute-positioned children), which maps directly to CSS Flexbox:

| Auto Layout property | Confirmed convention |
|---|---|
| Direction | Horizontal for single-row clusters (button content, header action row); Vertical for stacked content (Menu Bar list, ticket header text block) |
| Gap | Always a `space.*` token — never an arbitrary pixel value (observed: 6px `space.075` between icon+label, 8px `space.100` between list rows) |
| Padding | Always a `space.*` token pair (observed: 16px/6px on Buttons = `space.200`/`space.075`) |
| Sizing | Children default to **Hug contents** (buttons, pills, badges); containers default to **Fill container** (panels, rows) or a fixed px width for fixed-size cards |
| Alignment | Center-aligned cross-axis is the default for single-line rows (button content, list-row metadata lines) |

**Rule for implementation**: Any new component should be built with a flex container using only `space.*` tokens for `gap`/`padding` — never a hardcoded pixel value — to stay consistent with the file's 100%-Auto-Layout construction.

### 4.2 Responsive Behavior

Derived from the confirmed 4-breakpoint grid ([§1.11](#111-grid-system--breakpoints)):

| Breakpoint | Range | Layout behavior (⚠️ inferred from breakpoint/column data — no explicit responsive frames were inspected) |
|---|---|---|
| `sm` (mobile) | ≥480px, 4 columns | Single-column stacks; Menu Bar/nav collapses to an off-canvas Drawer (`Drawer/Right/Nav/SM`, confirmed component path, [§3.15](#315-drawer-drawerrightnavsm-confirmed-path--implied-drawer-family)); Cards/Tables likely switch to a stacked card-per-row layout instead of a wide table |
| `md` (tablet) | ≥768px, 8 columns | Two-column layouts possible (e.g., list + preview pane); persistent nav rail likely replaces the Drawer |
| `lg` (desktop) | ≥1024px, 12 columns | Full 3-pane workbench layout becomes viable (nav + list + detail) — matches the ticket-triage screens observed (Menu Bar ≈220px + detail ≈1066px ≈ fits a 1024–1280px viewport) |
| `xl` (wide) | ≥1280px, 12 columns, 40px margin | Same 12-column layout with more breathing room (wider margins) rather than more columns — content max-width should likely be capped rather than stretched infinitely |

> ⚠️ **Assumption**: No explicit "Mobile" or "Tablet" frames of the Command Center screens were found/inspected in this session — the behaviors above are inferred from (a) the documented breakpoint/column/gutter tokens and (b) the fixed pixel widths observed on the desktop-oriented Menu Bar (220px) and ticket header (1066px), which together imply a **desktop-first, fixed 3-pane workbench** design that has *not yet been explicitly designed responsively* in the reachable parts of this file. Flag this as a gap to close with design before building mobile/tablet Command Center views.

### 4.3 Page Templates & Workbench Layouts

**Confirmed 3-pane "workbench" pattern** (from the Layout page's embedded product screens):

```
┌─────────────┬──────────────────────────────────────────────┐
│  Menu Bar   │  Record Header (identity + action cluster)   │
│  (220px)    ├──────────────────────────────────────────────┤
│  Inbox list │                                                │
│  (search +  │  Detail / workspace content                   │
│  filtered   │  (tabs, forms, AI chat, audit trail, etc.)    │
│  rows)      │                                                │
└─────────────┴──────────────────────────────────────────────┘
```

- **Left pane** (fixed ~220px): entity list/queue with search + filter, à la an email inbox — this is the "triage" pane.
- **Right pane** (fluid, observed at 1066px in a desktop frame): the selected entity's full detail view, headed by the "record header" pattern documented in [§3.25](#325-command-center-components--confirmed-via-real-product-screens).

**Dashboard layout** (⚠️ inferred): Given the confirmed `Skeleton[Dashboard]` proxy variant ([§3.20](#320-skeleton-loader--confirmed) / [§3.23](#323-kpi--dashboard-cards)), dashboard pages likely use a **card-grid layout** — a responsive grid of KPI/Dashboard-card widgets (each ≈340×278px at MD) laid out across the 12-column grid, e.g., 3–4 widgets per row at `lg`/`xl` breakpoints, collapsing to 1–2 per row at `sm`/`md`. Not directly confirmed against a real dashboard page.

### 4.4 Card Patterns

- **List-row card** (Menu Bar ticket preview): no visible border/shadow per-row; separation is via the parent panel's outer border/shadow + subtle background tint on the active row only.
- **Standalone Card** ([§3.6](#36-card-component_set)): bordered or elevated container, `radius.medium`/`radius.xlarge`, used for dashboard widgets and grouped content.
- **Record header card** (ticket header, [§3.25](#325-command-center-components--confirmed-via-real-product-screens)): a full-width bar rather than a bounded card — treat as a distinct "header region" pattern, not a Card variant.

---

## 5. Interaction

### 5.1 State Model (cross-component)

Nearly every interactive component in this file follows the **same 5-state model** the Button component fully exposes (Default / Hover / Pressed / Focused / Disabled), plus contextual states layered on top for data-driven components (Loading, Error, Success, Selected/Active):

| State | Confirmed mechanism | Token(s) |
|---|---|---|
| **Default** | Base semantic color binding | `color/background/*`, `color/text/*` |
| **Hover** | Discrete color swap (Button) or opacity overlay (generic) | `Opacity/hover` = 0.08 |
| **Pressed / Active** | Discrete color swap (Button) or opacity overlay (generic) | `Opacity/pressed` = 0.12 |
| **Focused** | Visible ring/outline (Button has a dedicated `State=Focused` symbol) | `Border Width/thick` (2px) + `color/border/brand` (⚠️ exact focus-ring token binding inferred, not directly resolved) |
| **Disabled** | Dimmed, non-interactive | `Opacity/disabled` = 0.4 |
| **Loading** | Dimmed placeholder (Skeleton) or a Spinner overlay | `Opacity/loading` = 0.6 |
| **Selected** | Persistent "on" tint, distinct from hover (e.g., active Menu Bar row) | `color/background/selected` |
| **Error** | Border/icon/text recolor to danger family | `color/border/danger` (⚠️ implied), `color/text/danger`, `color/icon/danger` |
| **Success** | Recolor to success family | `color/text/success`, `color/icon/success` |

### 5.2 Animation Timing

All motion should draw from the 4 confirmed durations and 4 easing curves ([§1.13](#113-motion--animation)):

| Interaction | Recommended duration | Recommended easing |
|---|---|---|
| Button hover/press feedback | `Motion/duration/fast` (100ms) | `Motion/easing/standard` |
| Tooltip appear | `Motion/duration/fast` (100ms) | `Motion/easing/enter` |
| Dropdown/Select menu open | `Motion/duration/medium` (200ms) | `Motion/easing/enter` |
| Dropdown/Select menu close | `Motion/duration/medium` (200ms) | `Motion/easing/exit` |
| Modal open | `Motion/duration/slow` (350ms) | `Motion/easing/enter` |
| Modal close | `Motion/duration/slow` (350ms) | `Motion/easing/exit` |
| Drawer slide-in/out | `Motion/duration/slow` (350ms) | `Motion/easing/enter` / `exit` |
| Toast enter/exit | `Motion/duration/medium` (200ms) (⚠️ inferred — toasts are typically snappier than modals) | `Motion/easing/enter` / `exit` |
| Spinner rotation | continuous | `Motion/easing/linear` (explicitly confirmed for spinners) |
| Progress bar fill | continuous/incremental | `Motion/easing/linear` (explicitly confirmed for progress bars) |
| Skeleton shimmer (if animated) | continuous | ⚠️ not confirmed — likely `linear` or a custom shimmer keyframe |

### 5.3 Motion Principles

- **Snappy micro-interactions, deliberate macro-transitions**: 100ms for anything the user directly touches (hover/press); 200ms for content appearing/disappearing (menus); 350ms for large surfaces entering the viewport (modals, drawers).
- **Directional easing, not symmetric ease-in-out**: entrances use `enter` (`cubic-bezier(0,0,0,1)`, decelerating into place), exits use `exit` (`cubic-bezier(0.2,0,1,1)`, accelerating away) — never the same curve for both directions.
- **Linear is reserved exclusively for continuous, non-discrete motion** (spinners, indeterminate progress) — using `linear` on a discrete state change (e.g., a hover fade) would feel mechanical and violates the system's own token descriptions.

---

## 6. Accessibility

### 6.1 Color Contrast

| Pairing | Foreground | Background | Approx. contrast ratio | WCAG AA (4.5:1 text / 3:1 large text) |
|---|---|---|---|---|
| Primary/Danger/Secondary button text | `#ffffff` (`color/text/inverse`) | `#d70000` (danger-bold) | ~4.8:1 | ✅ Pass (normal text) |
| Primary/Danger/Secondary button text | `#ffffff` | `#615fff` (information-bold) | ~3.6:1 | ⚠️ Borderline — passes for large/bold text (16px Medium ≈ borderline "large text" per WCAG's 14pt-bold/18pt-regular rule); recommend verifying at final rendered weight |
| Primary button text | `#ffffff` | `#4f39f5` (gradient start) | ~5.2:1 | ✅ Pass — but verify the **midpoint and end** of the gradient (`#cc3478`) independently, since contrast must hold across the entire gradient, not just the start color |
| Tertiary button text | `#030712` (`color/text/default`) | `#f3f4f6` (`color/background/neutral`) | ~16.5:1 | ✅ Pass (excellent) |
| Status pill text (warning) | `#92400e` | `#fffbeb` | ~7.5:1 | ✅ Pass |
| Ticket subtitle text | `#475569`-ish (`text/secondary`, legacy layer) | white/panel background | ~7:1 | ✅ Pass |

> ⚠️ **Recommendation**: Run the **full pill palette** (13 hues × text-on-bg) through an automated contrast checker before shipping — only the warning/amber pairing above was directly sampled from a real instance; the other 12 hues were not independently contrast-tested in this session.

### 6.2 Typography Accessibility Rules

- **Minimum body text size**: the smallest *body/paragraph* text observed is `Body XS`/9-11px (inbox preview/timestamp text) — this is below the commonly recommended 12–14px minimum for sustained reading. ⚠️ Recommend reserving sub-12px sizes strictly for secondary metadata (timestamps, captions) as currently used, never for primary content or actionable labels.
- **Line height**: all confirmed text uses a line-height ≥ 1.25× the font size (e.g., 16px/20px = 1.25, 12px/16px = 1.33) — meets WCAG 1.4.8 (line spacing at least 1.5× is recommended for *blocks* of text; the tighter ratios here are acceptable for short UI labels, not long-form paragraphs).
- **Don't rely on tracking/letter-spacing alone for emphasis** — the Cover page's uppercase, tracked headings (`0.84–3.84px` tracking) are decorative/marketing-only and should not be a pattern for functional UI text, which should rely on weight/color/size instead.

### 6.3 Focus States

- Button ships an explicit **`State=Focused`** symbol distinct from Hover — confirming focus-visible styling is a first-class design concern, not a browser-default afterthought.
- Recommended focus ring (⚠️ inferred, exact token binding not directly resolved): **2px** (`Border Width/thick`) outline in `color/border/brand`, offset 2px from the control edge, applied via `:focus-visible` (not `:focus`) so mouse users aren't shown a ring on click.
- All interactive components (Button, Input, Select, Checkbox, Radio, Toggle, Tabs, Pagination, nav items) must implement an equivalent focus-visible treatment even where a dedicated Focused symbol wasn't directly inspected for that component.

### 6.4 Keyboard Navigation

⚠️ Not directly testable from static Figma data — the following are **standard WCAG-driven requirements** the implementation must satisfy regardless of what's explicitly drawn in Figma:

- All interactive components must be reachable via `Tab`/`Shift+Tab` in a logical DOM order matching the visual left-to-right, top-to-bottom reading order (record header → detail tabs → workspace content, per the confirmed workbench layout in [§4.3](#43-page-templates--workbench-layouts)).
- `Dropdown Menu` / `Select` must support `Arrow Up/Down` to move selection, `Enter`/`Space` to select, `Escape` to close.
- `Modal` / `Drawer` must trap focus while open and return focus to the triggering element on close.
- `Tabs` must support `Arrow Left/Right` to move between tab items (per the WAI-ARIA Tabs pattern).
- Icon-Only buttons and Avatar/status-pill-only rows must be operable and labeled for screen readers even though they carry no visible text label.

### 6.5 WCAG Considerations Summary

| WCAG criterion | Status in this system |
|---|---|
| 1.4.3 Contrast (Minimum) | Mostly passes on sampled pairings; **verify full pill palette + gradient midpoints** before sign-off |
| 1.4.11 Non-text Contrast (borders, focus rings) | ⚠️ Not directly testable — the `0.5px` hairline borders on Tertiary buttons/inputs should be checked against the 3:1 non-text contrast requirement at real-world rendering |
| 2.1.1 Keyboard | ⚠️ Design-system responsibility to implement per §6.4; not verifiable from Figma alone |
| 2.4.7 Focus Visible | ✅ Explicit `State=Focused` Button symbol is a strong signal this is taken seriously; extend the same rigor to all other interactive components |
| 1.4.4 Resize Text | ⚠️ Token-based `rem`/scalable units recommended over fixed `px` at implementation time, even though Figma naturally works in px |
| 4.1.2 Name, Role, Value | Icon-Only Button/Avatar/Pill usages must carry accessible names — flagged throughout §3 |

---

## 7. Documentation & Governance

### 7.1 File & Page Structure (as observed)

```
Design System CC (Figma file, fileKey: xzy7YzlLGft4NqEDpv54jx)
├─ Cover                                  — brand/version splash
├─ ✦ Spacing & Grid Documentation         — internal token education page
├─ ✦ Layout System — Showcase             — page/template + component usage showcase
│    └─ embedded real product screens (Menu Bar, Ticket Header) used as ground truth in this doc
├─ Button  (canvas "0:1")                 — full 500-symbol variant matrix
├─ Divider                                — full variant showcase
├─ Skeleton Loader                        — 21-symbol variant matrix
├─ Empty State                            — 24-symbol variant matrix
├─ Input / Select / Dropdown Menu / Checkbox / Radio / Toggle
├─ Card / Table Header Cell / Table Body Cell
├─ Tabs (Tab Item) / Breadcrumb / Breadcrumb Item
├─ Pagination / Pagination Bar / Pagination Button
├─ Badge / Tag / Avatar / Avatar Group
├─ Tooltip / Modal / Drawer (Drawer/Right/Nav/SM, …) / Toast / Alert
├─ Progress Bar / Spinner
├─ Nav - Buttons / nav-items / TOP Bar - Nav
└─ (Figma Variables, not a page) → "Design Tokens" collection + "Semantic colors" collection
```

> ⚠️ **Assumption**: This tree reflects every page/component **name** confirmed via `search_design_system`/`get_metadata`/`get_design_context` across this session; it is a reconstruction, not a literal single "pages" listing pulled from the file in one call (the file's page-list API call was unreliable in this session — see the [Errors and fixes] history). Treat page **order** as approximate.

### 7.2 Naming Conventions (system-wide summary)

See [§2.6](#26-naming-conventions) for the full token-naming table. Component-level conventions:

- **Component sets** use **Title Case, space-separated** names (`Table Header Cell`, `Empty State`, `Dropdown Menu`).
- **Variant properties** use **Title Case keys** with **Title Case or acronym values** (`Style=Primary`, `Size=MD`, `State=Default`).
- **Namespaced families** use **`/` for hierarchy in the component name itself**, not just variant properties (`Drawer/Right/Nav/SM`) — this is a **second, distinct namespacing pattern** from the variant-property pattern used by Button, and should be **standardized on going forward** (recommend: prefer variant properties over slash-namespaced component names for new components, since slash-names don't get Figma's built-in variant-property tooling/inspector).

### 7.3 Governance Recommendations

1. **Consolidate the dual token system** ([§1.3.3](#133-legacy--screen-level-token-layer-️-observation)) — migrate any screen still bound to `--scale/*`, `--primary/50…900`, `--secondary/50…900` onto the canonical `color/*`, `space.*`, `Dimension/*` variables. Track this as a design-debt item.
2. **Formalize the AI gradient-text treatment** ([§3.22](#322-ai-components--partially-confirmed-largely-inferred)) as a real token/variant (`color/text/ai` + `Button[Style=AI]`) rather than a one-off composition, given the product's AI-forward positioning.
3. **Audit the Button Icon-Only XL size** (48px vs. the `Dimension/control-xl` token's 52px) for an intentional-vs-accidental mismatch ([§2.4](#24-component-tokens)).
4. **Publish a full Elevation/Shadow scale** as Figma Effect Styles — currently only one shadow value exists on a real instance with no backing style ([§1.7](#17-elevation--shadow)).
5. **Standardize the Space/Radius naming** from dot-notation (`space.150`) to slash-notation (`Space/150`) to match every other token family ([§2.6](#26-naming-conventions)).
6. **Author explicit mobile/tablet frames** for the Command Center workbench — the current screens are desktop-fixed-width only ([§4.2](#42-responsive-behavior)).
7. **Contrast-audit the full 13-hue pill palette and the brand gradient's midpoint/end color** before relying on them for text-bearing surfaces ([§6.1](#61-color-contrast)).

---

## 8. Developer Handoff

### 8.1 CSS Variables (root token set)

Only **directly confirmed** values are populated below; every other listed token is present for structural completeness with its Figma name preserved — pull the exact value from the Figma Variables panel (`Design Tokens` / `Semantic colors` collections) before use. Do not treat placeholder comments as real values.

```css
:root {
  /* ---- Spacing (confirmed) ---- */
  --space-0: 0px;
  --space-025: 2px;
  --space-050: 4px;
  --space-075: 6px;
  --space-100: 8px;
  --space-150: 12px;
  --space-200: 16px;
  --space-250: 20px;
  --space-300: 24px;
  --space-400: 32px;
  --space-500: 40px;
  --space-600: 48px;
  --space-800: 64px;
  --space-1000: 80px;

  /* ---- Radius (confirmed) ---- */
  --radius-none: 0px;
  --radius-small: 4px;
  --radius-medium: 8px;
  --radius-large: 12px;
  --radius-xlarge: 16px;
  --radius-full: 9999px;

  /* ---- Dimension (confirmed) ---- */
  --dimension-control-sm: 28px;
  --dimension-control-md: 36px;
  --dimension-control-lg: 44px;
  --dimension-control-xl: 52px;

  /* ---- Icon size (confirmed) ---- */
  --icon-size-small: 16px;
  --icon-size-medium: 20px;
  --icon-size-large: 24px;
  --icon-size-xlarge: 32px;

  /* ---- Border width (confirmed) ---- */
  --border-width-none: 0px;
  --border-width-thin: 1px;
  --border-width-thick: 2px;

  /* ---- Opacity (confirmed) ---- */
  --opacity-0: 0;
  --opacity-100: 1;
  --opacity-hover: 0.08;
  --opacity-pressed: 0.12;
  --opacity-disabled: 0.4;
  --opacity-loading: 0.6;
  --opacity-scrim: 0.5;

  /* ---- Motion (confirmed) ---- */
  --motion-duration-instant: 0ms;
  --motion-duration-fast: 100ms;
  --motion-duration-medium: 200ms;
  --motion-duration-slow: 350ms;
  --motion-easing-linear: linear;
  --motion-easing-standard: cubic-bezier(0.2, 0, 0, 1);
  --motion-easing-enter: cubic-bezier(0, 0, 0, 1);
  --motion-easing-exit: cubic-bezier(0.2, 0, 1, 1);

  /* ---- Z-index (confirmed) ---- */
  --z-base: 0;
  --z-raised: 100;
  --z-dropdown: 200;
  --z-sticky: 300;
  --z-overlay: 400;
  --z-modal: 500;
  --z-popover: 600;
  --z-toast: 700;

  /* ---- Semantic color (confirmed subset) ---- */
  --color-text-default: #030712;
  --color-text-inverse: #ffffff;
  --color-background-neutral: #f3f4f6;
  --color-border-default: #e5e7eb;
  --color-background-danger-bold: #d70000;
  --color-background-information-bold: #615fff;
  --brand-gradient: linear-gradient(99.4deg, #4f39f5 0%, #cc3478 99.9%);

  /* ---- Semantic color (name confirmed, hex NOT resolved — pull from Figma before use) ---- */
  --color-text-subtle: /* TODO: resolve from Figma */;
  --color-text-brand: /* TODO */;
  --color-text-danger: /* TODO */;
  --color-text-success: /* TODO */;
  --color-link-default: /* TODO */;
  --color-icon-default: /* TODO */;
  --color-icon-subtle: /* TODO */;
  --color-icon-inverse: /* TODO */;
  --color-icon-brand: /* TODO */;
  --color-icon-danger: /* TODO */;
  --color-icon-success: /* TODO */;
  --color-icon-warning: /* TODO */;
  --color-border-bold: /* TODO */;
  --color-border-brand: /* TODO */;
  --color-background-surface-default: /* TODO */;
  --color-background-neutral-bold: /* TODO */;
  --color-background-input: /* TODO */;
  --color-background-disabled: /* TODO */;
  --color-background-selected: /* TODO */;
  --color-background-brand-bold: /* TODO */;
  --color-background-danger: /* TODO */;
  --color-background-warning: /* TODO */;
  --color-background-warning-bold: /* TODO */;
  --color-background-success: /* TODO */;
  --color-background-success-bold: /* TODO */;
  --color-background-information: /* TODO */;
  --color-background-discovery: /* TODO */;
}
```

### 8.2 Tailwind Token Mapping

Map the confirmed tokens into `tailwind.config.js` `theme.extend` so class names stay design-token-driven (`bg-brand-bold`, `rounded-medium`, `p-space-200`, etc.) instead of arbitrary values:

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      spacing: {
        '0': '0px', '025': '2px', '050': '4px', '075': '6px',
        '100': '8px', '150': '12px', '200': '16px', '250': '20px',
        '300': '24px', '400': '32px', '500': '40px', '600': '48px',
        '800': '64px', '1000': '80px',
      },
      borderRadius: {
        none: '0px', small: '4px', medium: '8px',
        large: '12px', xlarge: '16px', full: '9999px',
      },
      colors: {
        text: {
          default: '#030712',
          inverse: '#ffffff',
          // subtle, brand, danger, success, link: resolve from Figma before use
        },
        background: {
          neutral: '#f3f4f6',
          'danger-bold': '#d70000',
          'information-bold': '#615fff',
          // surface-default, input, disabled, selected, brand-bold, warning*, success*, information, discovery: resolve from Figma
        },
        border: {
          default: '#e5e7eb',
          // bold, brand: resolve from Figma
        },
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(99.4deg, #4f39f5 0%, #cc3478 99.9%)',
      },
      transitionDuration: {
        instant: '0ms', fast: '100ms', medium: '200ms', slow: '350ms',
      },
      transitionTimingFunction: {
        standard: 'cubic-bezier(0.2, 0, 0, 1)',
        enter: 'cubic-bezier(0, 0, 0, 1)',
        exit: 'cubic-bezier(0.2, 0, 1, 1)',
      },
      zIndex: {
        base: '0', raised: '100', dropdown: '200', sticky: '300',
        overlay: '400', modal: '500', popover: '600', toast: '700',
      },
    },
  },
};
```

### 8.3 Figma Variable → Code Mapping

| Figma variable path | Code token | Resolution status |
|---|---|---|
| `Design Tokens/float/Space/*` | `--space-*` / Tailwind `spacing.*` | ✅ Fully resolved |
| `Design Tokens/float/Radius/*` | `--radius-*` / Tailwind `borderRadius.*` | ✅ Fully resolved |
| `Design Tokens/float/Dimension/*` | `--dimension-control-*` | ✅ Fully resolved |
| `Design Tokens/float/Icon Size/*` | `--icon-size-*` | ✅ Fully resolved |
| `Design Tokens/float/Opacity/*` | `--opacity-*` | ✅ Fully resolved |
| `Design Tokens/float/Border Width/*` | `--border-width-*` | ✅ Fully resolved |
| `Design Tokens/float,string/Motion/*` | `--motion-*` | ✅ Fully resolved |
| `Design Tokens/color/{Gray,Purple,Pink,Red,Green,Blue,Dark Blue,Stone}/*` | (primitives — not directly exposed in code; consume only via semantic layer) | ⚠️ Names confirmed, ramp hex mostly unresolved |
| `Semantic colors/color/text/*` | `--color-text-*` | ⚠️ 2 of 7 resolved |
| `Semantic colors/color/icon/*` | `--color-icon-*` | ⚠️ 0 of 7 resolved |
| `Semantic colors/color/border/*` | `--color-border-*` | ⚠️ 1 of 3 resolved |
| `Semantic colors/color/background/*` | `--color-background-*` | ⚠️ 3 of 16 resolved |
| `Semantic colors/elevation/surface/*` | (map to a `--elevation-*` custom property or a shadow/bg pairing) | ⚠️ Names confirmed only |
| `Semantic colors/pill/{hue}/{bg,text,border}` | `--pill-{hue}-{bg,text,border}` | ⚠️ Names confirmed only (1 hue's real-world hex sampled: warning/amber) |

> **Action required before production**: Open the Figma file → Variables panel → export/inspect the `Design Tokens` and `Semantic colors` collections directly (via Figma's own "Export variables" or the Dev Mode variables inspector) to fill every ⚠️ row above with its true hex/value. This document intentionally avoids fabricating those values.

### 8.4 Icon Library Dependency

**Package**: [`lucide-react`](https://lucide.dev/icons/) (or the equivalent Lucide package for the target framework — `lucide-vue-next`, `lucide-svelte`, etc.) — this is the confirmed icon source for the system ([§1.14](#114-iconography)).

```tsx
// Example: an Icon-Only Button using a Lucide icon at the token-driven size
import { Search } from 'lucide-react';

<Button variant="tertiary" content="icon-only" aria-label="Search">
  <Search size={16} strokeWidth={2} /> {/* size = --icon-size-small token */}
</Button>
```

- Bind `size` to the matching `Icon Size/*` token (16/20/24/32px) rather than a hardcoded number, so icon scale stays in sync with the design system if those tokens change.
- Do not set a hardcoded `color`/`stroke` on individual `<Icon />` usages — let it inherit `currentColor` from the semantic `color/icon/*` token applied to the parent/wrapper.
- Maintain a lookup table (Figma icon-instance name → Lucide icon name) as icons are implemented, to avoid ad-hoc/inconsistent icon choices across the codebase.

### 8.5 Component Architecture (recommended folder structure)

```
src/
├─ design-system/
│  ├─ tokens/
│  │  ├─ primitives.css        # Gray/Purple/Pink/Red/Green/Blue/DarkBlue/Stone ramps
│  │  ├─ semantic.css          # color/text, color/icon, color/border, color/background
│  │  ├─ elevation.css         # elevation/surface/* (+ shadow scale once published, §7.3.4)
│  │  ├─ pill.css              # 13-hue pill/{hue}/{bg,text,border}
│  │  ├─ spacing.css           # space.*
│  │  ├─ radius.css            # radius.*
│  │  ├─ dimension.css         # Dimension/control-*
│  │  ├─ motion.css            # Motion/duration/*, Motion/easing/*
│  │  ├─ opacity.css           # Opacity/*
│  │  └─ typography.css        # font-family/heading (Funnel Display), type scale
│  ├─ primitives/               # unstyled/low-level: Icon, VisuallyHidden, FocusRing
│  ├─ components/
│  │  ├─ Button/
│  │  ├─ Input/  Select/  Checkbox/  Radio/  Toggle/
│  │  ├─ Card/   Table/  (HeaderCell, BodyCell)
│  │  ├─ Tabs/   Breadcrumb/  Pagination/
│  │  ├─ Badge/  Tag/  Avatar/  AvatarGroup/
│  │  ├─ Tooltip/  Modal/  Drawer/  Toast/  Alert/
│  │  ├─ ProgressBar/  Spinner/  Divider/  Skeleton/  EmptyState/
│  │  └─ Nav/  (NavButtons, NavItem, TopBarNav)
│  └─ patterns/                 # composed, product-specific
│     ├─ RecordHeader/          # ticket-header pattern (§3.25) — reusable across entities
│     ├─ Workbench/             # 3-pane list+detail layout (§4.3)
│     ├─ KpiCard/                # §3.23, pending confirmation
│     └─ AiActionButton/         # gradient-text "Ask VIQAI" pattern (§3.22) — formalize as Button[Style=AI]
└─ app/
   └─ (feature code consumes design-system/* only — never raw hex/px)
```

### 8.6 Component Prop / Variant Naming (code-facing, derived from Figma variant properties)

```tsx
// Example: Button — mirrors the Figma variant properties 1:1
type ButtonStyle = 'primary' | 'secondary' | 'tertiary' | 'danger'; // + 'ai' (recommended, §7.3.2)
type ButtonSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';
type ButtonContent = 'label-only' | 'icon-label' | 'label-icon' | 'icon-label-icon' | 'icon-only';
// State (hover/pressed/focused/disabled) is handled by CSS pseudo-classes / the `disabled` prop —
// never a separate `state` prop, since these are not designer-chosen but browser/user-driven.

interface ButtonProps {
  variant?: ButtonStyle;   // default: 'primary'
  size?: ButtonSize;       // default: 'md'
  content?: ButtonContent; // inferred from children/icon props rather than required
  disabled?: boolean;
  loading?: boolean;       // maps to Opacity/loading + Spinner, not a Figma-confirmed variant — implement per §3.18
}
```

### 8.7 Handoff Checklist

- [ ] Export true hex values for every ⚠️-flagged token in [§8.1](#81-css-variables-root-token-set)/[§8.3](#83-figma-variable--code-mapping) directly from Figma's Variables panel.
- [ ] Confirm Button Hover/Pressed/Focused colors per style directly from the `State=Hover|Pressed|Focused` symbols (not fabricated here, §2.5).
- [ ] Confirm full anatomy for Input, Select, Dropdown Menu, Checkbox, Radio, Toggle, Card, Tabs, Breadcrumb, Pagination, Tooltip, Modal, Drawer, Toast, Alert, Progress Bar, Spinner directly against their Figma pages (all flagged ⚠️ in §3).
- [ ] Contrast-audit the full 13-hue pill palette + brand gradient midpoint/endpoint (§6.1).
- [ ] Resolve the Button Icon-Only XL (48px) vs. `Dimension/control-xl` (52px) discrepancy (§2.4).
- [ ] Decide on and implement a real Elevation/shadow scale (currently one ad-hoc value, §1.7/§7.3.4).
- [ ] Formalize the AI gradient-text button treatment as a first-class `Button[Style=AI]` variant + `color/text/ai` token (§3.22/§7.3.2).
- [ ] Design and confirm mobile/tablet responsive frames for the Command Center workbench (§4.2).
- [ ] Migrate any screens still bound to the legacy `--scale/*`/`--primary-50…900` token layer onto the canonical `color/*` system (§1.3.3/§7.3.1).
- [ ] Build a Figma icon-instance-name → [Lucide](https://lucide.dev/icons/) icon-name lookup table so every icon usage in the file has an unambiguous code equivalent (§1.14/§8.4).

---

*End of document. This file was generated by directly inspecting the Figma file "Design System CC" (`xzy7YzlLGft4NqEDpv54jx`) via the Figma MCP server — page metadata, component/variant names, rendered component code (CSS/Tailwind), and Figma Variable names/descriptions. Every ⚠️ Assumption callout marks a value or structure that could not be directly resolved in this session and must be validated in Figma before production use. Nothing in this document was fabricated without a corresponding piece of evidence from the file.*
