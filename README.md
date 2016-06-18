Friendly IRC bot using Twisted (python 2.7)

# Requirements:
With virtualenv:

    apt install libxml2-dev libxslt1-dev python-dev libmysqlclient-dev
    virtualenv venv
    . venv/bin/activate
    pip install -r requirements.txt

Without venv:

    apt install python-twisted python-mysqldb python-lxml python-openssl python-requests

Usage:

    $ python snurr.py -h
    Usage: python snurr.py [-h] [options] CHANNEL

    Pipes UDP-messages to an IRC-channel.

    Options:
      -h, --help            show this help message and exit
      -c SERVER, --connect=SERVER
                            IRC server (default: irc.oftc.net)
      -p PORT, --port=PORT  IRC server port (default: 6697)
      -s, --ssl             connect with SSL (default: False)
      -l LISTEN_PORT, --listen_port=LISTEN_PORT
                            UDP listen port (default: 55666)

