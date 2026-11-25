cmake_minimum_required(VERSION 3.21)
project(frontart VERSION 0.1.0 LANGUAGES CXX)

# The distribution sets these (packages/pkgbuild/frontart/PKGBUILD.in).
set(APP_ID "frontline-frontart" CACHE STRING "Executable, desktop file and icon name")
set(APP_NAME "FrontArt" CACHE STRING "Name shown to the user")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets)
find_package(ZLIB REQUIRED)
include(GNUInstallDirs)

qt_standard_project_setup(REQUIRES 6.5)

qt_add_executable(frontart
    src/main.cpp
    src/mainwindow.h src/mainwindow.cpp
    src/canvas.h src/canvas.cpp
    src/document.h src/document.cpp
    src/brush.h src/brush.cpp
    src/colorpicker.h src/colorpicker.cpp
    src/zip.h src/zip.cpp)
set_target_properties(frontart PROPERTIES OUTPUT_NAME "${APP_ID}")
target_compile_definitions(frontart PRIVATE
    APP_ID="${APP_ID}"
    APP_NAME="${APP_NAME}"
    APP_VERSION="${PROJECT_VERSION}")
target_link_libraries(frontart PRIVATE Qt6::Widgets ZLIB::ZLIB)

install(TARGETS frontart RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
configure_file(data/frontart.desktop.in ${CMAKE_CURRENT_BINARY_DIR}/${APP_ID}.desktop @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/${APP_ID}.desktop DESTINATION ${CMAKE_INSTALL_DATADIR}/applications)
install(FILES data/frontart.svg
        DESTINATION ${CMAKE_INSTALL_DATADIR}/icons/hicolor/scalable/apps RENAME ${APP_ID}.svg)
