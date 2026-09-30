# Native browser zoom capability check

- Tested exact application source: 57a3cfb99aaf53dcf63628640c4b17d26fccf0fb.
- Playwright page started at a 1280x720 CSS viewport with DPR 1.0000000149.
- Pressed Ctrl+Shift+Equal and Ctrl+Equal. The page stayed at innerWidth 1280, DPR 1.0000000149, and visualViewport.scale 1.
- CUA surface inventory returned apps=[] and browsers=[]. Creating an IAB tab and a Chrome tab both returned "Browser is not available".
- The available Playwright surface sends page keyboard events but did not control browser chrome zoom. Actual native 200% zoom is unverified. No CSS viewport proxy is presented as native zoom, and no machine setting changed.
