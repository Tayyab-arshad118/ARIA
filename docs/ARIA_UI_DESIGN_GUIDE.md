# ARIA UI — single-patient design guide

## Product model
ARIA is a personal assistive communication app for **one intended voice user**. A trusted helper may assist with the **same patient's** voice enrollment; this does not create another person's voice or transfer consent or ownership.

## Setup journey
1. Welcome / ARIA logo.
2. Speaking-language preference.
3. Optional patient PIN and account recovery (recovery code is provided by the backend after setup, not chosen on the welcome screen).
4. Choose **I'm setting up my voice** or **I'm helping someone**.
5. Enroll an existing recording of the intended patient. Direct microphone capture is **not implemented** in the current Flet client; do not suggest that it is.
6. Confirm patient consent or a valid representative basis with a recording-specific authorization reference. A caregiver role alone is not authorization.
7. Continue into speaking when a compatible authorized voice is available. The licensed ARIA synthetic voice is an optional fallback, only if configured.
8. On everyday launches, keep the speaking composer and quick phrases accessible; do not force onboarding for each operation.

## Navigation and interaction
- **Speak:** text in Urdu/native or Roman mode, suggestion and speech controls.
- **Phrases:** searchable and reusable phrases.
- **Voice:** select/replace the patient's authorized recording and manage the patient profile.
- **Profile:** account PIN, recovery, trusted helper access, connection and privacy; speech settings contain expression, speed and research-only safety controls.

Helper permissions use plain-language labels in the app and map to the backend's scoped **speak / enroll / manage** permissions. Backend scope enforcement remains intact and must not be bypassed.

## Visual standards
- ARIA blue primary CTA, high-contrast dark text, white/soft-grey backgrounds and rounded low-chrome cards.
- Meaningful primary action anchored consistently; no redundant status pill/banners.
- Smooth ~260 ms fade navigation; soft pressed/selected feedback. Avoid excessive animation.
- Provide a reduced-motion path for web animations and honor operating-system accessibility settings in future native builds.
- Keep consent wording readable and clear even with assistive text scaling.

## Safety and implementation reality
- The **HTML gallery** is a navigable *design preview*, not the running speech application. Its progress, voice test and speech controls must not claim to process or synthesize actual audio.
- The **Flet app** retains its existing backend authorization, watermark policy, voice storage, encryption, PIN, playback and phrase logic.
- UI regression checks run through GitHub Actions. Desktop and Android screenshot/device acceptance should still be checked before merging.
