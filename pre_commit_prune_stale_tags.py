from __future__ import annotations

import subprocess


def get_local_tags():
    """Return a set of all local tag names."""
    out = subprocess.check_output(["git", "tag", "-l"], text=True, stderr=subprocess.DEVNULL)  # noqa: S603, S607
    return {line.strip() for line in out.splitlines() if line.strip()}


def get_remote_tags():
    """Return a set of all remote tag names on 'origin'."""
    out = subprocess.check_output(["git", "ls-remote", "--tags", "origin"], text=True, stderr=subprocess.DEVNULL)  # noqa: S603, S607
    tags = set()
    for line in out.splitlines():
        # each line is "<hash>\\trefs/tags/<tagname>" or "<hash>\\trefs/tags/<tagname>^{}"
        parts = line.split()
        if len(parts) != 2:  # noqa: PLR2004
            continue
        ref = parts[1]
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref[len("refs/tags/") :]
        # strip off ^{} that marks peeled (annotated) tags
        if tag.endswith("^{}"):
            tag = tag[:-3]
        tags.add(tag)
    return tags


def prune_stale_tags():
    local = get_local_tags()
    remote = get_remote_tags()
    to_delete = sorted(local - remote)
    if not to_delete:
        return remote
    # Bulk-delete them:
    subprocess.check_output(["git", "tag", "-d", *to_delete], text=True)  # noqa: S603, S607
    return remote


if __name__ == "__main__":
    prune_stale_tags()
