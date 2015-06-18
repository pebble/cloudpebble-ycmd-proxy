#!/usr/bin/env python

__author__ = 'joe'

from gevent import monkey
monkey.patch_all(subprocess=False, thread=False)
import argparse

from ycm_proxy import YCMProxy

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Websocket interface to ycm')
    parser.add_argument('--port', default=9000, type=int, help="Port for websocket to listen on")
    # TODO: eventually require token
    parser.add_argument('--token', required=False, help="Token for the websocket to require as authentication")
    parser.add_argument('--ssl-root', help="Root for SSL certs, containing server-cert.pem and server-key.pem")
    args = parser.parse_args()
    server = YCMProxy(port=args.port, token=args.token, ssl_root=args.ssl_root)
    server.run()
