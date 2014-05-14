#!/usr/bin/env python
# encoding: utf-8
import optparse
import subprocess 
import time
import MySQLdb
import urllib2, lxml.html, re
from datetime import datetime


from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, ssl
from twisted.enterprise import adbapi
from twisted.python import log

import settings

if not settings.DISABLE_LOG:
    import MySQLdb

class SnurrBot(irc.IRCClient):
    def __init__(self):
        self.actions = IRCActions(self)

    def _get_nickname(self):
        return self.factory.nickname

    nickname = property(_get_nickname)

    def __unicode__(self):
        return "SnurrBot:%s" % (nickname,)

    def signedOn(self):
        self.join(self.factory.channel)
        _log("Signed on as %s." % (self.nickname,))
        # make the client instance known to the factory
        self.factory.bot = self

    def joined(self, channel):
        _log("Joined %s." % (channel,))

    # Called when I have a message from a user to me or a channel.
    def privmsg(self, user, channel, msg):
        # Handle command strings.
        if msg.startswith("!"):
            self.actions.new(msg[1:], user, channel)
        else:
            self.actions.newfull(msg, user, channel)
        _log("PRIVMSG: %s: %s" % (user,msg,))
    
    def msgReply(self, user, to, msg):
        if len(msg) > 0:
            if to == self.nickname:
                _log("Message sent to %s" % (user,))
                self.msg(user, msg, length=512)
            else:
                self.msgToChannel(msg)

    def msgToChannel(self, msg):
        # Sends a message to the predefined channel
        _log("Message sent to %s" % (self.factory.channel,))
        if len(msg) > 0:
            self.say(self.factory.channel, msg, length=512)


class SnurrBotFactory(protocol.ClientFactory):
    protocol = SnurrBot

    def __init__(self, channel, nickname='snurr'):
        self.channel = channel
        self.nickname = nickname

    def __unicode__(self):
        return "SnurrBotFactory"

    def clientConnectionLost(self, connector, reason):
        _log("Lost connection (%s), reconnecting." % (reason,))
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        _log("Could not connect: (%s), retrying." % (reason,))

class UDPListener(protocol.DatagramProtocol):

    def __init__(self, botfactory):
        self.botfactory = botfactory

    def startProtocol(self):
        _log("Listening for messages.")

    def stopProtocol(self):
        _log("Listener stopped")

    def datagramReceived(self, data, (host, port)):
        # UDP messages (from MediaWiki f.ex) arrive here and are relayed
        # to the ircbot created by the bot factory.
        _log("Received %r from %s:%d" % (data, host, port))
        _log("Relaying msg to IRCClient in %s" % (self.botfactory,))
        if self.botfactory.bot:
            self.botfactory.bot.msgToChannel(data)

