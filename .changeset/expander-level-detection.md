---
"openvchange": patch
---

Fix the expander/gate. It judged the level from single samples, so even a signal well above the threshold was turned down by 5 dB or more. It now measures the level properly and leaves such signals untouched. Attack and release were also the wrong way round: the gate took over 100 ms to open, cutting off the start of words, and snapped shut in 20 ms. Attack now sets how fast the gate opens and release how fast it closes. Presets that use the expander will sound different, and may want a lower threshold.
