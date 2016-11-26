#!/usr/bin/env python
# encoding: utf-8
import optparse
import re
import logging
from time import sleep

from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, ssl

import settings

from utils import ReconnectingConnectionPool, ping_host, get_reply_from_url

logger = logging.getLogger('snurr')


class SnurrBot(irc.IRCClient):
    nickname = 'snurr'

    def __init__(self):
        self.actions = IRCActions(self)

    def signedOn(self):
        self.join(self.factory.channel)
        logger.info("Signed on as %s." % (self.nickname,))

        # Make the client instance known to the factory
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
        logger.info("PRIVMSG: %s: %s", user, msg)

    def msg_reply(self, user, to, msg):
        if len(msg) > 0:
            if to == self.nickname:
                logger.info("Message sent to %s", user)
                self.msg(user, msg, length=512)
            else:
                self.msg_to_channel(msg)

    def msg_to_channel(self, msg):
        # Sends a message to the predefined channel
        logger.info("Message sent to %s", self.factory.channel)

        if len(msg) > 0:
            self.say(self.factory.channel, msg, length=512)

    def rawDataReceived(self, data):
        pass

    def dccSend(self, user, file):
        pass


class SnurrBotFactory(protocol.ClientFactory):
    protocol = SnurrBot

    TIMEOUT_INITIAL = 2

    def __init__(self, channel):
        self.channel = channel
        self.timeout = self.TIMEOUT_INITIAL

    def buildProtocol(self, addr):
        self.timeout = self.TIMEOUT_INITIAL  # reset
        return super().buildProtocol(addr)

    def clientConnectionLost(self, connector, reason):
        self.timeout *= self.timeout
        logger.info("Lost connection (%s), reconnecting.", reason)
        sleep(self.timeout)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        self.timeout *= self.timeout
        logger.info("Could not connect: (%s), retrying in %s seconds.", reason)
        sleep(self.timeout)
        connector.connect()


class UDPListener(protocol.DatagramProtocol):

    def __init__(self, botfactory):
        self.bot_factory = botfactory

    def startProtocol(self):
        logger.info("Listening for messages.")

    def stopProtocol(self):
        logger.info("Listener stopped")

    def datagramReceived(self, data, addr):
        host, port = addr
        # UDP messages (from MediaWiki f.ex) arrive here and are relayed
        # to the ircbot created by the bot factory.
        logger.info("Received %r from %s:%d", data, host, port)
        logger.info("Relaying msg to IRCClient in %s", self.bot_factory)
        if self.bot_factory.bot:
            self.bot_factory.bot.msg_to_channel(data)


class IRCActions:
    def __init__(self, bot):
        self.bot = bot
        if not settings.DISABLE_TETRIS:
            self.tetris_dbpool = self._get_tetris_dbpool()

    def _get_tetris_dbpool(self):
        # Setup an async db connection
        return ReconnectingConnectionPool(
            settings.DB_API_ADAPTER,
            host=settings.TETRIS_DB_HOST,
            user=settings.TETRIS_DB_USER,
            passwd=settings.TETRIS_DB_PASSWORD,
            db=settings.TETRIS_DB_NAME,
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
            self.bot.msg_reply(nick, channel, help_reply)
            return

        if parts[0] == "ping" and len(parts) == 2:
            self.bot.msg_reply(nick, channel, ping_host(parts[1]))
        elif parts[0] == "help" and len(parts) == 1:
            self.bot.msg_reply(nick, channel, self.help())
        elif parts[0] == "tetrishigh" and len(parts) == 1 and not settings.DISABLE_TETRIS:
            self.get_tetris_highscore().addCallback(self.msg_tetris_highscore, channel, nick)
        else:
            self.bot.msg_reply(nick, channel, help_reply)

    def newfull(self, msg, user, channel):
        nick = user.split('!', 1)[0]  # Strip out hostmask

        # Check if msg contains HTTP(S) URL
        urlmatch = re.search(r"(https?):\/\/([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w\.-]*\/?)(\?[\/\w=&\.-]+)?", msg, re.I)
        if urlmatch is not None:
            self.msg_urlinfo(urlmatch.group(), channel, nick)

    def msg_urlinfo(self, url, channel, nick):
        reply = get_reply_from_url(url)
        self.bot.msg_reply(nick, channel, reply)

    def get_tetris_highscore(self):
        sql = "SELECT MAX(score) AS highscore, name FROM highscore GROUP BY name ORDER BY highscore DESC LIMIT 3"
        return self.tetris_dbpool.runQuery(sql)

    def msg_tetris_highscore(self, highscores, channel, nick):
        for highscore in highscores:
            high, name = highscore
            string_highscore = "Highscore: " + str(high) + " by " + name + "."
            self.bot.msg_reply(nick, channel, string_highscore)


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


def setup_logging():
    log_format = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
    logger.setLevel(logging.DEBUG)
    console_logger = logging.StreamHandler()
    console_logger.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_logger)


if __name__ == "__main__":
    setup_logging()

    argument_parser = _get_parser()
    options, args = argument_parser.parse_args()

    if len(args) != 1:
        print(argument_parser.usage)
        exit(1)

    _channel = args[0] if args[0][0] == '#' else '#' + args[0]

    # Start IRC-bot on specified server and port.
    my_snurrbot = SnurrBotFactory(_channel)
    if options.ssl:
        reactor.connectSSL(options.connect, options.port, my_snurrbot, ssl.ClientContextFactory())
    else:
        reactor.connectTCP(options.connect, options.port, my_snurrbot)

    # Start the MediaWiki changelog listener.
    mediawiki_listener = UDPListener(my_snurrbot)
    reactor.listenUDP(options.listen_port, mediawiki_listener)

    # Fire up the reactor
    reactor.run()
