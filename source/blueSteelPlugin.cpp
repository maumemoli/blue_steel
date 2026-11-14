/**
 * @file blueSteelPlugin.cpp
 * @brief Minimal Maya 2026 plug-in used as a toolchain smoke test.
 *
 * It registers nothing on purpose: if this builds and loads, your devkit,
 * MSVC toolset and CRT mismatch problems are ruled out before you write the
 * real node/command code.
 *
 * Load it in Maya's Script Editor:
 *     loadPlugin "C:/git/blue_steel/build/2026/plug-ins/Release/blueSteel.mll";
 * Expect: [blueSteel] loaded from build <date>, Maya <version>
 *
 * The file name (blueSteel.mll) must keep matching kPluginName, otherwise
 * `pluginInfo` and the .mod file in releases/maya/BlueSteel will not line up.
 */
#include <maya/MFnPlugin.h>
#include <maya/MGlobal.h>
#include <maya/MStatus.h>
#include <maya/MString.h>

namespace {
const char* const kPluginName = "blueSteel";
const char* const kVendor = "Blue Steel";
const char* const kVersion = "0.1.0";
}  // namespace

// MFnPlugin.h already declares these with C++ linkage plus PLUGIN_EXPORT
// (__declspec(dllexport)), so adding `extern "C"` here is a hard error on
// MSVC (C2732: linkage specification contradicts earlier specification).
MStatus initializePlugin(MObject obj)
{
    MFnPlugin plugin(obj, kVendor, kVersion, "Any");

    MString info("[");
    info += kPluginName;
    info += "] loaded from build " __DATE__ " " __TIME__ ", Maya ";
    info += MGlobal::mayaVersion();
    MGlobal::displayInfo(info);

    return MS::kSuccess;
}

MStatus uninitializePlugin(MObject /*obj*/)
{
    MString info("[");
    info += kPluginName;
    info += "] unloaded";
    MGlobal::displayInfo(info);
    return MS::kSuccess;
}
