from . import env
import requests
print("BlueSteel initialized on maya {} on python".format(env.MAYA_VERSION, env.PYTHON_VERSION))
if env.MAYA_VERSION < 2022 or env.PYTHON_VERSION < 3:
    raise RuntimeError("BlueSteel requires Maya 2022 or higher with Python 3.x")
__version__ = env.VERSION
__author__ = "Maurizio Memoli"
__latest_version__ = __version__
__url__ = "https://api.github.com/repos/maumemoli/blue_steel/releases/latest"

def check_latest_version()-> str:
    """
    Check if the current version of BlueSteel is the latest one available on GitHub.

    Returns:
        str: The latest version available on GitHub. If the current version is the latest,
        it returns the current version.
    """
    try:
        response = requests.get(__url__)
        if response.status_code == 200:
            latest_version = response.json()["tag_name"]
            if latest_version != __version__:
                print("A new version of BlueSteel is available: {}. You are currently using version {}.".format(latest_version, __version__))
                return latest_version
            else:
                return __version__
        else:
            print("Could not check for updates. Status code: {}".format(response.status_code))
            return __version__
    except Exception as e:
        print("An error occurred while checking for updates: {}".format(e))
        return __version__