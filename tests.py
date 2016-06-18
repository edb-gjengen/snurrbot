from __future__ import unicode_literals
import unittest

from utils import parse_title, get_reply_from_url


class ParseHTMLTest(unittest.TestCase):
    def test_parse_title(self):
        title = 'Adventure Time GIF - Find Share on GIPHY'
        partial_html = """<!DOCTYPE html><html itemscope itemtype="http://schema.org/WebPage" >
            <head >
            <title>{}</title>
            <meta charset="utf-8" />
            <meta name="idk" content="test" />""".format(title)
        self.assertEqual(parse_title(html=partial_html), title)

    def test_get_reply_from_url(self):
        url = 'https://www.youtube.com/watch?v=3yR_BAqB7aQ'
        reply = get_reply_from_url(url)
        self.assertEqual(reply, 'URL: 200 text/html [Daydream Labs: Puzzle - YouTube]')

if __name__ == '__main__':
    unittest.main()
