#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
from flask import Flask, request, jsonify
from flask.ext.cors import CORS, cross_origin
import atexit
import gevent
import collections
import ycm_helpers
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
import geventwebsocket
import ssl
import websocket
import settings
import json
import gevent.pool

import traceback
import werkzeug.serving

app = Flask(__name__)

cors = CORS(app, headers=["X-Requested-With", "X-CSRFToken", "Content-Type"], resources="/ycm/*")
mapping = {}


@app.route('/spinup', methods=['POST'])
def spinup():
    content = request.get_json(force=True)
    result = ycm_helpers.spinup(content)
    result['ws_port'] = settings.PORT
    return jsonify(result)


#### Websocket handlers ####
# TODO: maybe do this without a global?
_ws_commands = {
    'completions': ycm_helpers.get_completions,
    'errors': ycm_helpers.get_errors,
    'goto': ycm_helpers.go_to,
    'create': ycm_helpers.create_file,
    'delete': ycm_helpers.delete_file,
    'ping': ycm_helpers.ping
}

def server_ws(process_uuid):
    global _ws_commands

    # Get the WebSocket from the request context
    server_ws = request.environ.get('wsgi.websocket', None)
    if server_ws is None:
        return "websocket endpoint", 400

    alive = [True]
    def do_recv(receive, send, error):
        try:
            while alive[0]:
                # First try to get some valid JSON data
                # with a command and message id
                raw = receive()
                id = -1
                if raw is None:
                    continue

                try:
                    packet = json.loads(raw)
                    id = packet['_ws_message_id']
                    command = packet['command']
                    data= packet['data']
                except:
                    error(id, 'invalid packet')
                    continue

                if command not in _ws_commands:
                    error(id, 'unknown command')
                    continue

                # Run the specified command with the correct uuid and data
                try:
                    print "Running command: %s" % command
                    result = _ws_commands[command](process_uuid, data)
                    print ">> Done running"
                except Exception as e:
                    print "Error running command"
                    print e
                    print traceback.format_exc()
                    error(id, e.message)
                    continue

                send(id, result)
        except (websocket.WebSocketException, geventwebsocket.WebSocketError, TypeError) as e:
            # WebSocket closed
            alive[0] = False
        except Exception as e:
            alive[0] = False
            raise

    group = gevent.pool.Group()

    # Helper functions for sending responses, includes repeating the ID
    def send_response(id, response):
        if not isinstance(response, collections.Mapping):
            response = dict(message=response)
        response['_ws_message_id'] = id
        return server_ws.send(json.dumps(response))


    def send_error(id, message):
        response = (dict(success=False, error=message))
        send_response(id, response)

    # Spawn a greenlet to deal with the websocket connection
    group.spawn(do_recv,lambda: server_ws.receive(), send_response, send_error)

    def end_server():
        alive[0] = False
        group.kill()

    atexit.register(end_server)
    group.join()
    return ''

@app.route('/ycm/<process_uuid>/ws')
def ycm_ws(process_uuid):
    return server_ws(process_uuid)

@atexit.register
def kill_completers():
    ycm_helpers.kill_completers()


g = gevent.spawn(ycm_helpers.monitor_processes, mapping)
atexit.register(lambda: g.kill())

# Using upstart to stop the proxy doesn't work unless we run the server with werkzeug's reloader.
# If there is a better way of doing this, I'm not sure what it is.
@werkzeug.serving.run_with_reloader
def run_server():
    app.debug = settings.DEBUG

    ssl_args = {}
    if settings.SSL_ROOT is not None:
        ssl_args = {
            'keyfile': '%s/server-key.pem' % settings.SSL_ROOT,
            'certfile': '%s/server-cert.pem' % settings.SSL_ROOT,
            'ca_certs': '%s/ca-cert.pem' % settings.SSL_ROOT,
            'ssl_version': ssl.PROTOCOL_TLSv1,
        }

    server = pywsgi.WSGIServer(('', settings.PORT), app, handler_class=WebSocketHandler, **ssl_args)
    server.start()
    server.serve_forever()

if __name__ == '__main__':
    run_server()
