# Supporting documentation assets

[Project handbook](../README.md)

The main README is the single complete handbook. This folder contains supporting visual material rather than another competing set of startup instructions.

## Contents

[screenshots](screenshots/) contains desktop and phone-sized UI captures. These are snapshots of several revisions, not live status or proof of model quality. Older `compose-*` images can show earlier styling.

| Screen | Example |
| --- | --- |
| Welcome | [onboarding-welcome.png](screenshots/onboarding-welcome.png) |
| Connection | [onboarding-connect.png](screenshots/onboarding-connect.png) |
| Compact voice selection | [onboarding-voices-360x640.png](screenshots/onboarding-voices-360x640.png) |
| English, light | [speak-english-light.png](screenshots/speak-english-light.png) |
| English, dark | [speak-english-dark.png](screenshots/speak-english-dark.png) |
| Quick phrases | [quick-phrases-phone.png](screenshots/quick-phrases-phone.png) |

The `-360x640` suffix identifies a compact viewport; the flow capture helper defaults to 390 × 844. Regeneration instructions are in [desktop tests](../aria_desktop/tests/README.md). Inspect loading state, text shaping, small-window layout, and contrast before using a capture in the FYP. Do not capture credentials or private material. Screenshots do not replace accessibility testing or emotion/watermark measurements.

## Where information belongs

- End-user setup, architecture, privacy, configuration, APIs, maintenance, and troubleshooting belong in [the main handbook](../README.md).
- Implementation details belong in the README beside the relevant source folder.
- Images demonstrating a layout belong here, with meaningful filenames and no credentials.

The old numbered implementation-phase guides and duplicate setup/security pages have been consolidated. Use relative links so navigation works on GitHub and in a local checkout. Update links when moving files, and avoid screenshots that imply a mock/offline example is a real model-quality result.
