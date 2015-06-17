#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
from flask import Flask, request, jsonify
from flask.ext.cors import CORS, cross_origin
import atexit
import gevent
import collections
import ycm_helpers

import settings

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


@atexit.register
def kill_completers():
    ycm_helpers.kill_completers()


g = gevent.spawn(ycm_helpers.monitor_processes, mapping)
atexit.register(lambda: g.kill())

if __name__ == '__main__':
    app.debug = settings.DEBUG
    app.run(settings.HOST, settings.PORT)
