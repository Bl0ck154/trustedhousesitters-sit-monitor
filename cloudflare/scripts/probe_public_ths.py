#!/usr/bin/env python3
"""One-off, public unauthenticated site access diagnostic. Not a CAPTCHA workaround.

Only one GET; do not use sessions, cookies, credential files, rotating networks,
fake user-agents, parallel requests or retries. Never log HTML content.
"""
import urllib.error
import urllib.request

URL = "https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/europe/"
CHALLENGES = (
    b"verify that you're not a robot",
    b"javascript is disabled",
    b"just a moment",
    b"checking your browser",
    b"captcha",
)

try:
    req = urllib.request.Request(URL, headers={"Accept": "text/html,application/xhtml+xml"})
    try:
        response = urllib.request.urlopen(req, timeout=16)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.status
        ct = response.headers.get("Content-Type", "")
        url = response.geturl()
        body = response.read(96 * 1024).lower()
    challenged = any(marker in body for marker in CHALLENGES)
    structured = b"__initial_state__" in body
    print("HTTP status:", status)
    print("Content type:", ct.split(";")[0])
    print("Redirected off known site:", not url.startswith("https://www.trustedhousesitters.com/"))
    print("Security challenge detected:", challenged)
    print("Public structured data marker:", structured)
    print("Fetched bytes (bounded):", len(body))
    if status == 200 and structured and not challenged:
        print("RESULT: CANDIDATE_PUBLIC_HTML; NOT YET PARSER VERIFIED")
    elif challenged or status in (403, 429):
        print("RESULT: ACCESS_RESTRICTED; STOP, DO NOT RETRY")
    else:
        print("RESULT: NO_DATA; NEED NON-BYPASS DIAGNOSTICS")
except (TimeoutError, OSError, urllib.error.URLError) as error:
    print("RESULT: NETWORK_ERROR", type(error).__name__)
