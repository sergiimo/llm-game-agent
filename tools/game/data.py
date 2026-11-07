"""Cheap disk revisions for mutable learned image data; never a daemon restart trigger."""
import os


def image_revision(directory):
    """Additions, replacements and removals invalidate feature caches in the same process."""
    rows = []
    for root, _, files in os.walk(directory):
        for name in sorted(files):
            if name.endswith('.png'):
                path = os.path.join(root, name)
                try:
                    s = os.stat(path)
                except FileNotFoundError:  # a concurrent removal; the next read observes the new revision
                    continue
                rows.append((path, s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino))
    return (os.path.abspath(directory), tuple(sorted(rows)))
