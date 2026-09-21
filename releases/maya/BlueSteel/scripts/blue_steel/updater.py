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

try:
    import requests
except ImportError:
    requests = None
    from urllib import request
import json
from maya import cmds


LOGGER = logging.getLogger(__name__)

# Asset name pattern used by the release workflow (BlueSteel-<tag>.zip).
_ASSET_NAME_TEMPLATE = "BlueSteel-{tag}.zip"

# Top-level folder inside the release asset zip.
_ZIP_ROOT_FOLDER = "BlueSteel"

def get_latest_version(url: str) -> str:
    """
    Check if the current version of BlueSteel is the latest one available on GitHub.

    Returns:
        str: The latest version available on GitHub. If the current version is the latest,
        it returns the current version.
    """
    try:
        if requests is not None:
            response = requests.get(url)
            if response.status_code == 200:
                latest_version = response.json()["tag_name"]
                return latest_version
            else:
                print("Could not check for updates. Status code: {}".format(response.status_code))
                return None
        else:
            with request.urlopen(url) as response:
                if response.status == 200:
                    data = json.loads(response.read())
                    latest_version = data["tag_name"]
                    return latest_version
                else:
                    print("Could not check for updates. Status code: {}".format(response.status))
                    return None
    except Exception as e:
        print("An error occurred while checking for updates: {}".format(e))
        return None

def _get_bluesteel_root() -> str:
    """Return the local BlueSteel module root directory."""
    return cmds.moduleInfo(moduleName="blue_steel_maya", path=True)


def _fetch_release_info(url: str) -> dict:
    """Return the JSON payload for the latest GitHub release."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _find_asset_url(release: dict, tag: str) -> str:
    """Return the browser_download_url for the BlueSteel zip asset."""
    expected_name = _ASSET_NAME_TEMPLATE.format(tag=tag)
    for asset in release.get("assets", []):
        if asset.get("name") == expected_name:
            return asset["browser_download_url"]
    raise RuntimeError(
        "Release {} has no asset named '{}'. "
        "Available assets: {}".format(
            tag,
            expected_name,
            [a.get("name") for a in release.get("assets", [])],
        )
    )


def _download_asset(url: str) -> bytes:
    """Download a release asset and return its raw bytes."""
    LOGGER.info("Downloading %s …", url)
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    chunks = []
    for chunk in resp.iter_content(chunk_size=1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_zip(zip_bytes: bytes, dest: str) -> None:
    """Extract the release asset zip into *dest*.

    The zip contains a single top-level ``BlueSteel/`` folder.  Its
    contents are extracted directly into *dest* (stripping that prefix).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        prefix = "{}/".format(_ZIP_ROOT_FOLDER)

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
                "No files found under '{}' in the zip.".format(prefix)
            )
        LOGGER.info("Extracted %d files into %s", extracted, dest)


def update(url: str, version: str, force: bool = False) -> str:
    """Download and install the latest BlueSteel release.

    Args:
        url: The URL to fetch the latest release information from.
        force: If *True*, re-install even when the local version already
            matches the latest release.

    Returns:
        The version string that was installed (or the current version if
        no update was needed).
    """
    release = _fetch_release_info(url)
    latest_tag = release.get("tag_name", "")
    if not latest_tag:
        raise RuntimeError("Could not determine the latest release tag.")

    if not force and latest_tag == version:
        msg = "Already up-to-date ({}).".format(version)
        LOGGER.info(msg)
        cmds.warning(msg)
        return version

    asset_url = _find_asset_url(release, latest_tag)
    zip_bytes = _download_asset(asset_url)

    bluesteel_root = _get_bluesteel_root()
    LOGGER.info("BlueSteel root: %s", bluesteel_root)

    # Stage into a temporary directory next to the install so we stay on the
    # same filesystem (atomic rename / fast move).
    staging_dir = tempfile.mkdtemp(
        prefix="bluesteel_update_", dir=os.path.dirname(bluesteel_root)
    )
    backup_dir = bluesteel_root + "_backup"

    try:
        _extract_zip(zip_bytes, staging_dir)

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
        version, latest_tag
    )
    LOGGER.info(msg)
    cmds.warning(msg)
    return latest_tag
