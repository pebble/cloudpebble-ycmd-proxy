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

app = Flask(__name__)

cors = CORS(app, headers=["X-Requested-With", "X-CSRFToken", "Content-Type"], resources="/ycm/*")
mapping = {}


@app.route('/spinup', methods=['POST'])
def spinup():
    content = request.get_json(force=True)
    result = ycm_helpers.spinup(content)
    result['ws_port'] = settings.PORT
    return make_response(result)

#### These functions are currently kept for now, in order to continue to support HTTP ####
# TODO: eventually delete these
def make_response(result):
    """ jsonify a response if it is a dict, otherwise just return it """
    if isinstance(result, collections.Mapping):
        return jsonify(result)
    else:
        return result

@app.route('/ycm/<process_uuid>/completions', methods=['POST'])
def get_completions(process_uuid):
    data = request.get_json(force=True)
    result = ycm_helpers.get_completions(process_uuid, data)
    return make_response(result)


@app.route('/ycm/<process_uuid>/errors', methods=['POST'])
def get_errors(process_uuid):
    data = request.get_json(force=True)
    result = ycm_helpers.get_errors(process_uuid, data)
    return make_response(result)


@app.route('/ycm/<process_uuid>/goto', methods=['POST'])
def go_to(process_uuid):
    data = request.get_json(force=True)
    result = ycm_helpers.go_to(process_uuid, data)
    return make_response(result)


@app.route('/ycm/<process_uuid>/create', methods=['POST'])
def create_file(process_uuid):
    data = request.get_json(force=True)
    result = ycm_helpers.create_file(process_uuid, data)
    return make_response(result)


@app.route('/ycm/<process_uuid>/delete', methods=['POST'])
def delete_file(process_uuid):
    data = request.get_json(force=True)
    result = ycm_helpers.create_file(process_uuid, data)
    return make_response(result)


@app.route('/ycm/<process_uuid>/ping', methods=['POST'])
def ping(process_uuid):
    result = ycm_helpers.ping(process_uuid)
    return make_response(result)

#### END HTTP functions ####

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

    # Get the websocket from the request context
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
                if raw is None:
                    continue #TODO: check?
                try:
                    data = json.loads(raw)
                except:
                    error(-1, 'invalid json')
                    continue
                id = data.get('_ws_message_id', -1)
                if 'command' not in data or data['command'] not in _ws_commands:
                    error(id, 'invalid command')
                    continue

                # Run the specified command with the correct uuid and data
                cmd = data['command']
                del data['command']
                try:
                    result = _ws_commands[cmd](process_uuid, data)
                except Exception as e:
                    # TODO: Think carefully about error handling and logging
                    print e
                    error(id, e.message)
                    continue

                send(id, result)
        except (websocket.WebSocketException, geventwebsocket.WebSocketError, TypeError) as e:
            # TODO: see above
            print e
            alive[0] = False
        except Exception as e:
            print e
            alive[0] = False
            raise

    group = gevent.pool.Group()

    # Helper functions for sending responses, includes repeating the ID
    def send_response(id, response):
        response['_ws_message_id'] = id
        if isinstance(response, collections.Mapping):
            server_ws.send(json.dumps(response))
        else:
            # TODO: check which things were sending 'ok'.
            # Make sure nothing relied on them just saying 'ok'
            server_ws.send(json.dumps(dict(message=response)))
    def send_error(id, message):
        response = (dict(success=False, error=message))
        send_response(id, response)

    # Spawn a greenlet to deal with the websocket connection
    group.spawn(do_recv,lambda: server_ws.receive(), send_response, send_error)
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

if __name__ == '__main__':
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
    # TODO: Figure out why the service can't be restart properly if there's an exception in the websocket...
    server.serve_forever()

