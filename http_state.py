"""Public-HTML HTTP transport. No browser, login, cookies or private API."""
import json
import urllib.parse
import urllib.request
import urllib.error

STATE_TAG = '<script id="__INITIAL_STATE__" type="application/json">'
HOST = "www.trustedhousesitters.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
MAX_BYTES = 4 * 1024 * 1024

class FetchError(RuntimeError):
    pass

def fetch_state(url, timeout=12):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname != HOST or p.username or p.password:
        raise FetchError("Refusing non-TrustedHousesitters URL")
    if not p.path.startswith("/house-and-pet-sitting-assignments/"):
        raise FetchError("URL outside public house-sit listing paths")
    req = urllib.request.Request(url,headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Accept-Language":"en-US,en;q=0.8"
    })
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            if response.status != 200:
                raise FetchError("Unexpected HTTP response "+str(response.status))
            final = urllib.parse.urlsplit(response.url)
            if final.scheme!="https" or final.hostname!=HOST:
                raise FetchError("Unexpected redirect")
            data=response.read(MAX_BYTES+1)
    except urllib.error.HTTPError as exc:
        # No retries around security challenges or rate limits.
        raise FetchError("HTTP "+str(exc.code)+" (not retried)") from None
    except (urllib.error.URLError,TimeoutError) as exc:
        raise FetchError("Connection error: "+type(exc).__name__) from None
    if len(data)>MAX_BYTES:
        raise FetchError("HTML exceeds 4 MiB safety limit")
    html=data.decode("utf-8","replace")
    if STATE_TAG not in html:
        raise FetchError("Public page contains no structured state")
    try:
        payload=html.split(STATE_TAG,1)[1].split("</script>",1)[0]
        state=json.loads(payload)
    except (ValueError,IndexError) as exc:
        raise FetchError("Malformed embedded JSON state") from exc
    if not isinstance(state,dict) or "search" not in state:
        raise FetchError("Unexpected JSON structure")
    return state
