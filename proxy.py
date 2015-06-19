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


def make_response(result):
    """ jsonify a response if it is a dict, otherwise just return it """
    if isinstance(result, collections.Mapping):
        return jsonify(result)
    else:
        return result


@app.route('/spinup', methods=['POST'])
def spinup():
    content = request.get_json(force=True)
    result = ycm_helpers.spinup(content)
    result['ws_port'] = settings.PORT
    return make_response(result)


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

_ws_commands = {
    'completions': ycm_helpers.get_completions,
    'errors': ycm_helpers.get_errors,
    'goto': ycm_helpers.go_to,
    'create': ycm_helpers.create_file,
    'delete': ycm_helpers.delete_file
    'ping': ycm_helpers.ping
}

def server_ws(process_uuid):
    global _ws_commands
    server_ws = request.environ.get('wsgi.websocket', None)
    if server_ws is None:
        return "websocket endpoint", 400

    alive = [True]
    def do_recv(receive, send, error):
        try:
            while alive[0]:
                raw = receive()
                if raw is None:
                    continue #TODO: check?
                try:
                    data = json.loads(raw)
                except:
                    error('invalid json')
                    return
                if 'command' not in data or data['command'] not in _ws_commands:
                    error('invalid command')
                    return

                cmd = data['command']
                del data['command']
                result = _ws_commands[cmd](process_uuid, data)
                if isinstance(result, collections.Mapping):
                    send(json.dumps(result))
                else:
                    send(result)

        except (websocket.WebSocketException, geventwebsocket.WebSocketError, TypeError):
            alive[0] = False
        except:
            alive[0] = False
            raise

    group = gevent.pool.Group()

    group.spawn(do_recv,
                lambda: server_ws.receive(),
                lambda x: server_ws.send(x),
                lambda x: server_ws.send(json.dumps(dict(success=False, error=x))))
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

    server.serve_forever()
