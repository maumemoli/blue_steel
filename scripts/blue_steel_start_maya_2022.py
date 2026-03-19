import os
import sys
import subprocess
import inspect

CREATE_SPECIAL_REFERENCES = False

this_directory = os.path.abspath(os.path.split(__file__)[0])
plugin_dir = os.path.dirname(this_directory)
module_dir = plugin_dir + '\\releases'
user_dir = os.path.expanduser('~')

print("plugin_dir: ", plugin_dir)
print("module_dir: ", module_dir)
print("user_dir: ", user_dir)


MAYA_EXE = 'C:/Program Files/Autodesk/Maya2022/bin/maya.exe'

if CREATE_SPECIAL_REFERENCES:
    MAYA_PREFS = os.path.join(user_dir, 'blue_steel_maya_prefs')

    # Start with clean prefs
    os.environ['MAYA_APP_DIR'] = MAYA_PREFS
    print("Maya preferences for this session in : {}".format(os.environ['MAYA_APP_DIR']))

# Add this as maya module
os.environ['MAYA_MODULE_PATH'] = module_dir
print("module pah: ", os.environ['MAYA_MODULE_PATH'])

# pyton_reloader_code = inspect.getsourcelines(modules_reloader.reload_python_modules)[0]
# reloader_button = f'shelfButton -rpt true -i1 "pythonFamily.png" -l {pyton_reloader_code}'

# Open maya with this
command = " ""print \\\"Blue Steel NOT loaded, use the remote tester.py file!!\\\"\";"
subprocess.Popen([MAYA_EXE, '-command', command, ' -noAutoloadPlugins'])