#!/usr/bin/env python
# encoding: utf-8
import optparse
import requests
import re
import logging
from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, ssl

import settings

from utils import ReconnectingConnectionPool, ping_host, parse_title

logger = logging.getLogger('snurr')


class SnurrBot(irc.IRCClient):
    def __init__(self):
        self.actions = IRCActions(self)

    @property
    def nickname(self):
        return self.factory.nickname

    def __unicode__(self):
        return "SnurrBot:%s" % self.nickname

    def signedOn(self):
        self.join(self.factory.channel)
        logger.info("Signed on as %s." % (self.nickname,))
        # make the client instance known to the factory
        self.factory.bot = self

    def joined(self, channel):
        logger.info("Joined %s." % channel)

    # Called when I have a message from a user to me or a channel.
    def privmsg(self, user, channel, msg):
        # Handle command strings.
        if msg.startswith("!"):
            self.actions.new(msg[1:], user, channel)
        else:
            self.actions.newfull(msg, user, channel)
        logger.info("PRIVMSG: %s: %s" % (user,msg))
    
    def msgReply(self, user, to, msg):
        if len(msg) > 0:
            if to == self.nickname:
                logger.info("Message sent to %s" % user)
                self.msg(user, msg, length=512)
            else:
                self.msgToChannel(msg)

    def msgToChannel(self, msg):
        # Sends a message to the predefined channel
        logger.info("Message sent to %s" % self.factory.channel)

        if len(msg) > 0:
            self.say(self.factory.channel, msg, length=512)

    def rawDataReceived(self, data):
        pass

    def dccSend(self, user, file):
        pass


