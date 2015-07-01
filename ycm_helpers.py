#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
import uuid
import tempfile
import os
import os.path
import errno
import gevent
import collections
import traceback

import settings
from ycm import YCM
from filesync import FileSync

mapping = {}

YCMHolder = collections.namedtuple('YCMHolder', ('filesync', 'ycms'))
CodeCompletion = collections.namedtuple('CodeCompletion', ('kind', 'insertion_text', 'extra_menu_info', 'detailed_info'))

class YCMProxyException(Exception):
    pass


def spinup(content):
    root_dir = tempfile.mkdtemp()
    platforms = set(content.get('platforms', ['aplite']))
    sdk_version = content.get('sdk', '2')
    print "spinup in %s" % root_dir
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
            f.write(content.encode('utf-8'))

    filesync = FileSync(root_dir)
    ycms = YCMHolder(filesync=filesync, ycms={})

    print "created files"
    settings_path = os.path.join(root_dir, ".ycm_extra_conf.py")

    conf_mapping = {
        '2': 'ycm_extra_conf_sdk2.py',
        '3': 'ycm_extra_conf_sdk3.py',
    }
    sdk_mapping = {
        '2': settings.PEBBLE_SDK2,
        '3': settings.PEBBLE_SDK3,
    }

    with open(settings_path, "w") as f:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ycm_conf', conf_mapping[sdk_version])) as template:
            f.write(template.read().format(sdk=sdk_mapping[sdk_version], here=root_dir, stdlib=settings.STDLIB_INCLUDE_PATH))

    try:
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
    except Exception as e:
        print "Failed to spawn ycm with root_dir %s" % root_dir
        print traceback.format_exc()
        return dict(success=False, error=str(e)), 500

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = ycms
    # print mapping
    print "spinup complete (%s); %s -> %s" % (platforms, this_uuid, root_dir)
    # victory!
    return dict(success=True, uuid=this_uuid)


def get_completions(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    completions = collections.OrderedDict()
    completion_start_column = None
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        ycm.parse(data['file'], data['line'], data['ch'])  # TODO: Should we do this here?
        platform_completions = ycm.get_completions(data['file'], data['line'], data['ch'])
        if platform_completions is not None:
            completion_start_column = platform_completions['completion_start_column']
            for completion in platform_completions['completions']:
                if completion['insertion_text'] in completions:
                    continue
                completions[completion['insertion_text']] = completion

    return dict(
        completions=completions.values(),
        start_column=completion_start_column,
    )


def get_errors(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    errors = {}
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        result = ycm.parse(data['file'], data['line'], data['ch'])
        if 'exception' in result:
            continue
        if result is None:
            continue
        for error in result:
            error_key = (error['kind'], error['location']['line_num'], error['text'])
            if error_key in errors:
                errors[error_key]['platforms'].append(platform)
            else:
                error['platforms'] = [platform]
                errors[error_key] = error

    return dict(
        errors=errors.values()
    )


def go_to(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    for platform, ycm in sorted(ycms.ycms.iteritems(), reverse=True):
        ycm.parse(data['file'], data['line'], data['ch'])
        result = ycm.go_to(data['file'], data['line'], data['ch'])
        if result is not None:
            return dict(location=result)
    return dict(location=None)


def create_file(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    ycms.filesync.create_file(data['filename'], data['content'])
    return 'ok'


def delete_file(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    ycms.filesync.delete_file(data['filename'])
    return 'ok'


def ping(process_uuid, data=None):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    for ycm in mapping[process_uuid].ycms.itervalues():
        if not ycm.ping():
            raise YCMProxyException("Failed to ping YCM")

    return 'ok'

def kill_completers():
    global mapping
    for ycms in mapping.itervalues():
        for ycm in ycms.ycms.itervalues():
            ycm.close()
    mapping = {}

def monitor_processes(mapping):
    while True:
        print "process sweep running"
        gevent.sleep(20)
        to_kill = set()
        for uuid, ycms in mapping.iteritems():
            for platform, ycm in ycms.ycms.iteritems():
                if not ycm.alive:
                    print "killing %s:%s (alive: %s)" % (uuid, platform, ycm.alive)
                    ycm.close()
                    to_kill.append(uuid)
        for uuid in to_kill:
            del mapping[uuid]
    print "process sweep collected %d instances" % len(to_kill)


