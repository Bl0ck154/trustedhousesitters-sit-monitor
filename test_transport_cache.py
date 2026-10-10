import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import http_state
import monitor

class Response:
    status = 200
    url = "https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/europe/"
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def read(self,n):
        return ('<script id="__INITIAL_STATE__" type="application/json">'+json.dumps({"search":{"listings":{} }})+'</script>').encode()

class TransportCacheTests(unittest.TestCase):
    def test_public_http_embedded_json(self):
        with patch.object(http_state.urllib.request, "urlopen",return_value=Response()):
            data=http_state.fetch_state(Response.url)
        self.assertIn("search",data)

    def test_reject_external_host_and_private_paths(self):
        for url in ("http://www.trustedhousesitters.com/house-and-pet-sitting-assignments/europe/",
                    "https://evil.test/house-and-pet-sitting-assignments/europe/",
                    "https://www.trustedhousesitters.com/account/"):
            with self.assertRaises(http_state.FetchError):
                http_state.fetch_state(url)

    def test_cache_ttl_and_field_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=pathlib.Path(tmp)/"listings"
            target.mkdir()
            item={"listing_id":"123","assignment_id":"456","start":"2026-10-28",
                  "end":"2026-11-10","status":"open","title":"Cat sit",
                  "application_count":1,"verified_by_detail":True,
                  "observed_at":dt.datetime.now(dt.timezone.utc).isoformat()}
            (target/"456.json").write_text(json.dumps(item))
            with patch.object(monitor,"OUT",pathlib.Path(tmp)):
                self.assertIsNotNone(monitor.detail_cache(item,ttl_seconds=1800))
                self.assertIsNone(monitor.detail_cache({**item,"application_count":2},ttl_seconds=1800))
                self.assertIsNone(monitor.detail_cache({**item,"status":"reviewing"},ttl_seconds=1800))
                old={**item,"observed_at":(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=2)).isoformat()}
                (target/"456.json").write_text(json.dumps(old))
                self.assertIsNone(monitor.detail_cache(item,ttl_seconds=1800))
if __name__=="__main__":unittest.main()