class SnurrBotFactory(protocol.ClientFactory):
    protocol = SnurrBot

    def __init__(self, channel, nickname='snurr'):
        self.channel = channel
        self.nickname = nickname

    def __unicode__(self):
        return "SnurrBotFactory"

    def clientConnectionLost(self, connector, reason):
        logger.info("Lost connection (%s), reconnecting." % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        logger.info("Could not connect: (%s), retrying." % reason)


class UDPListener(protocol.DatagramProtocol):

    def __init__(self, botfactory):
        self.botfactory = botfactory

    def startProtocol(self):
        logger.info("Listening for messages.")

    def stopProtocol(self):
        logger.info("Listener stopped")

    def datagramReceived(self, data, addr):
        host, port = addr
        # UDP messages (from MediaWiki f.ex) arrive here and are relayed
        # to the ircbot created by the bot factory.
        logger.info("Received %r from %s:%d" % (data, host, port))
        logger.info("Relaying msg to IRCClient in %s" % (self.botfactory,))
        if self.botfactory.bot:
            self.botfactory.bot.msgToChannel(data)


class IRCActions:
    def __init__(self, bot):
        self.bot = bot
        if not settings.DISABLE_TETRIS:
            self.tetris_dbpool = self._get_tetris_dbpool()

    def _get_tetris_dbpool(self):
        # Setup an async db connection
        return ReconnectingConnectionPool(
            settings.DB_API_ADAPTER,
            host=settings.TETRIS_DB_HOST, user=settings.TETRIS_DB_USER,
            passwd=settings.TETRIS_DB_PASSWORD, db=settings.TETRIS_DB_NAME,
            charset="utf8", use_unicode=True,
            cp_reconnect=True)

    def help(self):
        text = ""
        text += "Command: !help\n"
        text += "   This help message\n"

        if not settings.DISABLE_TETRIS:
            text += "Command: !tetrishigh\n"
            text += "   Display tetris highscore\n"
        text += "Command: !ping HOST\n"
        text += "   Ping target host"

        return text

    def new(self, msg, user, channel):
        nick = user.split('!', 1)[0]  # Strip out hostmask
        help_reply = "Need !help " + nick + "?"

        # Process the commands
        parts = msg.split()
        if not parts:
            self.bot.msgReply(nick, channel, help_reply)
            return

        if parts[0] == "ping" and len(parts) == 2:
            self.bot.msgReply(nick, channel, ping_host(parts[1]))
        elif parts[0] == "help" and len(parts) == 1:
            self.bot.msgReply(nick, channel, self.help())
        elif parts[0] == "tetrishigh" and len(parts) == 1 and not settings.DISABLE_TETRIS:
            self.get_tetris_highscore().addCallback(self.msg_tetris_highscore, channel, nick)
        else:
            self.bot.msgReply(nick, channel, help_reply)

    def newfull(self, msg, user, channel):
        nick = user.split('!', 1)[0]  # Strip out hostmask

        # Check if msg contains HTTP(S) URL
        urlmatch = re.search(r"(https?):\/\/([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w\.-]*\/?)(\?[\/\w=&\.-]+)?", msg, re.I)
        if urlmatch is not None:
            self.msg_urlinfo(urlmatch, channel, nick)

    def msg_urlinfo(self, urlmatch, channel, nick):
        reply = "URL: "
        url = urlmatch.group()
        try:
            req = requests.get(url, headers={'User-Agent': 'snurrbot v0.1'}, stream=True)
        except Exception as e:
            logger.info(e)
            self.bot.msgReply(nick, channel, reply + "Timeout")
            return

        content_type = req.headers['content-type']
        if ';' in content_type:
            content_type = content_type.split(';')[0]
        reply += "%d %s " % (req.status_code, content_type)
        if req.status_code == 200 and content_type == "text/html":
            # Read max 20480 bytes
            partial_html = next(req.iter_content(chunk_size=20480))
            reply += parse_title(partial_html)

        self.bot.msgReply(nick, channel, reply)

    def get_tetris_highscore(self):
        sql = "SELECT MAX(score) AS highscore, name FROM highscore GROUP BY name ORDER BY highscore DESC LIMIT 3"
        return self.tetris_dbpool.runQuery(sql)

    def msg_tetris_highscore(self, highscores, channel, nick):
        for highscore in highscores:
            high, name = highscore
            string_highscore = "Highscore: " + str(high) + " by " + name + "."
            self.bot.msgReply(nick, channel, string_highscore.encode("utf-8"))


def _get_parser():
    usage = 'python snurr.py [-h] [options] CHANNEL'
    parser = optparse.OptionParser(description='Pipes UDP-messages to an IRC-channel.',
                                   usage=usage)
    parser.add_option('-c', '--connect', metavar='SERVER',
                      help='IRC server (default: irc.oftc.net)', default='irc.oftc.net')
    parser.add_option('-p', '--port', metavar='PORT', type=int,
                      help='IRC server port (default: 6697)', default=6697)
    parser.add_option('-s', '--ssl', action='store_true',
                      help='connect with SSL (default: False)', default=True)
    parser.add_option('-l', '--listen_port', metavar='LISTEN_PORT', type=int,
                      help='UDP listen port (default: 55666)', default=55666)
    return parser


if __name__ == "__main__":
    LOG_FORMAT = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
    logger.setLevel(logging.DEBUG)
    consoleLogger = logging.StreamHandler()
    consoleLogger.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(consoleLogger)

    argument_parser = _get_parser()
    options, args = argument_parser.parse_args()

    if len(args) != 1:
        print(argument_parser.usage)
        exit(1)
    channel = args[0] if args[0][0] == '#' else '#' + args[0]

    # Start IRC-bot on specified server and port.
    my_snurrbot = SnurrBotFactory(channel)
    if options.ssl:
        reactor.connectSSL(options.connect, options.port, my_snurrbot, ssl.ClientContextFactory())
    else:
        reactor.connectTCP(options.connect, options.port, my_snurrbot)

    # Start the MediaWiki changelog listener.
    mediawiki_listener = UDPListener(my_snurrbot)
    reactor.listenUDP(options.listen_port, mediawiki_listener)

    # Fire up the reactor
    reactor.run()
