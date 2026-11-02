# Contributing

This is an unofficial, personal-use listing monitor. Bug fixes and documentation improvements are welcome, particularly around caching, filtering and Telegram message formatting.

## Reporting a problem

Include the Python version, command used and a minimal redacted reproduction. If the problem concerns a changed page layout, describe the affected public fields and expected output rather than uploading someone else's complete listing.

**Never attach** login sessions, cookies, API tokens, Telegram chat IDs, exact home addresses, owner messages, private application notes, or the `data/` directory.

## Running checks

Use Python 3.10 or newer and run:

```sh
python3 -m unittest discover -p 'test_*.py'
```

Keep new parser and formatting tests deterministic and offline. Avoid live scraping during CI.

## Pull requests

- Keep changes focused, explain the behavior before/after and include the relevant tests.
- Respect site terms, robots rules, rate limits and authentication boundaries. Do not introduce anti-bot bypasses or credential harvesting.
- Keep credentials and collected records outside version control; update `.gitignore` if a new private artifact is introduced.
- Do not assume the site exposes fields (such as Wi-Fi or transport availability) that are absent from its public summary.

This repository has no declared open-source license; open an issue before proposing redistribution or licensing changes.
