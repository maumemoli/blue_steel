"""BlueSteel self-updater.

Downloads the latest release zip from GitHub and overwrites the local
BlueSteel module directory so the next Maya restart picks up new code.

Usage (from Maya Script Editor)::

    from blue_steel.updater import update
    update()
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
import logging

import requests
from maya import cmds

from . import env
from . import __url__, __version__

LOGGER = logging.getLogger(__name__)

# Subfolder inside the GitHub zipball that maps to the local module root.
_REPO_SUBPATH = "releases/maya/BlueSteel"


def _get_bluesteel_root() -> str:
    """Return the local BlueSteel module root directory."""
    return cmds.moduleInfo(moduleName="blue_steel_maya", path=True)


def _fetch_release_info() -> dict:
    """Return the JSON payload for the latest GitHub release."""
    resp = requests.get(__url__, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _download_zipball(zipball_url: str) -> bytes:
    """Download the zipball and return its raw bytes."""
    LOGGER.info("Downloading %s …", zipball_url)
    resp = requests.get(zipball_url, timeout=120, stream=True)
    resp.raise_for_status()
    chunks = []
    for chunk in resp.iter_content(chunk_size=1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_subfolder(zip_bytes: bytes, repo_subpath: str, dest: str) -> None:
    """Extract only *repo_subpath* from the zipball into *dest*.

    GitHub zipballs have a single top-level directory whose name is
    ``<owner>-<repo>-<short_sha>/``.  We strip that prefix plus
    *repo_subpath* so the extracted tree lands directly in *dest*.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Detect the top-level directory name (first entry).
        top_level = zf.namelist()[0].split("/")[0]
        prefix = "{}/{}/".format(top_level, repo_subpath.strip("/"))

        extracted = 0
        for info in zf.infolist():
            if not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            if not rel:
                continue

            target = os.path.join(dest, rel.replace("/", os.sep))
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1

        if extracted == 0:
            raise RuntimeError(
                "No files found under '{}' in the zipball.".format(prefix)
            )
        LOGGER.info("Extracted %d files into %s", extracted, dest)


def update(force: bool = False) -> str:
    """Download and install the latest BlueSteel release.

    Args:
        force: If *True*, re-install even when the local version already
            matches the latest release.

    Returns:
        The version string that was installed (or the current version if
        no update was needed).
    """
    release = _fetch_release_info()
    latest_tag = release.get("tag_name", "")
    if not latest_tag:
        raise RuntimeError("Could not determine the latest release tag.")

    if not force and latest_tag == __version__:
        msg = "Already up-to-date ({}).".format(__version__)
        LOGGER.info(msg)
        cmds.warning(msg)
        return __version__

    zipball_url = release.get("zipball_url")
    if not zipball_url:
        raise RuntimeError("No zipball URL found in the release payload.")

    zip_bytes = _download_zipball(zipball_url)

    bluesteel_root = _get_bluesteel_root()
    LOGGER.info("BlueSteel root: %s", bluesteel_root)

    # Stage into a temporary directory next to the install so we stay on the
    # same filesystem (atomic rename / fast move).
    staging_dir = tempfile.mkdtemp(
        prefix="bluesteel_update_", dir=os.path.dirname(bluesteel_root)
    )
    backup_dir = bluesteel_root + "_backup"

    try:
        _extract_subfolder(zip_bytes, _REPO_SUBPATH, staging_dir)

        # Swap: current -> backup, staging -> current.
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        os.rename(bluesteel_root, backup_dir)
        os.rename(staging_dir, bluesteel_root)

        # Clean up backup.
        shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        # Attempt to restore from backup on failure.
        if not os.path.exists(bluesteel_root) and os.path.exists(backup_dir):
            os.rename(backup_dir, bluesteel_root)
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    msg = "BlueSteel updated from {} to {}. Restart Maya to use the new version.".format(
        __version__, latest_tag
    )
    LOGGER.info(msg)
    cmds.warning(msg)
    return latest_tag
