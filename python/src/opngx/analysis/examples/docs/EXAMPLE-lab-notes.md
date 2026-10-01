# Example: lab notes (your own docs)

Every Markdown file in this folder shows up in the studio's **Docs** tab under
**My docs**, next to the shipped guides, and is included in the full-text
search. Use it for protocols, calibration values, or notes on a module you
wrote.

## Calibration

| setup | objective | pixel size |
|---|---|---|
| trap A | 60x oil | 0.0833 um/px |
| trap B | 40x air | 0.125 um/px |

Pass the pixel size to the analysis, for example
`brownian_motion.pixel_size_um = 0.0833`.

## Editing

Open this file in the **Editor** tab. Markdown is highlighted there, and
**Save** updates the Docs tab immediately. You can rename it or delete it;
opngx copies the samples only once and will not put them back.
