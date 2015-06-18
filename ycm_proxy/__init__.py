__author__ = 'joe'

import os.path
import os
import json
from contextlib import contextmanager

from geventwebsocket import WebSocketApplication, WebSocketError
from geventwebsocket.handler import WebSocketHandler
from gevent.pywsgi import WSGIServer
import ssl
import gevent

import settings


class YCMProxy(object):
    def __init__(self, port, token=None, ssl_root=None):
        self.port = port
        self.token = token
        self.authed = False
        self.ssl_root = ssl_root
        self.ws = None
        self.running = False
        self.client_believes_running = False
        self.server = None

        super(YCMProxy, self).__init__()

    def run(self):
        # TODO: start YCM?

        # TODO: check if we still want SSL stuff
        if self.ssl_root is not None:
            ssl_args = {
                'keyfile': '%s/server-key.pem' % self.ssl_root,
                'certfile': '%s/server-cert.pem' % self.ssl_root,
                'ca_certs': '%s/ca-cert.pem' % self.ssl_root,
                'ssl_version': ssl.PROTOCOL_TLSv1,
            }
        else:
            ssl_args = {}
        self.server = WSGIServer(("", self.port), self.handle_ws, handler_class=WebSocketHandler, **ssl_args)
        print 'serving on port %d' % self.port
        self.server.serve_forever()

    def stop(self):
        self.server.stop()
        # TODO: stop YCM?

    #### WebSocket handlers
    def handle_ws(self, environ, start_response):
        if environ['PATH_INFO'] == '/':
            self.ws = environ['wsgi.websocket']
            self.on_open()
            while True:
                try:
                    self.on_message(self.ws.receive())
                except WebSocketError:
                    break
            self.on_close()

    def send_response(self, message):
        message = message.copy()
        self.ws.send(json.dumps(message))

    def send_message(self, message):

        if self.ws is not None:
            print "send: {}".format(message)
            self.ws.send(json.dumps(message))

    def on_open(self):
        print "socket opened"
        self.authed = False

    def on_close(self):
        print "socket closed"

    def on_message(self, message):
        print "message: %s" % message
        # Ignore empty or binary messages
        if message is None or isinstance(message, bytearray):
            return

        message = json.loads(message)
        if not self.authed:
            token = message.get('token', None)
            if token == self.token:
                self.authed = True
            self.send_message({'authed': self.authed})
            return
        self.send_message(message)

        # TODO: interpret message
        # TODO: send responses
