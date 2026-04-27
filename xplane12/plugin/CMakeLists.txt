cmake_minimum_required(VERSION 3.20)

project(XPlane12ImageBridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(OpenGL REQUIRED)

add_library(XPlane12ImageBridge MODULE XPlane12ImageBridge.cpp)

target_include_directories(
  XPlane12ImageBridge
  PRIVATE
    /mnt/Yanlai/.tmp_xplane_sdk/SDK/CHeaders
)

target_compile_definitions(
  XPlane12ImageBridge
  PRIVATE
    APL=0
    IBM=0
    LIN=1
    XPLM200=1
    XPLM210=1
    XPLM300=1
    XPLM302=1
    XPLM400=1
    XPLM410=1
    XPLM420=1
    XPLM430=1
)

target_link_libraries(XPlane12ImageBridge PRIVATE OpenGL::GL)

target_link_options(
  XPlane12ImageBridge
  PRIVATE
    -Wl,--allow-shlib-undefined
)

set_target_properties(
  XPlane12ImageBridge
  PROPERTIES
    PREFIX ""
    SUFFIX ".xpl"
    OUTPUT_NAME "XPlane12ImageBridge"
)
