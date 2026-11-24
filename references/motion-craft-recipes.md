# Full Reference Recipes & Craft Patterns (`mattypark/Motion-graphics-skill` §14)

Use these 4 complete aesthetic recipes as **creative building blocks to recombine** — never treat any single one as a fixed template, and **NEVER add continuous `#cam` zoom-in** on top of a motion scene (`scale: 1` locked camera is default).

## Shared Taste Principles Across All 4 Styles
1. **One accent color** (or one brand gradient) carries all emphasis; keep 90% of the canvas calm and high-contrast.
2. **Keywords get treatment; filler stays quiet** (ultra-thin/light filler + heavy/bold `2–4×` keyword).
3. **Every beat = a fresh visual idea; cut on the first syllable.**
4. **2D world first, real 3D only at peaks** (`Three.js` or perspective 2D→3D pop with thickness + rim light).
5. **Real proof floats cleanly as physical cards** (real press screenshots, archival photos, actual UI — never invented dark HUD telemetry boxes).
6. **Camera locked by default (`scale: 1`):** Motion comes from elements entering, transforming, flipping in 3D, inverting worlds, or drawing on — **NOT** from zooming the whole canvas. Confident editorial holds are a mark of taste.
7. **SFX mark changes** (new world, reveal, click, counter tick), not every word; silence right before/after a hero hit sells it.

---

## Recipe A · Premium Kinetic Caption & Proof Reel (9:16 or 16:9, Intensity 3–4)
- **Pairing:** Ultra-thin grotesk (`Inter 200` / `Space Grotesk 300`) white 80% for filler + heavy grotesk `2–3×` larger for the single keyword with **2-stop vertical gradient fill + subtle bevel/glow** (e.g. steel-teal `#2E7F95->#A7DCE6` or electric yellow `#FFE14A` with orange glow behind subject).
- **Moves:**
  - Words blur-in (`blur 12->0px`, `y +20->0`, `200ms easeOutCubic`) and exit by crisp letter dissolve.
  - Counter rolls (`easeOutCubic`) while 4–6 rounded photo/proof cards (`2px` crisp border, soft shadow) fan out in an arc (`scale 0 -> 1.06 -> 1`, `80ms` stagger).
  - Real screenshot/proof enters as a **tilted 3D plane** (`rotateZ -6°`, perspective depth).
  - Pill badges grow `dot -> circle -> pill` on the exact spoken keyword.
  - **Text behind subject:** use `rembg` cutout on the subject so giant display type sits cleanly behind the head/shoulders.
- **SFX:** Low `soft-thud` on first keyword, subtle ticks during counter roll, light `whoosh` on section pivot, nothing on filler.

---

## Recipe B · Cinematic Storyteller Documentary Multi-World (16:9, Intensity 4–5 for Hooks / 3 for Essay)
- **Core Idea:** Every sentence or beat enters a **distinct tactile world** (hard 1-frame punctuation cut between worlds — zero repetitive slide decks!).
- **Visual Devices to Mix:**
  - **Tactile Halftone Paper World:** Cream `#F1E8C8` halftone texture + **organic gobo leaf shadow** + `3%` grain; bold distressed headline inside a **design-tool selection box** (dashed outline + 4 square corner handles) that rotates and morphs into a circular badge.
  - **Torn-Paper Window Reveal:** Ragged paper edge tears open to expose real documentary footage underneath.
  - **Cutout Collage World:** Layered real photos/landmarks with depth parallax + handwritten marker accents (`Permanent Marker` / `p5.brush` strokes in `#FFD84A` or accent ink).
  - **3D Picture Frame Under Spotlight:** Dark studio stage, real archival photograph framed in 3D perspective with directional rim light and crisp date stamp.
  - **Archival B&W Beat:** High-contrast monochrome frame with subtle projector grain and clean minimal italic subtitle.
- **SFX:** `paper` rustle on tactile scenes, `whoosh` on world switches, `riser -> soft-thud` into hero reveal. Hits land on Frame 1 of each new world.

---

## Recipe C · SaaS / Tech Explainer 2D↔3D Launch (16:9, Intensity 2–3, Clarity-First Premium)
- **Opening:** Calm high-contrast stage; thin monospace line **scramble-decodes** the opening thesis; glowing accent orbs drift in and condense into crisp icons/nodes along a clean dock or axis.
- **2D↔3D Hero Peak:**
  - Real UI/diagram card flies in rotating in 3D (`rotateY 65° -> 0°`, `easeOutCubic`) while concentric accent rings expand behind (`120ms` stagger).
  - **3D→2D Collapse:** Shaded 3D object flattens cleanly into bold black line-art outline (`6–8px` stroke) and cuts sharply into real footage.
- **Typography:** Wide geometric display sans (`Clash Display` / `General Sans` / `Space Grotesk`); **word swap in the same slot** (`"Zero Alignment" -> "Zero Momentum"`); **tracking collapse** (`0.55em -> 0`) into final lockup; giant cropped keyword bleeding off one edge over a soft blurred brand-color gradient blob rising from below.
- **SFX:** Clean `ui-click` on triggers, airy `whoosh` on 3D flips, one clean `soft-thud` on the main reveal, then silence.

---

## Recipe D · Beat-Synced High-Contrast Brand Promo (16:9 or 9:16, Intensity 4)
- **Palette:** Sharp alternating contrast per beat: off-white `#FAF8FA` ↔ matte black `#0A0A0A` + **one electric accent** (e.g. `#FF6A1A` or `#2563EB`); one geometric display sans, hierarchy by extreme scale only.
- **Devices:**
  - **Directional Motion-Blur Echo:** Hero word enters with 4–6 offset echo copies in the accent color with stepping opacity (`0.45 -> 0.08`) trailing behind its motion vector.
  - **Card Snake:** 15–25 delayed copies of a proof/asset card sweeping cleanly along a smooth bezier arc.
  - **Stack -> 4×2 Grid Explosion:** Rotated card stack shuffles cleanly on beats, then opens into an organized 4×2 grid with 3D Y-flips; one card expands into a search chip / UI callout; background snaps from light to dark on click.
- **SFX:** Sparse `whoosh-pop` on opening kinetic words, `riser -> impact` on contrast inversion, `ui-click` on button morph.

---

## Anti-Shadow-Clip Padding Rule (Transparent PNG Overlays)
When rendering a standalone transparent overlay via `motion_runner.mjs --png ... --transparent`:
- Wrap the visual element inside a transparent flex/grid stage with `padding: 96px` (minimum `64px` or `3×` the largest `box-shadow`/`drop-shadow` blur + spread radius).
- Set `html, body { background: transparent; margin: 0; overflow: visible; }`.
- Never place `overflow: hidden` directly on a shadowed card wrapper (only on an inner text-line reveal mask!).
- Confirm `edge_alpha_clip: PASS` before adding the overlay to `edit_plan.json`.
