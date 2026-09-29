---
"openvchange": patch
---

Fix the de-esser. It used to turn down the whole signal, voice included, by the full reduction in a single step whenever sibilance crossed the threshold. It now turns down only the band from 5 to 8 kHz, by as much as that band exceeds the threshold and at most by the reduction setting, and it does so gradually. Presets that use the de-esser will sound different.
