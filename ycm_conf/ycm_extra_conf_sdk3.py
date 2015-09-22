import os

if os.environ['PLATFORM'] == 'basalt':
    def FlagsForFile(filename, **kwargs):
        return {{
            'flags': [
                '-std=c11',
                '-x',
                'c',
                '-Wall',
                '-Wextra',
                '-Werror',
                '-Wno-unused-parameter',
                '-Wno-error=unused-function',
                '-Wno-error=unused-variable',
                '-I{sdk}/Pebble/basalt/include',
                '-I{here}/build',
                '-I{here}',
                '-I{here}/build/src',
                '-I{here}/src',
                '-isystem',
                '{stdlib}',
                '-DRELEASE',
                '-DPBL_PLATFORM_BASALT',
                '-DPBL_COLOR',
                '-DPBL_SDK_3',
                '-D_TIME_H_',
            ],
            'do_cache': True,
        }}
elif os.environ['PLATFORM'] == 'aplite':
    def FlagsForFile(filename, **kwargs):
        return {{
            'flags': [
                '-std=c11',
                '-x',
                'c',
                '-Wall',
                '-Wextra',
                '-Werror',
                '-Wno-unused-parameter',
                '-Wno-error=unused-function',
                '-Wno-error=unused-variable',
                '-I{sdk}/Pebble/aplite/include',
                '-I{here}/build',
                '-I{here}',
                '-I{here}/build/src',
                '-I{here}/src',
                '-isystem',
                '{stdlib}',
                '-DRELEASE',
                '-DPBL_PLATFORM_APLITE',
                '-DPBL_BW',
                '-DPBL_SDK_2',
            ],
            'do_cache': True,
        }}
if os.environ['PLATFORM'] == 'chalk':
    def FlagsForFile(filename, **kwargs):
        return {{
            'flags': [
                '-std=c11',
                '-x',
                'c',
                '-Wall',
                '-Wextra',
                '-Werror',
                '-Wno-unused-parameter',
                '-Wno-error=unused-function',
                '-Wno-error=unused-variable',
                '-I{sdk}/Pebble/chalk/include',
                '-I{here}/build',
                '-I{here}',
                '-I{here}/build/src',
                '-I{here}/src',
                '-isystem',
                '{stdlib}',
                '-DRELEASE',
                '-DPBL_PLATFORM_CHALK',
                '-DPBL_COLOR',
                '-DPBL_SDK_3',
                '-D_TIME_H_',
            ],
            'do_cache': True,
        }}

else:
    raise Exception("Need a platform.")
