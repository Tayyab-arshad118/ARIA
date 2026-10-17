# Interface screenshots

[Project handbook](../../README.md) · [Documentation folder](../README.md)

These PNGs document several interface revisions and viewport sizes. They are snapshots of a running preview, not live status or proof of GPU inference. Older `compose-*` images may show earlier styling; use newer onboarding/speak captures when comparing the current flow.

## Representative screens

| Screen | Image |
| --- | --- |
| Welcome | [onboarding-welcome.png](onboarding-welcome.png) |
| Connect | [onboarding-connect.png](onboarding-connect.png) |
| Compact voice selection | [onboarding-voices-360x640.png](onboarding-voices-360x640.png) |
| Composer | [onboarding-compose.png](onboarding-compose.png) |
| English fields, light | [speak-english-light.png](speak-english-light.png) |
| English fields, dark | [speak-english-dark.png](speak-english-dark.png) |
| Quick phrases | [quick-phrases-phone.png](quick-phrases-phone.png) |

## Naming and regeneration

`-360x640` indicates a compact 360 × 640 viewport. The flow capture helper's default is 390 × 844. Older general captures use other desktop/mobile dimensions.

Instructions and prerequisites are in [desktop tests](../../aria_desktop/tests/README.md). Inspect the result after capture: animation, loading state, a disconnected backend, or different saved voices can change what is visible. Do not include API keys, private text, or personal files in a screenshot intended for publication.

To review layout, check small/normal viewports, light/dark contrast, language chips, native-script shaping, fixed playback/Continue actions, and long content scrolling. A visible offline pill in an image only describes that capture session.
