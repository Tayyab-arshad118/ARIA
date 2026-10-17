# Bundled backend data

[Project handbook](../../README.md) · [Backend folder](../README.md)

This directory contains the small version-controlled resources used by the local text and phrase services. It can also be the fallback runtime location, but private generated data must not be committed.

## Files included in Git

| File | Purpose |
| --- | --- |
| [roman_urdu_dictionary.json](roman_urdu_dictionary.json) | Roman spelling → Urdu mapping, including informal variants; used for local conversion and prediction vocabulary. |
| [default_phrases.json](default_phrases.json) | Initial 60 phrases, with IDs, Roman wording, Urdu wording, and category. |

The phrase seed has five categories: needs, medical, family, greetings, and custom. It is imported once per initialized database. Editing the seed file does not overwrite existing user phrase records at every startup.

## Files that may be generated locally

Depending on active settings, runtime files may include `aria.sqlite` and sidecars, `voices/.fernet.key`, downloaded model folders, logs, or evaluation reports. The standard private setup normally stores runtime user data elsewhere. Check `DATA_DIR`, model paths, and the ignore rules before assuming this directory is safe to upload in full.

The repository dictionary/seed remain readable JSON resources. Enrolled voices, user phrase content, and caches belong in the encrypted runtime database, not in these shared source files.

## Editing a dictionary or seed

Use UTF-8, valid JSON, appropriate script, stable IDs for existing seeds, and the supported category names. Review spelling and meaning manually; a valid JSON document can still contain a bad phrase. Local conversion cache identity incorporates the dictionary version, so changing dictionary contents affects future lookups.

Run [backend text/phrase tests](../tests/README.md) after changing resources. Resetting a live user's bank to test seed changes would delete customizations; use a temporary test data directory instead.
