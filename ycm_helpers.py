#!/usr/bin/env python
import gevent.monkey;

gevent.monkey.patch_all(subprocess=True)
import uuid
import tempfile
import os
import os.path
import errno
import gevent
import collections
import traceback
import atexit
import subprocess
import zipfile
import json
import glob
import re

import settings
from ycm import YCM
from filesync import FileSync

mapping = {}

YCMHolder = collections.namedtuple('YCMHolder', ('filesync', 'ycms'))
CodeCompletion = collections.namedtuple('CodeCompletion',
                                        ('kind', 'insertion_text', 'extra_menu_info', 'detailed_info'))


class YCMProxyException(Exception):
    pass


def spinup(content):
    root_dir = tempfile.mkdtemp()
    platforms = set(content.get('platforms', ['aplite']))
    sdk_version = content.get('sdk', '2')
    dependencies = content.get('dependencies', {})

    print "spinup in %s" % root_dir
    # Dump all the files we should need.
    for path, file_content in content['files'].iteritems():
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
            f.write(file_content.encode('utf-8'))

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

    if dependencies:
        install_dependencies(dependencies, root_dir)

    with open(settings_path, "w") as f:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ycm_conf',
                               conf_mapping[sdk_version])) as template:
            f.write(template.read().format(sdk=sdk_mapping[sdk_version], here=root_dir,
                                           stdlib=settings.STDLIB_INCLUDE_PATH))

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

        if 'chalk' in platforms:
            ycm = YCM(filesync, 'chalk')
            ycm.wait()
            ycm.apply_settings(settings_path)
            ycms.ycms['chalk'] = ycm

    except Exception as e:
        print "Failed to spawn ycm with root_dir %s" % root_dir
        print traceback.format_exc()
        return dict(success=False, error=str(e))

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = ycms
    # print mapping
    print "spinup complete (%s); %s -> %s" % (platforms, this_uuid, root_dir)
    # victory!
    return dict(success=True, uuid=this_uuid)


def dump_minimal_package_json(fp, dependencies):
    return json.dump({
        "name": "cloudpebble-ycmd-proxy",
        "version": "1.0.0",
        "dependencies": dependencies
    }, fp)


def validate_dependencies(dependencies):
    """ Check that none of the version strings in a dictionary of dependencies reference local paths. """
    # CloudPebble performs identical checks for this, so hopefully it should never actually get triggered.
    for version in dependencies.values():
        if re.match(r'^file:|(\.*|~)/', version):
            raise ValueError("Dependencies are not allowed to reference paths")


def install_dependencies(dependencies, root_dir):
    validate_dependencies(dependencies)
    # Make a minimal package.json file referencing all the dependencies
    package_path = os.path.join(root_dir, 'package.json')
    with open(package_path, 'w') as f:
        dump_minimal_package_json(f, dependencies)

    try:
        # Install all the dependencies
        # TODO: Should NPM itself have resource limits?
        # TODO: Should we prune, or delete node_modules?
        subprocess.check_output([settings.NPM_BINARY, "prune"], stderr=subprocess.STDOUT, cwd=root_dir)
        subprocess.check_output([settings.NPM_BINARY, "install", "--ignore-scripts"], stderr=subprocess.STDOUT, cwd=root_dir)
        # Make the libraries directory if it does not exist
        libs_path = os.path.join(root_dir, 'libraries')
        if not os.path.isdir(libs_path):
            os.mkdir(libs_path)
        # Look for C modules with dist.zip files
        for zip_path in glob.glob(os.path.join(root_dir, 'node_modules', '*', 'dist.zip')):
            # Construct the expected path to the library's headers based on its name
            includes_path = os.path.join('include', os.path.basename(os.path.dirname(zip_path)))
            with zipfile.ZipFile(zip_path) as z:
                # Extract any header files which are inside 'include/<module_name>'
                for zip_entry in z.infolist():
                    if zip_entry.filename.startswith(includes_path) and zip_entry.filename.endswith('.h'):
                        z.extract(zip_entry, libs_path)
    except subprocess.CalledProcessError as e:
        print e.output
        raise
    finally:
        # Clean up
        os.unlink(package_path)


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
        if result is None:
            continue
        if 'exception' in result:
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


def update_dependencies(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    install_dependencies(data['dependencies'], ycms.filesync.root_dir)


def create_file(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    ycms.filesync.create_file(data['filename'], data['content'])


def delete_file(process_uuid, data):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    ycms = mapping[process_uuid]
    ycms.filesync.delete_file(data['filename'])


def ping(process_uuid, data=None):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    for ycm in mapping[process_uuid].ycms.itervalues():
        if not ycm.ping():
            raise YCMProxyException("Failed to ping YCM")


def kill_completer(process_uuid):
    global mapping
    if process_uuid in mapping:
        for platform, ycm in mapping[process_uuid].ycms.iteritems():
            print "killing %s:%s (alive: %s)" % (process_uuid, platform, ycm.alive)
            ycm.close()
        del mapping[process_uuid]
    else:
        print "no uuid %s to kill" % process_uuid


def kill_completers():
    global mapping

    for ycms in mapping.itervalues():
        for ycm in ycms.ycms.itervalues():
            ycm.close()
    mapping = {}


def monitor_processes():
    global mapping

    def monitor(process_mapping):
        while True:
            print "process sweep running"
            gevent.sleep(20)
            to_kill = set()

            for process_uuid, ycms in process_mapping.iteritems():
                for platform, ycm in ycms.ycms.iteritems():
                    if not ycm.alive:
                        print "killing %s:%s (alive: %s)" % (process_uuid, platform, ycm.alive)
                        ycm.close()
                        to_kill.add(process_uuid)
            for process_uuid in to_kill:
                del process_mapping[process_uuid]
            print "process sweep collected %d instances" % len(to_kill)

    g = gevent.spawn(monitor, mapping)
    atexit.register(lambda: g.kill())
