import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from merge import classify_url, parse_m3u, channel_key, region_scope, Entry


class MergeTests(unittest.TestCase):
    def test_addresses(self):
        cases = [
            ("http://[2409:8087:8:21::18]:6610/live.m3u8", (True, "v6")),
            ("https://1.1.1.1/live.m3u8", (True, "v4")),
            ("https://example.org/live.m3u8", (True, "dns")),
            ("http://127.0.0.1/live.m3u8", (False, "v4")),
            ("http://192.168.1.1/live.m3u8", (False, "v4")),
            ("http://[fe80::1]/live.m3u8", (False, "v6")),
            ("file:///a.m3u8", (False, "")),
            ("http://localhost/live.m3u8", (False, "")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(classify_url(url), expected)

    def test_parse_and_channel(self):
        source = {"name": "test", "scope": "china", "priority": 50}
        playlist = '#EXTM3U\n#EXTINF:-1 tvg-name="CCTV-1" group-title="CCTV",CCTV 1 综合\nhttp://1.1.1.1/cctv1.m3u8\n#EXTINF:-1 tvg-id="CCTV1.cn@HD",CCTV-1\nhttps://example.com/a.m3u8\n'
        entries = parse_m3u(playlist, source)
        self.assertEqual(len(entries), 2)
        self.assertEqual(channel_key(entries[0]), "cctv1")
        self.assertEqual(channel_key(entries[1]), "cctv1")

    def test_world_cn_into_china(self):
        sample = Entry("CCTV1", "https://example.com/1.m3u8", "#EXTINF:-1,CCTV1", "iptv-org", "global", 50, "", "CCTV1.cn@HD")
        self.assertEqual(region_scope(sample), "china")


if __name__ == "__main__":
    unittest.main()
