# Noto Nastaliq Urdu

The unmodified variable TrueType font is bundled as [NotoNastaliqUrdu.ttf](NotoNastaliqUrdu.ttf)
and registered by the app through `page.fonts`. The original file is
`NotoNastaliqUrdu[wght].ttf` from the
[Google Fonts repository](https://github.com/google/fonts/tree/main/ofl/notonastaliqurdu).
Only the local filename changed; the font itself was not modified.

Copyright 2022 The Noto Project Authors. Redistribution follows the included
[SIL Open Font License](OFL.txt). Keep that license with the font in desktop/APK builds.

SHA-256:
`98a4787f34eb6fde57fb9a1121a8f216301196ab0da98ea110cad581be8abbcd`

If the local asset is absent, desktop text uses the platform font. The Android build
bundles this font through Flet's assets directory; Flutter can fall back to a system
font if it cannot load it. Font fallback may have different Urdu shaping/appearance.
