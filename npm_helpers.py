import contextlib
import glob
import json
import os
import re
import shutil
import subprocess
import zipfile

import settings
from projectinfo import Resource


class NPMInstallError(Exception):
    pass


@contextlib.contextmanager
def temporary_package_json(root_dir, dependencies):
    package_path = os.path.join(root_dir, 'package.json')
    try:
        with open(package_path, 'w') as f:
            json.dump({
                "name": "cloudpebble-ycmd-proxy",
                "version": "1.0.0",
                "description": "A temporary package.json",
                "repository": None,
                "license": "",
                "dependencies": dependencies
            }, f)
        yield
    finally:
        os.unlink(package_path)


def validate_dependencies(dependencies):
    """ Check that none of the version strings in a dictionary of dependencies reference local paths. """
    # CloudPebble performs identical checks for this, so hopefully it should never actually get triggered.
    for version in dependencies.values():
        if re.match(r'^file:|(\.*|~)/', version):
            raise ValueError("Dependencies are not allowed to reference paths")


def install_dependencies(dependencies, root_dir):
    """ Install some npm dependencies into a directory and then extract the headers
    :param dependencies: a dictionary of name->version
    :param root_dir: the directory to install into
    """
    validate_dependencies(dependencies)
    # Make a minimal package.json file
    with temporary_package_json(root_dir, dependencies):
        try:
            # Install all the dependencies
            # TODO: Should NPM itself have resource limits?
            subprocess.check_output([settings.NPM_BINARY, "prune"], stderr=subprocess.STDOUT, cwd=root_dir)
            if dependencies:
                subprocess.check_output([settings.NPM_BINARY, "install", "--ignore-scripts"], stderr=subprocess.STDOUT, cwd=root_dir)
                subprocess.check_output([settings.NPM_BINARY, "dedupe"], stderr=subprocess.STDOUT, cwd=root_dir)
        except subprocess.CalledProcessError:
            # Setting the error message to e.output here would let the user see their lovely NPM error output.
            raise NPMInstallError("One or more of your dependencies cannot be installed. Please check that the names and versions for all of your dependencies are valid.")


def _recursive_file_search(base, filename):
    for dirname, _, filenames in os.walk(base):
        if filename in filenames:
            yield os.path.join(dirname, filename)


def get_package_metadata(root_dir):
    """ Given a directory with a node_modules directory full of pebble modules, get all of their messageKeys and resource type/name information
    :param root_dir:
    :return: (array of resources, array of (type, name) tuples
    """
    resources = []
    messagekeys = []
    for package_path in _recursive_file_search(os.path.join(root_dir, 'node_modules'), 'package.json'):
        with open(package_path, 'r') as f:
            data = json.load(f)
            if 'pebble' not in data:
                continue
            messagekeys.extend(data['pebble'].get('messageKeys', []))
            resources.extend(Resource(r['type'], r['name']) for r in data['pebble'].get('resources', {}).get('media', []))
    return resources, messagekeys


def extract_library_headers(root_dir):
    """ Given a directory with a node_modules directory full of Pebble modules, extract all of their header files into ./librares/include/<module_name>
    :param root_dir: base directory
    """
    # Make the libraries directory if it does not exist
    libs_path = os.path.join(root_dir, 'libraries')
    if os.path.isdir(libs_path):
        shutil.rmtree(libs_path)
    node_modules = os.path.join(root_dir, 'node_modules')
    os.mkdir(libs_path)
    # Look for C modules with dist.zip files
    for zip_path in _recursive_file_search(node_modules, 'dist.zip'):
        try:
            # Construct the expected path to the library's headers based on its name
            includes_path = os.path.join('include', os.path.dirname(os.path.relpath(zip_path, node_modules)))
            with zipfile.ZipFile(zip_path) as z:
                # Extract any header files which are inside 'include/<module_name>'
                for zip_entry in z.infolist():
                    if zip_entry.filename.startswith(includes_path) and zip_entry.filename.endswith('.h'):
                        z.extract(zip_entry, libs_path)
        except Exception:
            raise NPMInstallError("One or more of your dependencies is not a valid pebble library.")
