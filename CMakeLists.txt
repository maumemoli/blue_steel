cmake_minimum_required(VERSION 3.20)

project(BlueSteelPlugins VERSION 0.1.0 LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Toolchain rules
# ---------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Maya links against the *dynamic* CRT. Building with /MT produces a plugin
# that crashes or fails to load with a nonsensical error, so force /MD.
if(MSVC AND NOT DEFINED CMAKE_MSVC_RUNTIME_LIBRARY)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
endif()

# ---------------------------------------------------------------------------
# Locate the Maya devkit
# ---------------------------------------------------------------------------
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake")

set(MAYA_VERSION "2026" CACHE STRING "Target Maya version")
set(MAYA_LOCATION "" CACHE PATH "Maya devkit root (contains include/ and lib/)")

# Keep the devkit path out of the repo so the same file works on every machine.
# Priority: -DMAYA_LOCATION > $MAYA_DEVKIT_<version> > $MAYA_LOCATION > default.
if(NOT MAYA_LOCATION)
    if(DEFINED ENV{MAYA_DEVKIT_${MAYA_VERSION}})
        set(MAYA_LOCATION "$ENV{MAYA_DEVKIT_${MAYA_VERSION}}")
    elseif(DEFINED ENV{MAYA_LOCATION})
        set(MAYA_LOCATION "$ENV{MAYA_LOCATION}")
    endif()
endif()

# cmake/FindMaya.cmake only sets its own MAYA_FOUND flag, not Maya_FOUND, so
# REQUIRED would misfire here - validate the paths ourselves instead.
find_package(Maya)

if(NOT MAYA_INCLUDE_DIR OR NOT MAYA_LIBRARY_DIR)
    message(FATAL_ERROR
        "Maya ${MAYA_VERSION} devkit not found.\n"
        "  MAYA_LOCATION = '${MAYA_LOCATION}'\n"
        "Fix it with one of:\n"
        "  -DMAYA_LOCATION=C:/devkit/Maya${MAYA_VERSION}   (on the configure line)\n"
        "  setx MAYA_DEVKIT_${MAYA_VERSION} C:\\devkit\\Maya${MAYA_VERSION}\n"
        "The folder must contain include/maya/MFn.h and lib/Foundation.lib.")
endif()

message(STATUS "Maya ${MAYA_VERSION} includes : ${MAYA_INCLUDE_DIR}")
message(STATUS "Maya ${MAYA_VERSION} libraries: ${MAYA_LIBRARY_DIR}")

# Only link libraries this devkit actually ships (clew/OpenMayaFX come and go
# between Maya versions).
set(MAYA_LINK_LIBRARIES "")
foreach(_maya_lib OpenMaya OpenMayaAnim OpenMayaFX OpenMayaRender OpenMayaUI Foundation clew)
    find_library(MAYA_${_maya_lib}_LIBRARY
        NAMES ${_maya_lib}
        PATHS ${MAYA_LIBRARY_DIR}
        NO_DEFAULT_PATH)
    if(MAYA_${_maya_lib}_LIBRARY)
        list(APPEND MAYA_LINK_LIBRARIES "${MAYA_${_maya_lib}_LIBRARY}")
    else()
        message(STATUS "Maya ${MAYA_VERSION} has no ${_maya_lib} library - skipped")
    endif()
endforeach()

# ---------------------------------------------------------------------------
# Plugin target
# ---------------------------------------------------------------------------
# The output file name MUST match the name Maya registers, and it must also
# match the folder layout of the release module (releases/maya/BlueSteel).
set(PLUGIN_TARGET blueSteel)

set(PLUGIN_SOURCES
    source/blueSteelPlugin.cpp
    # Add nodes / commands / deformers here as you write them.
)

add_library(${PLUGIN_TARGET} SHARED ${PLUGIN_SOURCES})

target_include_directories(${PLUGIN_TARGET} PRIVATE "${MAYA_INCLUDE_DIR}")
target_link_libraries(${PLUGIN_TARGET} PRIVATE ${MAYA_LINK_LIBRARIES})

target_compile_definitions(${PLUGIN_TARGET} PRIVATE
    $<$<PLATFORM_ID:Windows>:NT_PLUGIN>
    $<$<PLATFORM_ID:Windows>:_BOOL>
    $<$<PLATFORM_ID:Windows>:REQUIRE_IOSTREAM>
)

if(MSVC)
    target_compile_options(${PLUGIN_TARGET} PRIVATE /W4 /permissive- /utf-8)
    target_compile_definitions(${PLUGIN_TARGET} PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

set_target_properties(${PLUGIN_TARGET} PROPERTIES PREFIX "")

if(WIN32)
    # .mll files are DLLs, so they land in RUNTIME, not LIBRARY.
    set_target_properties(${PLUGIN_TARGET} PROPERTIES
        SUFFIX ".mll"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plug-ins"
        ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
        PDB_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plug-ins")
    # No /export:initializePlugin here: MFnPlugin.h declares the entry points
    # with PLUGIN_EXPORT (__declspec(dllexport)), so they are exported by the
    # declaration itself, and the linker-visible symbol names are mangled -
    # an /export:<unmangled name> flag would fail with LNK2001.
elseif(APPLE)
    set_target_properties(${PLUGIN_TARGET} PROPERTIES
        SUFFIX ".bundle"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plug-ins")
else()
    set_target_properties(${PLUGIN_TARGET} PROPERTIES
        SUFFIX ".so"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plug-ins")
endif()

# `cmake --install build/2026 --config Release --prefix releases/maya/BlueSteel`
install(TARGETS ${PLUGIN_TARGET}
    RUNTIME DESTINATION plug-ins
    LIBRARY DESTINATION plug-ins)

# ---------------------------------------------------------------------------
# Smoke test / debugging notes
# ---------------------------------------------------------------------------
# Release   : ships.
# Debug     : a MSVC-debug-CRT plugin usually refuses to load in release Maya.
# RelWithDebInfo : what you want while debugging - optimised like Maya, with a
#                  matching .pdb so you can attach VS to maya.exe.
add_custom_command(TARGET ${PLUGIN_TARGET} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo
        "Built $<TARGET_FILE:${PLUGIN_TARGET}>"
    VERBATIM)
