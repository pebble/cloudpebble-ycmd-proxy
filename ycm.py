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
import os

from symbol_blacklist import is_valid_symbol
import settings

__author__ = 'katharine'


class YCM(object):
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self._port = self._get_port()
        self._secret = os.urandom(16)
        self._spawn()
        self._update_ping()
        self._patch_ids = {}
        self._pending_patches = {}
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

    def apply_patches(self, patch_sequence, was_pending=False):
        self._update_ping()
        # TODO: optimisations, if we care.
        # We can keep the files in memory
        # A sequence of patches probably all apply to the same file. We can optimise around this.
        # But does it matter?


        for patch in patch_sequence:
            filename = patch['filename']
            if filename not in self._patch_ids:
                self._patch_ids[filename] = 0
                self._pending_patches[filename] = []

            self._pending_patches[filename].append(patch)

        for filename, pending in self._pending_patches.iteritems():
            pending = sorted(pending, key=lambda x: x['sequence'])

            while len(pending) > 0 and pending[0]['sequence'] == self._patch_ids[filename]:
                patch = pending.pop(0)
                self._patch_ids[filename] += 1
                abs_path = self._abs_path(patch['filename'])

                with open(abs_path) as f:
                    lines = f.readlines()
                    start = patch['start']
                    end = patch['end']

                    # Including everything up to the start line
                    content = lines[:start['line']]
                    # Merge the start line, replacement, and end line into a single line
                    merged_line = ''
                    if len(lines) > start['line']:
                        merged_line += lines[start['line']][:start['ch']]
                    merged_line += "\n".join(patch['text'])
                    if len(lines) > end['line']:
                        merged_line += lines[end['line']][end['ch']:]
                    content.append(merged_line)
                    # Add the lines from the end through to the end.
                    if len(lines) > end['line']+1:
                        content.extend(lines[end['line']+1:])

                # Writeback.
                with open(abs_path, 'w') as f:
                    f.writelines(content)

    def apply_settings(self, file):
        self._request('load_extra_conf_file', {'filepath': file})

    def create_file(self, path, content):
        path = self._abs_path(path)
        with open(path, 'w') as f:
            f.write(content)

    def delete_file(self, path):
        path = self._abs_path(path)
        os.unlink(path)

    def parse(self, filepath, line, ch):
        self._update_ping()
        path = self._abs_path(filepath)
        with open(path) as f:
            request = {
                'event_name': 'FileReadyToParse',
                'filepath': path,
                'line_num': line + 1,
                'column_num': ch + 1,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c']
                    }
                }
            }
        result = self._request("event_notification", request)
        try:
            return result.json()
        except:
            return None

    def ping(self):
        self._update_ping()
        headers = {
            'X-Ycm-Hmac': self._hmac(''),
        }
        return requests.get("http://localhost:%d/healthy" % self._port, headers=headers).status_code == 200

    def get_completions(self, filepath, line, ch):
        self._update_ping()
        path = self._abs_path(filepath)
        with open(path) as f:
            request = {
                'column_num': ch + 1,
                'line_num': line + 1,
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
        print result.text
        if result.status_code == 200:
            response = result.json()
            completions = map(self._clean_symbol, filter(is_valid_symbol, response['completions'])[:10])
            return {
                'completions': completions,
                'completion_start_column': response['completion_start_column'],
            }
        else:
            return {'completions': []}

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
        if not abs_path.startswith(self.root_dir):
            raise Exception("Bad path")
        return abs_path

    def _request(self, endpoint, data=None):
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

    @staticmethod
    def _clean_symbol(sym):
        sym = sym.copy()
        sym['detailed_info'] = sym['detailed_info'].split("\n")[0]
        return sym
