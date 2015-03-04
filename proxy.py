#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
from flask import Flask, request, jsonify
from flask.ext.cors import CORS, cross_origin
import uuid
import tempfile
import os
import os.path
import errno
import atexit
import gevent
import collections

import settings
from ycm import YCM
from filesync import FileSync

app = Flask(__name__)

cors = CORS(app, headers=["X-Requested-With", "X-CSRFToken", "Content-Type"], resources="/ycm/*")

mapping = {}


YCMHolder = collections.namedtuple('YCMHolder', ('filesync', 'ycms'))
CodeCompletion = collections.namedtuple('CodeCompletion', ('kind', 'insertion_text', 'extra_menu_info', 'detailed_info'))


@app.route('/spinup', methods=['POST'])
def spinup():
    content = request.get_json(force=True)
    root_dir = tempfile.mkdtemp()
    platforms = set(content.get('platforms', ['aplite']))
    print root_dir
    # Dump all the files we should need.
    for path, content in content['files'].iteritems():
        abs_path = os.path.normpath(os.path.join(root_dir, path))
        if not abs_path.startswith(root_dir):
            raise Exception("Failed: escaped root directory.")
        dir_name = os.path.dirname(abs_path)
        try:
            os.makedirs(dir_name)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(dir_name):
                pass
            else:
                raise
        with open(abs_path, 'w') as f:
            f.write(content)

    filesync = FileSync(root_dir)
    ycms = YCMHolder(filesync=filesync, ycms={})

    settings_path = os.path.join(root_dir, ".ycm_extra_conf.py")
    with open(settings_path, "w") as f:
        with open(os.path.dirname(__file__) + '/ycm_extra_conf.py') as template:
            f.write(template.read().format(sdk=settings.PEBBLE_SDK3, here=root_dir, stdlib=settings.STDLIB_INCLUDE_PATH))

    if 'aplite' in platforms:
        ycm = YCM(filesync, 'aplite')
        ycm.wait()
        ycm.apply_settings(settings_path)
        ycms.ycms['aplite'] = ycm

    if 'basalt' in platforms:
        ycm = YCM(filesync, 'basalt')
        ycm.wait()
        ycm.apply_settings(settings_path)
        ycms.ycms['basalt'] = ycm

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = ycms
    print mapping
    # victory!
    return jsonify(success=True, uuid=this_uuid)


@app.route('/ycm/<process_uuid>/completions', methods=['POST'])
def get_completions(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycms = mapping[process_uuid]
    data = request.get_json(force=True)
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    completions = collections.OrderedDict()
    print "get_completions:"
    completion_start_column = None
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        print platform, ycm
        ycm.parse(data['file'], data['line'], data['ch'])  # TODO: Should we do this here?
        platform_completions = ycm.get_completions(data['file'], data['line'], data['ch'])
        completion_start_column = platform_completions['completion_start_column']
        print platform_completions
        for completion in platform_completions['completions']:
            if completion['insertion_text'] in completions:
                continue
            completions[completion['insertion_text']] = completion
    print completions
    return jsonify(
        completions=completions.values(),
        start_column=completion_start_column,
    )


@app.route('/ycm/<process_uuid>/errors', methods=['POST'])
def get_errors(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycms = mapping[process_uuid]
    data = request.get_json(force=True)
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    errors = {}
    print "get_errors:"
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        print platform, ycm
        result = ycm.parse(data['file'], data['line'], data['ch'])
        print result
        if result is None:
            continue
        for error in result:
            error_key = (error['kind'], error['location']['line_num'], error['text'])
            if error_key in errors:
                errors[error_key]['platforms'].append(platform)
            else:
                error['platforms'] = [platform]
                errors[error_key] = error

    return jsonify(
        errors=errors.values()
    )


@app.route('/ycm/<process_uuid>/goto', methods=['POST'])
def go_to(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycms = mapping[process_uuid]
    data = request.get_json(force=True)
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        ycm.parse(data['file'], data['line'], data['ch'])
        result = ycm.go_to(data['file'], data['line'], data['ch'])
        if result is not None:
            return jsonify(location=result)
    return jsonify(location=None)


@app.route('/ycm/<process_uuid>/create', methods=['POST'])
def create_file(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycms = mapping[process_uuid]
    data = request.get_json(force=True)
    ycms.filesync.create_file(data['filename'], data['content'])
    return 'ok'


@app.route('/ycm/<process_uuid>/delete', methods=['POST'])
def delete_file(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    ycms = mapping[process_uuid]
    data = request.get_json(force=True)
    ycms.filesync.delete_file(data['filename'])
    return 'ok'


@app.route('/ycm/<process_uuid>/ping', methods=['POST'])
def ping(process_uuid):
    if process_uuid not in mapping:
        return "Not found", 404
    for ycm in mapping[process_uuid].ycms.itervalues():
        if not ycm.ping():
            return 'failed', 504

    return 'ok'


@atexit.register
def kill_completers():
    global mapping
    for ycms in mapping.itervalues():
        for ycm in ycms.ycms.itervalues():
            ycm.close()
    mapping = {}


def monitor_processes(mapping):
    while True:
        print "process sweep running"
        gevent.sleep(60)
        to_kill = set()
        for uuid, ycms in mapping.iteritems():
            for ycm in ycms.ycms.itervalues():
                if not ycm.alive:
                    ycm.close()
                    to_kill.add(uuid)
        for uuid in to_kill:
            del mapping[uuid]
        print "process sweep collected %d instances" % len(to_kill)


g = gevent.spawn(monitor_processes, mapping)
atexit.register(lambda: g.kill())

if __name__ == '__main__':
    app.debug = settings.DEBUG
    app.run(settings.HOST, settings.PORT)
