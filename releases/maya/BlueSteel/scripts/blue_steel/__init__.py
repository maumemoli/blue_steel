from . import env
print("BlueSteel initialized on maya {} on python".format(env.MAYA_VERSION, env.PYTHON_VERSION))
if env.MAYA_VERSION < 2022 or env.PYTHON_VERSION < 3:
    raise RuntimeError("BlueSteel requires Maya 2022 or higher with Python 3.x")