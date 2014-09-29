import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
import socket
import base64
import tempfile
import json
import subprocess
import os.path
import requests
import hmac
import hashlib
import gevent
import requests.exceptions
import shutil
import time

import settings

__author__ = 'katharine'


class YCM(object):
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self._port = self._get_port()
        self._secret = os.urandom(16)
        self._spawn()
        self._update_ping()
        self.wait()

    def _spawn(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            ycmd_settings = json.load(open(settings.YCMD_SETTINGS))
            ycmd_settings['hmac_secret'] = base64.b64encode(self._secret)
            ycmd_settings['confirm_extra_conf'] = 0
            json.dump(ycmd_settings, f)
            options_file = f.name
        self._process = subprocess.Popen([
            settings.YCMD_BINARY,
            '--idle_suicide_seconds', '700',
            '--port', str(self._port),
            '--options_file', options_file
        ], cwd=self.root_dir)

    def apply_patches(self, patch_sequence):
        self._update_ping()
        # TODO: optimisations, if we care.
        # We can keep the files in memory
        # A sequence of patches probably all apply to the same file. We can optimise around this.
        # But does it matter?
        for patch in patch_sequence:
            abs_path = self._abs_path(patch['filename'])
            with open(abs_path) as f:
                lines = f.readlines()
                start = patch['start']
                end = patch['end']

                # Including everything up to the start line
                content = lines[:start['line']-1]
                # Merge the start line, replacement, and end line into a single line
                content.append(lines[start['line']-1][:start['ch']] + patch['text'] + lines[end['line']-1][end['ch']:])
                # Add the lines from the end through to the end.
                content.extend(lines[end['line']:])

            # Writeback.
            with open(abs_path, 'w') as f:
                f.writelines(content)

    def apply_settings(self, file):
        self._request('load_extra_conf_file', {'filepath': file})

    def parse(self, filepath, line, ch):
        self._update_ping()
        path = self._abs_path(filepath)
        with open(path) as f:
            request = {
                'event_name': 'FileReadyToParse',
                'filepath': path,
                'line_num': line,
                'column_num': ch,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c']
                    }
                }
            }
        result = self._request("event_notification", request)
        print result.json()
        return result.json()

    def get_completions(self, filepath, line, ch):
        self._update_ping()
        path = self._abs_path(filepath)
        with open(path) as f:
            request = {
                'column_num': ch,
                'line_num': line,
                'filepath': path,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c']
                    }
                },
                'force_semantic': True,
            }

        result = self._request("completions", request)
        if result.status_code == 200:
            return result.json()
        else:
            raise Exception("Something broke.")

    def wait(self):
        while True:
            try:
                gevent.sleep(0.1)
                headers = {
                    'X-Ycm-Hmac': self._hmac(''),
                }
                result = requests.get("http://localhost:%d/ready" % self._port, headers=headers)
                print result
            except requests.exceptions.ConnectionError:
                pass
            else:
                if 200 <= result.status_code < 300 and result.json():
                    return True

    def _hmac(self, body):
        return base64.b64encode(hmac.new(self._secret, body, hashlib.sha256).hexdigest())

    def _abs_path(self, path):
        abs_path = os.path.normpath(os.path.join(self.root_dir, path))
        # if not abs_path.startswith(self.root_dir):
        #     raise Exception("Bad path")
        return abs_path

    def _request(self, endpoint, data):
        body = json.dumps(data)
        headers = {
            'X-Ycm-Hmac': self._hmac(body),
            'Content-Type': 'application/json',
        }
        return requests.post("http://localhost:%d/%s" % (self._port, endpoint), body, headers=headers)

    def _update_ping(self):
        self._last_ping = time.time()

    @property
    def alive(self):
        return time.time() < self._last_ping + 600

    def close(self):
        print "terminating server"
        self._process.terminate()
        shutil.rmtree(self.root_dir)

    @staticmethod
    def _get_port():
        # Get a temporary socket by binding to an unspecified one, getting the number, and unbinding.
        # (There is a race condition here if you create lots of ports...)
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port