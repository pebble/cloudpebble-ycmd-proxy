import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
from flask import Flask, request, jsonify
import uuid
import requests
import tempfile
import os
import os.path
import errno
import subprocess
import base64
import json

import settings

app = Flask(__name__)

mapping = {}

@app.route('/spinup')
def spinup():
    content = request.get_json(force=True)
    root_dir = tempfile.mkdtemp()
    # Dump all the files we should need.
    for path, content in content['files'].iteritems():
        abs_path = os.path.normpath(os.path.join(root_dir, path))
        if not dir_name.startswith(abs_path):
            raise Exception("Failed: escaped root directory.")
        dir_name = os.dir.pathname(abs_path)
        try:
            os.makedirs(dir_name)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(dir_name):
                pass
            else:
                raise
        with open(abs_path, 'w') as f:
            f.write(content)
    with open(os.path.join(root_dir, ".ycm_extra_conf"), "w") as f:
        f.write("""
import os

def FlagsForFile(filename, **kwargs):
    return {
        'flags': [
            '-std=c99',
            '-x',
            'c',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-Wno-unused-parameter',
            '-Wno-error=unused-function',
            '-Wno-error=unused-variable',
            '-I{sdk}/Pebble/include',
            '-I{here}/build',
            '-I{here}',
            '-I{here}/build/src',
            '-I{here}/src',
            '-DRELEASE',
        ],
        'do_cache': True,
    }
""".format(sdk=settings.PEBBLE_SDK, here=root_dir))

    port = _get_port()
    secret = base64.b64encode(os.urandom(64))
    with tempfile.NamedTemporaryFile(delete=False) as f:
        ycmd_settings = json.load(open(settings.YCMD_SETTINGS))
        ycmd_settings['hmac_secret'] = secret
        json.dump(ycmd_settings, f)
        options_file = f.name

    # Spawn a process.
    process = subprocess.Popen([
        settings.YCMD_BINARY,
        '--idle_suicide_seconds', '600',
        '--port', str(port),
        '--options_file', options_file
    ])

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = {
        'port': port,
        'secret': secret,
        'process': process
    }

    # victory!
    return jsonify(success=True, uuid=this_uuid)


def _get_port():
    # Get a temporary socket by binding to an unspecified one, getting the number, and unbinding.
    # (There is a race condition here if you create lots of ports...)
    sock = socket.socket()
    sock.bind(('', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port

if __name__ == '__main__':
    app.run()
