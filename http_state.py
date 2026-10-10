"""Public HTML HTTP transport for TrustedHousesitters.

Direct requests are the default. A prevalidated *local* proxy-broker route may
be used for transient network errors only; never for 403/429 or challenges.
No logins, cookies, passwords, API tokens or authenticated traffic.
"""
import json
import urllib.parse
import urllib.request
import urllib.error

STATE_TAG = '<script id="__INITIAL_STATE__" type="application/json">'
HOST = "www.trustedhousesitters.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
MAX_BYTES = 4 * 1024 * 1024
LOCAL_BROKER = "http://127.0.0.1:20140"

class FetchError(RuntimeError):
    pass

class AccessRestricted(FetchError):
    """Server explicitly rejected, challenged or rate-limited this client."""

class TransportError(FetchError):
    """DNS/connect/timeout error, not an HTTP refusal."""

class ParseError(FetchError):
    """Ordinary HTTP-200 HTML lacks the expected public application state."""

def validate_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname != HOST or p.username or p.password:
        raise FetchError("Refusing non-TrustedHousesitters URL")
    if not p.path.startswith("/house-and-pet-sitting-assignments/"):
        raise FetchError("URL outside public house-sit listing paths")

def _is_challenge(html):
    snippet=html.lower()[:200000]
    return any(marker in snippet for marker in (
        "cf-chl-","challenge-platform","verify you are human",
        "checking your browser before accessing","captcha challenge",
        "perimeterx","px-captcha","unusual automated traffic",
        "access to this page has been denied","just a moment...</title>"
    ))

def fetch_state(url, timeout=12, proxy_url=None):
    validate_url(url)
    if proxy_url not in (None,LOCAL_BROKER):
        raise FetchError("Only the canonical localhost broker is allowed")
    req = urllib.request.Request(url,headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.8"
    })
    opener=(urllib.request.build_opener(urllib.request.ProxyHandler({"https":LOCAL_BROKER}))
            if proxy_url else None)
    try:
        call=opener.open if opener else urllib.request.urlopen
        with call(req,timeout=timeout) as response:
            if response.status != 200:
                raise AccessRestricted("Unexpected HTTP "+str(response.status))
            final = urllib.parse.urlsplit(response.url)
            if final.scheme!="https" or final.hostname!=HOST:
                raise FetchError("Unexpected redirect")
            data=response.read(MAX_BYTES+1)
    except urllib.error.HTTPError as exc:
        raise AccessRestricted("HTTP "+str(exc.code)+" (not retried)") from None
    except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as exc:
        raise TransportError("Network error: "+type(exc).__name__) from None
    if len(data)>MAX_BYTES:
        raise FetchError("HTML exceeds 4 MiB safety limit")
    html=data.decode("utf-8","replace")
    if _is_challenge(html):
        raise AccessRestricted("Security challenge in HTTP response")
    if STATE_TAG not in html:
        raise ParseError("Public page contains no structured state")
    try:
        payload=html.split(STATE_TAG,1)[1].split("</script>",1)[0]
        state=json.loads(payload)
    except (ValueError,IndexError) as exc:
        raise ParseError("Malformed embedded JSON state") from exc
    if not isinstance(state,dict) or "search" not in state:
        raise ParseError("Unexpected JSON structure")
    return state

def broker_usable():
    """Never attempt free-proxy transport unless broker has a validated pool."""
    try:
        req=urllib.request.Request(LOCAL_BROKER+"/v1/pool?target=trustedhousesitters")
        with urllib.request.urlopen(req,timeout=2) as result:
            state=json.load(result)
        pool=state.get("usable")
        return bool(pool) if isinstance(pool,list) else bool(isinstance(pool,int) and pool>0)
    except (ValueError,urllib.error.URLError,TimeoutError,OSError):
        return False
