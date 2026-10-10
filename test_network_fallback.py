import io
import os
import urllib.error
import unittest
from unittest.mock import patch
import http_state
import monitor

URL="https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/europe/"

class FakeResponse:
    status=200
    url=URL
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.body

class NetworkFallbackTests(unittest.TestCase):
    def test_403_never_uses_proxy_or_browser(self):
        with patch.dict(os.environ,{"THS_FETCH_MODE":"http","THS_PROXY_FALLBACK":"1",
                                    "THS_BROWSER_FALLBACK":"1"}):
            with patch.object(monitor.http_state,"fetch_state",side_effect=http_state.AccessRestricted("HTTP 403")) as fetch:
                with patch.object(monitor.http_state,"broker_usable") as broker:
                    with patch.object(monitor,"_browser_state") as browser:
                        with patch.object(monitor,"_pause_access") as pause:
                            with self.assertRaises(http_state.AccessRestricted):
                                monitor.get_state(URL)
                            pause.assert_called_once()
                        self.assertEqual(fetch.call_count,1)
                        broker.assert_not_called();browser.assert_not_called()

    def test_connection_error_uses_validated_broker(self):
        expected={"search":{"listings":{}}}
        with patch.dict(os.environ,{"THS_FETCH_MODE":"http","THS_PROXY_FALLBACK":"1",
                                    "THS_BROWSER_FALLBACK":"1"}):
            with patch.object(monitor.http_state,"fetch_state",
                              side_effect=[http_state.TransportError("timeout"),expected]) as fetch:
                with patch.object(monitor.http_state,"broker_usable",return_value=True):
                    with patch.object(monitor,"_browser_state") as browser:
                        self.assertEqual(monitor.get_state(URL),expected)
                        self.assertEqual(fetch.call_count,2)
                        self.assertEqual(fetch.call_args.kwargs["proxy_url"],http_state.LOCAL_BROKER)
                        browser.assert_not_called()

    def test_unavailable_broker_uses_browser_on_network_error(self):
        expected={"search":{}}
        with patch.dict(os.environ,{"THS_FETCH_MODE":"http","THS_PROXY_FALLBACK":"1",
                                    "THS_BROWSER_FALLBACK":"1"}):
            with patch.object(monitor.http_state,"fetch_state",side_effect=http_state.TransportError("timeout")) as fetch:
                with patch.object(monitor.http_state,"broker_usable",return_value=False):
                    with patch.object(monitor,"_browser_state",return_value=expected) as browser:
                        self.assertEqual(monitor.get_state(URL),expected)
                        self.assertEqual(fetch.call_count,1)
                        browser.assert_called_once_with(URL)

    def test_parser_failure_uses_browser_but_restricted_does_not(self):
        with patch.dict(os.environ,{"THS_FETCH_MODE":"http","THS_BROWSER_FALLBACK":"1"}):
            with patch.object(monitor.http_state,"fetch_state",side_effect=http_state.ParseError("html changed")):
                with patch.object(monitor,"_browser_state",return_value={"search":{}}) as browser:
                    self.assertEqual(monitor.get_state(URL),{"search":{}})
                    browser.assert_called_once()

    def test_429_response_never_falls_back(self):
        err=urllib.error.HTTPError(URL,429,"Too Many Requests",{},None)
        with patch.object(http_state.urllib.request,"urlopen",side_effect=err):
            with self.assertRaises(http_state.AccessRestricted):
                http_state.fetch_state(URL)

    def test_challenge_page_never_falls_back(self):
        body=b"<html><title>Just a moment...</title><p>verify you are human</p></html>"
        with patch.object(http_state.urllib.request,"urlopen",return_value=FakeResponse(body)):
            with self.assertRaises(http_state.AccessRestricted):
                http_state.fetch_state(URL)

    def test_access_restriction_persists_cooldown(self):
        import pathlib,tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch.object(monitor,"OUT",pathlib.Path(td)):
                with patch.object(monitor.http_state,"fetch_state",
                                  side_effect=http_state.AccessRestricted("HTTP 429")) as fetch:
                    with patch.dict(os.environ,{"THS_FETCH_MODE":"http"}):
                        with self.assertRaises(http_state.AccessRestricted):
                            monitor.get_state(URL)
                        self.assertTrue((pathlib.Path(td)/"http-access-cooldown.json").is_file())
                        with self.assertRaisesRegex(http_state.AccessRestricted,"cooldown"):
                            monitor.get_state(URL)
                        self.assertEqual(fetch.call_count,1)

    def test_rejects_non_broker_proxy(self):
        with self.assertRaises(http_state.FetchError):
            http_state.fetch_state(URL,proxy_url="http://arbitrary-exit:8080")

if __name__=="__main__":
    unittest.main()
