import logging
import re
import subprocess

import lxml.html
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


def parse_title(partial_html):
    reply = ''
    try:
        # This might raise an exception if the HTML is _really_ broken
        tree = lxml.html.fromstring(partial_html)
        title = tree.find(".//title")
        if title is not None and title.text is not None:
            reply += "[%s]" % re.sub(r'\s+', ' ', title.text.strip())
        # DEBUG
        if title is None:
            reply += "<title is none>"
        elif title.text is None:
            reply += "<title.text is none>"
        # END
    except Exception as e:
        reply += "<exception>"
        logger.error(e.message)

    return reply
