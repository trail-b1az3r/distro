cmake_minimum_required(VERSION 3.21)
project(write VERSION 0.1.0 LANGUAGES CXX)

# The distribution sets these (packages/pkgbuild/write/PKGBUILD.in).
set(APP_ID "nexora-write" CACHE STRING "Executable, desktop file and data directory name")
set(APP_NAME "Nexora Write" CACHE STRING "Name shown to the user")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2 WebEngineQuick)
find_package(KF6SyntaxHighlighting REQUIRED)
find_package(LibArchive REQUIRED)
include(GNUInstallDirs)
find_program(CARGO_EXECUTABLE cargo REQUIRED)
set(WRITE_BACKEND_MANIFEST "${CMAKE_CURRENT_SOURCE_DIR}/backend/Cargo.toml")
set(WRITE_BACKEND_TARGET_DIR "${CMAKE_CURRENT_BINARY_DIR}/rust-target")
set(WRITE_BACKEND_BINARY "${WRITE_BACKEND_TARGET_DIR}/release/nexora-write-backend")
add_custom_command(OUTPUT "${WRITE_BACKEND_BINARY}"
    COMMAND ${CMAKE_COMMAND} -E env CARGO_TARGET_DIR=${WRITE_BACKEND_TARGET_DIR}
            ${CARGO_EXECUTABLE} build --release --manifest-path "${WRITE_BACKEND_MANIFEST}"
    DEPENDS "${WRITE_BACKEND_MANIFEST}" "${CMAKE_CURRENT_SOURCE_DIR}/backend/src/main.rs"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/backend"
    COMMENT "Building Nexora Write Rust backend"
    VERBATIM)
add_custom_target(write-rust-backend ALL DEPENDS "${WRITE_BACKEND_BINARY}")

qt_standard_project_setup(REQUIRES 6.5)

qt_add_executable(write src/main.cpp)
set_target_properties(write PROPERTIES OUTPUT_NAME "${APP_ID}")

qt_add_qml_module(write
    URI Write
    VERSION 1.0
    QML_FILES
        qml/Main.qml
        qml/RailButton.qml
        qml/Editor.qml
        qml/LibraryView.qml
        qml/Reader.qml
    SOURCES
        src/theme.h src/theme.cpp
        src/files.h src/files.cpp
        src/rustbackend.h src/rustbackend.cpp
        src/highlighter.h src/highlighter.cpp
        src/mdxlrenderer.h src/mdxlrenderer.cpp
        src/epubbook.h src/epubbook.cpp
)

# The generated QML type registrations include the headers by name.
target_include_directories(write PRIVATE src)

target_compile_definitions(write PRIVATE
    APP_ID="${APP_ID}"
    APP_NAME="${APP_NAME}"
    APP_VERSION="${PROJECT_VERSION}"
    HELPER_DIR="${CMAKE_INSTALL_FULL_LIBDIR}/${APP_ID}")

target_link_libraries(write PRIVATE
    Qt6::Quick Qt6::QuickControls2 Qt6::WebEngineQuick
    KF6::SyntaxHighlighting LibArchive::LibArchive)

install(TARGETS write RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(PROGRAMS "${WRITE_BACKEND_BINARY}" DESTINATION ${CMAKE_INSTALL_LIBDIR}/${APP_ID})
install(PROGRAMS data/mdxl-render.py
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/${APP_ID} RENAME mdxl-render)
configure_file(data/write.desktop.in ${CMAKE_CURRENT_BINARY_DIR}/${APP_ID}.desktop @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/${APP_ID}.desktop
        DESTINATION ${CMAKE_INSTALL_DATADIR}/applications)
install(FILES data/write.svg
        DESTINATION ${CMAKE_INSTALL_DATADIR}/icons/hicolor/scalable/apps RENAME ${APP_ID}.svg)
