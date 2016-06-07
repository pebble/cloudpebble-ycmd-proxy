""" These are integration tests which just exist to help with development. They are not particularly exhaustive are not
run automatically.
The dependencies test relies on the the git repo Spacerat/libname existing. """

import unittest
import subprocess

from ycm_helpers import spinup, kill_completers, get_completions

SIMPLE_CONTENT = """
#include <pebble.h>

int main(void) {
  APP_LOG(APP_LOG_LEVEL_DEBUG, "Hello World!");
  APP
}
"""

LIBNAME = 'spacerat/libname'
LIBRARY_EXPECTED_COMPLETION = 'world'
LIBRARIES_CONTENT = """
#include <pebble.h>
#include "libname/whatever.h"

int main(void) {
  APP_LOG(APP_LOG_LEVEL_DEBUG, "Hello %s", world());
  worl
}
"""


class TestYCM(unittest.TestCase):
    def tearDown(self):
        kill_completers()

    def spinup(self, options):
        options['sdk'] = options.get('sdk', '3')
        result = spinup(options)
        self.assertTrue(result['success'])
        return result['uuid']

    def expect_completion(self, uuid, line, ch, expect, filename='main.c'):
        self.assertIn(expect, [x['insertion_text'] for x in get_completions(uuid, {
            'file': filename,
            'line': line,
            'ch': ch
        })['completions']])

    def test_spinup(self):
        """ Check that spinup and a completion of 'APP_LOG' works """
        uuid = self.spinup({'files': {'main.c': SIMPLE_CONTENT}})
        self.expect_completion(uuid, 5, 6, 'APP_LOG')

    def test_dependencies(self):
        """ Check that YCM can autocomplete on external libraries. """
        try:
            uuid = self.spinup({
                'files': {'main.c': LIBRARIES_CONTENT},
                'dependencies': {'libname': LIBNAME}
            })
        except subprocess.CalledProcessError as e:
            print e.output
            raise
        self.expect_completion(uuid, 6, 6, LIBRARY_EXPECTED_COMPLETION)

    def test_bad_dependency(self):
        """ Check that YCM fails to spinup if unsafe dependencies are specified. """
        with self.assertRaises(ValueError):
            self.spinup({
                'files': {'main.c': LIBRARIES_CONTENT},
                'dependencies': {'libname': '../local/file'}
            })
