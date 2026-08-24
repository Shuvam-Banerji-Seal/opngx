# opngx v1.5.2

**Developer:** Shuvam Banerji Seal

## Fixed (reported from live use)
- **Black arrows / black text in Help** — the frame-viewer ◀ ▶ (and other
  glyph-drawn Qt standard icons) rendered black on the dark theme under
  QSS; they are gone, the crisp white ◀ ▶ ▶ ■ ✓ glyphs remain. Menu bar
  and dropdown items now have explicit white-on-dark item rules, and the
  Help guides set their document text color directly.

## New: richer recording facts, everywhere
- Probe (and `opngx info`) now show, straight from the binary:
  **frames on disk vs XML count** (✓ match / ⚠ MISMATCH — truncated or
  stale sidecar), **clock span** and **effective fps** from the first→last
  frame ticks (µs clock), the vendor's **FramerateReal (achieved)** rate,
  and a plain-language **pixel fidelity** line (8-bit sensor mono ·
  reference = vendor curve, clips raw ≥ 139 · raw = lossless).
- C parser gained `FramerateReal`; it flows into `metadata.json` too.
- O(1) probe: the clock sample reads exactly two 8-byte headers, so
  probing a 50k-frame bin stays instant.

## Performance
- **Verifier scratch reuse**: decode buffers are per-worker and reused —
  `verifybin` dropped from ~1.2 s to ~0.45 s on a 4 000-frame set
  (~2.8×); full 50k verification drops from ~21 s toward ~7 s.
  19/19 pixel-exact gates unchanged.
