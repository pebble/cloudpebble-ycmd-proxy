__author__ = 'katharine'

import os.path


class FileSync(object):
    def __init__(self, root_dir):
        assert isinstance(root_dir, basestring)
        self.root_dir = root_dir
        # Make this to see if it gets happier.
        with open(self.root_dir + '/.ycm_extra_conf.py', 'w') as f:
            f.write('#')
        self._patch_ids = {}
        self._pending_patches = {}

    def apply_patches(self, patch_sequence, was_pending=False):
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

        for filename in self._pending_patches:
            self._pending_patches[filename] = sorted(self._pending_patches[filename], key=lambda x: x['sequence'])
            pending = self._pending_patches[filename]

            while len(pending) > 0 and pending[0]['sequence'] == self._patch_ids[filename]:
                patch = pending.pop(0)
                self._patch_ids[filename] += 1
                abs_path = self.abs_path(patch['filename'])

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
                    f.flush()

    def create_file(self, path, content):
        path = self.abs_path(path)
        with open(path, 'w') as f:
            f.write(content)

    def delete_file(self, path):
        path = self.abs_path(path)
        os.unlink(path)

    def abs_path(self, path):
        abs_path = os.path.normpath(os.path.join(self.root_dir, path))
        if not abs_path.startswith(self.root_dir):
            raise Exception("Bad path")
        return abs_path
