---
"openvchange": patch
---

Check presets before using them. A preset with a wrong value, such as text where a number belongs, is now refused with a message that names the setting, and nothing from it is applied. Values outside a slider's range are brought into range and mentioned. Failures to read or write a preset file are reported in the status line. Loading a preset while audio is running no longer changes the buffer size or the number of pitch voices under the running stream, which could break pitch shifting; those two settings take effect at the next start.