class IRCActions():
    def __init__(self, bot):
        self.bot = bot
        if not settings.DISABLE_LOG:
            self.dbpool = self._get_dbpool()
            self.tetris_dbpool = self._get_tetris_dbpool()

    def _get_dbpool(self):
        # Setup an async db connection
        return ReconnectingConnectionPool(settings.DB_API_ADAPTER,
            host=settings.DB_HOST, user=settings.DB_USER,
            passwd=settings.DB_PASSWORD, db=settings.DB_NAME,
            charset="utf8", use_unicode=True,
            cp_reconnect=True)

    def _get_tetris_dbpool(self):
        # Setup an async db connection
        return ReconnectingConnectionPool(settings.DB_API_ADAPTER,
            host=settings.TETRIS_DB_HOST, user=settings.TETRIS_DB_USER,
            passwd=settings.TETRIS_DB_PASSWORD, db=settings.TETRIS_DB_NAME,
            charset="utf8", use_unicode=True,
            cp_reconnect=True)

    def ping(self, host):
        # TODO rewrite async
        try:
            command = "ping -W 1 -c 1 " + host
            retcode = subprocess.call(command.split(),stdout=subprocess.PIPE)
            if retcode == 0:
                return host + " pinger fint den :P"
            elif retcode == 2:
                return host + " pinger ikke :("
            else:
               return "ping returned: " + str(retcode)
        except OSError, e:
            _log("Execution failed:" + str(e))
            return "feil med ping:" + str(e)

    def help(self):
        text = ""
        text += "Command: !help\n"
        text += "   This help message\n"
        if not settings.DISABLE_LOG:
            text += "Command: !log DESCRIPTION\n"
            text += "   Add new entry in log\n"
            text += "Command: !lastlog\n"
            text += "   Last 3 log entries\n"
        text += "Command: !ping HOST\n"
        text += "   Ping target host"
        return text

    def new(self, msg, user, channel):
        nick = user.split('!', 1)[0] # Strip out hostmask

        # Process the commands
        parts = msg.split()
        if not parts:
            self.bot.msgReply(nick, channel, "Need !help " + nick + "?")
            return

        if parts[0] == "ping" and len(parts) == 2:
            self.bot.msgReply(nick, channel, self.ping(parts[1]))
        elif parts[0] == "help" and len(parts) == 1:
            self.bot.msgReply(nick, channel, self.help())
        elif parts[0] == "log" and len(parts) >= 2 and not settings.DISABLE_LOG:
            # set_log_entry should create a deferred and
            # the callback should fire when the db returns.
            self.set_log_entry(nick, parts[1:]).addCallback(self.msg_log_entry, channel, nick)
        elif parts[0] == "lastlog" and len(parts) == 1 and not settings.DISABLE_LOG:
            # ...same as above
            self.get_lastlog().addCallback(self.msg_lastlog, channel, nick)
        elif parts[0] == "tetrishigh" and len(parts) == 1 and not settings.DISABLE_TETRIS:
            self.get_tetris_highscore().addCallback(self.msg_tetris_highscore, channel, nick)

        else:
            self.bot.msgReply(nick, channel, "Need !help " + nick + "?")

    def newfull(self, msg, user, channel):
        nick = user.split('!', 1)[0] # Strip out hostmask

        # Check if msg contains HTTP(S) URL
        urlmatch = re.search(r"(https?):\/\/([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w\.-]*\/?)(\?[\/\w=&\.-]+)?", msg, re.I)
        if urlmatch is not None:
            self.msg_urlinfo(urlmatch, channel, nick)

    def msg_urlinfo(self, urlmatch, channel, nick):
        reply = "URL: "
        url = urlmatch.group()
        try:
            i = urllib2.urlopen(url, timeout=3, headers={'User-Agent': 'snurrbot v0.1'})
        except Exception as e:
            _log(e)
            self.bot.msgReply(nick, channel, reply + "Timeout")
            return
        statuscode = i.getcode()
        contenttype = i.info().gettype()
        reply += "%d %s " % (statuscode, contenttype)
        if statuscode == 200 and contenttype == "text/html":
            # Read max 10000 bytes
            partialhtml = i.read(10000)
            try:
                # This might raise an exception if the HTML is _really_ broken
                tree = lxml.html.fromstring(partialhtml)
                title = tree.find(".//title")
                if title is not None and title.text is not None:
                    reply += "[%s]" % re.sub(r'\s+', ' ', title.text.strip())
                # DEBUG
                if title is None:
                    reply += "<title is none>"
                elif title.text is None:
                    reply += "<title.text is none>"
                # END
            except:
                reply += "<exception>"
                pass
        self.bot.msgReply(nick, channel, reply)

    def set_log_entry(self, nick, entry):
        entry = " ".join(entry)
        sql = "INSERT INTO main_entry (user, text, created) VALUES (%s, %s, NOW())"
        params = (nick, entry)
        return self.dbpool.runOperation(sql, params)

    def msg_log_entry(self, result, channel, nick):
        self.bot.msgReply(nick, channel, "Yes sir! Driftslogg oppdatert.")

    def get_lastlog(self):
        sql = "SELECT * FROM main_entry ORDER BY created DESC LIMIT 3"
        return self.dbpool.runQuery(sql)

    def msg_lastlog(self, log_entries, channel, nick):
        for i,entry in enumerate(log_entries, start=1):
            string_entry = str(i) + ": " + entry[2] + " (" + entry[1] + ", " + str(entry[3]) + ")"
            self.bot.msgReply(nick, channel, string_entry.encode("utf-8"))

    def get_tetris_highscore(self):
        sql = "SELECT MAX(score) AS highscore, name FROM highscore GROUP BY name ORDER BY highscore DESC LIMIT 3"
        return self.tetris_dbpool.runQuery(sql)

    def msg_tetris_highscore(self, highscores, channel, nick):
        for highscore in highscores:
            high,name = highscore
            string_highscore = "Highscore: " + str(high) + " by " + name + "."
            self.bot.msgReply(nick, channel, string_highscore.encode("utf-8"))

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
        try:
            return adbapi.ConnectionPool._runInteraction(self, interaction, *args, **kw)
        except MySQLdb.OperationalError, e:
            if e[0] not in (2006, 2013):
                raise
            log.msg("RCP: got error %s, retrying operation" %(e))
            conn = self.connections.get(self.threadID())
            self.disconnect(conn)
            # try the interaction again
            return adbapi.ConnectionPool._runInteraction(self, interaction, *args, **kw)

def _log(message):
    now = datetime.now().strftime("%b %d %H:%M:%S")
    print "{0} {1}".format(now, message)

def _setup_and_parse_options():
    parser = optparse.OptionParser(description='Pipes UDP-messages to an IRC-channel.',
                                   usage=_usage())
    parser.add_option('-c', '--connect', metavar='SERVER',
                      help='IRC server (default: irc.ifi.uio.no)', default='irc.oftc.net')
    parser.add_option('-p', '--port', metavar='PORT', type=int,
                      help='IRC server port (default: 6697)', default=6697)
    parser.add_option('-s','--ssl', action='store_true',
                      help='connect with SSL (default: False)', default=True)
    parser.add_option('-l', '--listen_port', metavar='LISTEN_PORT', type=int,
                      help='UDP listen port (default: 55666)', default=55666)
    return parser.parse_args()

def _usage():
    return 'Usage: python snurr.py [-h] [options] CHANNEL'

if __name__ == "__main__":
    options, args = _setup_and_parse_options()

    if len(args) != 1:
        print _usage()
        exit()
    snurr = SnurrBotFactory('#' + args[0])
    listener = UDPListener(snurr)

    # Start the listener.
    reactor.listenUDP(options.listen_port, listener)

    # Start IRC-bot on specified server and port.
    if options.ssl:
        reactor.connectSSL(options.connect, options.port, snurr, ssl.ClientContextFactory())
    else:
        reactor.connectTCP(options.connect, options.port, snurr)
    reactor.run()
