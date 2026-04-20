import json
from . import env
from packaging.version import Version
try:
    import requests
except ImportError:
    requests = None
    from urllib import request
print("BlueSteel initialized on maya {} on python {}".format(env.MAYA_VERSION, env.PYTHON_VERSION))
if env.MAYA_VERSION < 2022 or env.PYTHON_VERSION < 3:
    raise RuntimeError("BlueSteel requires Maya 2022 or higher with Python 3.x")
__url__ = "https://api.github.com/repos/maumemoli/blue_steel/releases/latest"
__update_url__ = "https://github.com/maumemoli/blue_steel/releases/latest"
def get_latest_version()-> str:
    """
    Check if the current version of BlueSteel is the latest one available on GitHub.

    Returns:
        str: The latest version available on GitHub. If the current version is the latest,
        it returns the current version.
    """
    try:
        if requests is not None:
            response = requests.get(__url__)
            if response.status_code == 200:
                latest_version = response.json()["tag_name"]
                return latest_version
            else:
                print("Could not check for updates. Status code: {}".format(response.status_code))
                return None
        else:
            with request.urlopen(__url__) as response:
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


__version__ = Version(env.VERSION)
__author__ = "Maurizio Memoli"
__latest_version__ = Version(get_latest_version() or env.VERSION)
