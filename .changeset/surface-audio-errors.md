---
"openvchange": patch
---

Show audio failures instead of hiding them. If the stream cannot be started, the status line now says why and the window stays ready for another attempt, where it used to read "Running" with no sound. If an effect fails while running, the output goes silent and the stream stops with a message. It used to pass the unprocessed microphone signal through without any indication.
