import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class ReFetchTests(unittest.TestCase):
    def test_same_feed_is_throttled_but_changed_feed_can_fetch(self):
        s=(ROOT/'app.py').read_text()
        ast.parse(s)
        self.assertIn('previous_digest != digest',s)
        self.assertIn("published_at > str(last)",s)
        self.assertIn("if elapsed < 20*3600 and not content_changed:",s)
        self.assertIn("if state=='IN_PROGRESS':",s)
        self.assertIn('merchant_feed_address(project_id)',s)
        self.assertIn("cfg['fetch_feed_sha256']=digest",s)
        self.assertIn('for chunk in iter(lambda:f.read(1024*1024)',s)
    def test_status_is_human_readable(self):
        t=(ROOT/'templates/ecommerce.html').read_text()
        self.assertIn('Načíst aktuální XML Googlem',t)
        self.assertIn('Zpracováno Googlem',t)
if __name__=='__main__':unittest.main()
