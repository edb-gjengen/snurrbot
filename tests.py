import unittest

import requests
from utils import parse_title


class ParseHTMLTest(unittest.TestCase):
    def test_parse_title(self):
        title = 'Adventure Time GIF - Find Share on GIPHY'
        partial_html = """<!DOCTYPE html><html itemscope itemtype="http://schema.org/WebPage" >
            <head >
            <title>{}</title>
            <meta charset="utf-8" />
            <meta name="idk" content="test" />""".format(title)
        self.assertEqual(parse_title(partial_html=partial_html), '[{}]'.format(title))

    # @unittest.skip()
    def test_parse_title_from_stream(self):
        url = 'http://lol.com'
        req = requests.get(url, headers={'User-Agent': 'snurrbot v0.1'}, stream=True)
        partial_html = req.iter_content(chunk_size=10240)
        self.assertEqual(parse_title(partial_html=partial_html), None)

if __name__ == '__main__':
    unittest.main()
