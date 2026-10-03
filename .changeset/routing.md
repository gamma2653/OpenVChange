---
"openvchange": minor
---

Route several inputs to several outputs, with a full set of controls on each route. The window now has a tab per route, and each route has the Main, Dynamics, and Advanced Settings tabs of its own: its input and output devices, its effects, its levels and clip lights, its buffer size and pitch voices, and its own shortcut to switch its effects. Add Route makes another, starting as a copy of the route shown, so one microphone can go to your headphones untouched and to a virtual cable with a changed voice, or several inputs can be mixed into one output. Devices with more than one channel can be used a channel at a time, which is how the inputs and outputs of a matrix such as VB-Audio Matrix are reached. With one route, which is how the app starts, everything works as before. More routes add up to two buffers of delay (roughly 40 ms at the default buffer size, less with a smaller one), because the devices no longer share one stream.
