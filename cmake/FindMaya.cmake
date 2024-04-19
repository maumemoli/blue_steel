# Set a default Maya version if not specified
if(NOT DEFINED MAYA_VERSION)
	set(MAYA_VERSION 2022 CACHE STRING "Maya version")
endif()


if((UNIX AND NOT APPLE) AND (NOT DEFINED ENV{PY_VER_A} OR NOT PY_VER_A))
	message("Please set PY_VER_A cmake variable or env variable to 2 or 3 to select the target python version.")
endif()

if (WIN32)
	set(MAYA_DEFAULT_LOCATION "C:/Program Files/Autodesk/Maya${MAYA_VERSION}")
	set(OPEN_MAYA OpenMaya.lib)
	set(FOUNDATION Foundation.lib)
	set(LIB_SUFFIX "lib/")
elseif(APPLE)
	set(MAYA_DEFAULT_LOCATION "/Applications/Autodesk/maya${MAYA_VERSION}")
	set(OPEN_MAYA libOpenMaya.dylib)
	set(FOUNDATION libFoundation.dylib)
	set(LIB_SUFFIX "Maya.app/Contents/MacOS")
elseif(UNIX)
	set(MAYA_DEFAULT_LOCATION "/usr/autodesk/maya${MAYA_VERSION}")
	set(OPEN_MAYA libOpenMaya.so)
	set(FOUNDATION libFoundation.so)
	set(LIB_SUFFIX "lib/")
	if(${PY_VER_A} EQUAL 2)
		set(LIB_PYTHON_SUFFIX "lib${PY_VER_A}/")
	endif()
endif()

find_path(MAYA_BASE_DIR
	include/maya/MFn.h
	HINTS
		${MAYA_LOCATION}
		$ENV{MAYA_LOCATION}
		${MAYA_DEFAULT_LOCATION}
	
	DOC
		"Maya's base path"
	)

find_path(MAYA_INCLUDE_DIR
	maya/MFn.h
	HINTS
		${MAYA_LOCATION}
		$ENV{MAYA_LOCATION}
		${MAYA_DEFAULT_LOCATION}
	PATH_SUFFIXES
		"include/"
	DOC
		"Maya's include path"
	)

message(STATUS "maya include dir: ${MAYA_INCLUDE_DIR}")

find_path(MAYA_LIBRARY_DIR
		${FOUNDATION}
	HINTS
		${MAYA_LOCATION}
		$ENV{MAYA_LOCATION}
		${MAYA_DEFAULT_LOCATION}
	PATH_SUFFIXES
		${LIB_SUFFIX}
	DOC
		"Maya's libraries path"
	)

message(STATUS "maya library  dir: ${MAYA_LIBRARY_DIR}")

if(UNIX AND NOT APPLE)
	find_path(MAYA_PYTHON_LIBRARY_DIR
			${OPEN_MAYA}
		HINTS
			${MAYA_LOCATION}
			$ENV{MAYA_LOCATION}
			${MAYA_DEFAULT_LOCATION}
		PATH_SUFFIXES
			${LIB_PYTHON_SUFFIX}
			${LIB_SUFFIX}
		DOC
			"Maya's Python libraries path"
		)
	if(MAYA_LIBRARY_DIR)
		set(MAYA_LIBRARY_DIR ${MAYA_LIBRARY_DIR} ${MAYA_PYTHON_LIBRARY_DIR})
	endif()
endif()

if (MAYA_INCLUDE_DIR AND MAYA_LIBRARY_DIR)
	set(MAYA_FOUND TRUE)
endif()
