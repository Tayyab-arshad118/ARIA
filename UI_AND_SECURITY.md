# Groq conversion, Apple-inspired UI, and backend hardening

The app now opens in a clean light theme with white cards, blue accents, system typography,
a Cupertino-style Compose/Phrases switch, and a separate voice panel on wide windows.
It stacks on smaller screens. The moon/sun button switches to the matching dark palette.
The phrase library has search, category filters, favorites and recents. Existing voice,
speech, verification, emotion-reference and playback features remain available.

Rendered previews: [light desktop](docs/screenshots/compose-light.png),
[dark desktop](docs/screenshots/compose-dark.png), and [mobile layout](docs/screenshots/compose-mobile.png).
The screenshots show the real app without an enrolled voice; speech is intentionally disabled
until a compatible voice is available. Browser layout checks do not substitute for an APK test.

## Groq and the expanded dictionary

This machine is configured with `LLM_TRANSLIT_ENABLED=true`, `LOCAL_ONLY=false`, and
`TRANSLIT_STRATEGY=api_first`. Roman Urdu goes to Groq first, including sentences whose
words are already in the dictionary. Existing Urdu script passes through unchanged.
The response is checked for Urdu script and preserved digits before use.

A live request converted `me theek hu mujhe pani chahiye` to
`میں ٹھیک ہوں مجھے پانی چاہیے`, with `method_used=llm`.
Groq uses the [official OpenAI-compatible endpoint](https://console.groq.com/docs/openai).

The [dictionary](aria_backend/data/roman_urdu_dictionary.json) grew from **809 to 2,826
Roman spellings**, covering **1,087 distinct Urdu entries**. It includes `me`, `mei`,
`mey`, `m`, `mujy`, `mjy`, `mje`, `ni`, `thk`, and expanded daily-life, family, food,
mobility and medical vocabulary. Roman spelling remains ambiguous; API context is useful
for words with several meanings. The dictionary is a fallback, not a claim of complete
language coverage.

When Groq is unavailable, rejects a request, reaches a limit, returns oversized data, or
returns invalid text, the app uses dictionary/rule conversion. In API-first mode these
fallback results expire after 60 seconds so a restored API is tried again. Successful
results are cached encrypted. `TRANSLIT_STRATEGY=dictionary_first` restores the earlier
behavior; `LOCAL_ONLY=true` always disables Groq regardless of the strategy.

## Private configuration on this machine

Credentials are stored outside the OneDrive project directory:

```text
%LOCALAPPDATA%/ARIA/
├── config/backend.env    # Groq key, backend token, API policy and runtime settings
├── config/desktop.env    # Backend URL/token only; no Groq key
└── data/                 # SQLite and encrypted voice/cache data plus local keyfile
```

The Windows directory ACL grants access to the current user and SYSTEM. The supplied
Groq key was not written to project source or example files. A separate random 48-byte
token was generated for backend authentication and shared with the desktop configuration.
Do not copy either private configuration file into the app/build directory.

The key pasted in chat should be rotated in Groq. To replace it without putting it on a
command line, run this from the project root and use the hidden prompt:

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/configure_local.py
```

Restart the backend and app afterward. Existing connection settings are preserved;
the helper keeps an existing configured data directory or existing project database.
It does not silently move or delete existing voice data. This workspace had no runtime
database before configuration, so its runtime data now goes directly to the private folder.

Configuration precedence is: process environment → selected environment file → defaults.
The backend uses `ARIA_BACKEND_ENV_FILE` if provided, otherwise the private `backend.env`
when present, otherwise the project `aria_backend/.env`. The desktop uses
`ARIA_APP_ENV_FILE`, then private `desktop.env`, then `aria_desktop/.env`.
On non-Windows systems, private configuration is under `$XDG_CONFIG_HOME/ARIA/config`
or `~/.config/ARIA/config`. These discovery variables are optional file-path overrides,
not credentials. The app reads its file without copying keys into global process variables.

## Backend protections

The private configuration enables the following:

- A strong bearer token is required on **every** route. Authentication failures return 401.
- Binding is restricted to `127.0.0.1`; configuring a non-loopback bind without a strong
  key is rejected. The documented launcher ignores forwarded-IP headers.
- Explicit allowed hosts protect against unexpected Host headers. Browser requests with
  an unapproved Origin are rejected. Native Flet requests need no browser-origin exception.
- A bounded per-client request budget and failed-authentication limit throttle abuse.
  Existing concurrent-request, body-size, upload-size and timeout limits remain active.
- API docs/OpenAPI are disabled by default. Responses have `no-store`, `nosniff`,
  `no-referrer` and frame-denial headers, including authentication errors.
- Groq responses are size-limited, TLS-verified and never followed through redirects.
- User content, biometric data and caches remain encrypted as described in the phase
  guides. Raw recordings remain off by default. Errors do not echo credentials or input.

Settings are documented in [the environment template](aria_backend/.env.example):
`REQUIRE_AUTH`, `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, `DOCS_ENABLED`, `RATE_LIMIT_REQUESTS`,
`RATE_LIMIT_WINDOW_SECONDS`, `AUTH_FAILURE_LIMIT`, `TRANSLIT_STRATEGY`,
`GROQ_MAX_RESPONSE_BYTES`, and `TRANSLIT_FALLBACK_CACHE_SECONDS`.

The code still supports an explicitly configured local development mode without auth;
the private setup on this machine enables `REQUIRE_AUTH=true`. Copying only the example
file does not generate credentials—use the setup helper for a protected installation.
If you later enable LAN access, configure the actual host/IP allowlist and use HTTPS for
untrusted networks. HTTP loopback protection is not a public-server deployment design.
Browser preview is for local UI testing; the supported application remains the native
Flet desktop/Android client. Keep the preview bound to loopback.

These measures reduce exposure; they are not a penetration-test certification or a
guarantee against every attack. Anyone who can read both the local encryption key and
database can decrypt its content. Host administrators and compromised user accounts remain
outside that protection. Strict speech verification remains optional and best-effort.

## Run

No new runtime package was introduced. From the project root, terminal 1:

```powershell
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

In terminal 2, from the project root:

```powershell
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

Both automatically read the private configuration. Add your current Colab URL/key to
the private backend configuration (or use the existing authenticated runtime-update CLI)
for voice generation. Groq transliteration works without Colab; speech still needs a
configured Colab session and enrolled voice.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite passes **167 tests**. Added checks cover API-first routing, retrying stale local
fallbacks, response-size bounds, shorthand such as `me thk hu`, authentication, Host/Origin
blocking, rate limits, disabled docs, theme switching, navigation and phrase search.
The running backend returned 401 without its token and 200 with it. A live Groq request
was also verified. Real Colab/native audio and Android acceptance limits from the earlier
guides still apply.
