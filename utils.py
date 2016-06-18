from __future__ import unicode_literals

import logging
import lxml.html
from lxml.etree import XMLSyntaxError
import micawber
import re
import requests
import subprocess
from twisted.enterprise import adbapi


logger = logging.getLogger(__name__)


class ReconnectingConnectionPool(adbapi.ConnectionPool):
    """Reconnecting adbapi connection pool for MySQL.

    This class improves on the solution posted at
    http://www.gelens.org/2008/09/12/reinitializing-twisted-connectionpool/
    by checking exceptions by error code and only disconnecting the current
    connection instead of all of them.

    Also see:
    http://twistedmatrix.com/pipermail/twisted-python/2009-July/020007.html

    """
    def _runInteraction(self, interaction, *args, **kw):
        import MySQLdb

        try:
            return adbapi.ConnectionPool._runInteraction(self, interaction, *args, **kw)
        except MySQLdb.OperationalError as e:
            if e[0] not in (2006, 2013):
                raise

            logger.info("RCP: got error %s, retrying operation" % e)
            conn = self.connections.get(self.threadID())
            self.disconnect(conn)
            # try the interaction again
            return adbapi.ConnectionPool._runInteraction(self, interaction, *args, **kw)


def ping_host(host):
    # FIXME rewrite async
    try:
        command = "ping -W 1 -c 1 " + host
        retcode = subprocess.call(command.split(), stdout=subprocess.PIPE)
        if retcode == 0:
            return host + " pinger fint den :P"
        elif retcode == 2:
            return host + " pinger ikke :("
        else:
            return "ping returned: " + str(retcode)
    except OSError as e:
        logger.info("Execution failed:" + str(e))
        return "feil med ping:" + str(e)


def get_title_with_oembed(url):
    providers = micawber.bootstrap_basic()
    try:
        res = providers.request(url)
    except micawber.ProviderException as e:
        logger.info(e)
        return ''

    return '{} - {}'.format(res.get('title'), res.get('provider_name'))


def get_reply_from_url(url):
    user_agent = 'snurrbot v0.1'

    # Try using oembed
    title = get_title_with_oembed(url)

    # Fetch the html
    try:
        req = requests.get(url, headers={'User-Agent': user_agent})
    except requests.Timeout as e:
        logger.info(e)
        return 'URL Timeout'

    content_type = req.headers['content-type']
    if ';' in content_type:
        content_type = content_type.split(';')[0]

    if not title and req.status_code == 200 and content_type == "text/html":
        title = parse_title(req.text)

    title = '' if not title else ' [{}]'.format(title)
    reply = "URL: {} {}{}".format(req.status_code, content_type, title)

    return reply


def parse_title(html):
    title = ''

    try:
        # This might raise an exception if the HTML is _really_ broken
        tree = lxml.html.fromstring(html)
        title_tag = tree.find(".//title")

        if title_tag is not None and title_tag.text is not None:
            title += "%s" % re.sub(r'\s+', ' ', title_tag.text.strip())

    except XMLSyntaxError as e:
        logger.info(str(e))

    return title
