cmake_minimum_required(VERSION 3.20)
project(video-sync-gui LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt6
find_package(Qt6 REQUIRED COMPONENTS Widgets)

# Use Corrosion to build Rust crates
include(FetchContent)
FetchContent_Declare(
    Corrosion
    GIT_REPOSITORY https://github.com/corrosion-rs/corrosion.git
    GIT_TAG v0.5
)
FetchContent_MakeAvailable(Corrosion)

# Import the Rust bridge crate
corrosion_import_crate(MANIFEST_PATH ../Cargo.toml CRATES vsg_bridge)

# Get the CXX generated header directory
set(CXX_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/corrosion_generated/crates/vsg_bridge/cxxbridge")

# =============================================================================
# Source files organized by component
# =============================================================================

# Main window
set(MAIN_WINDOW_SOURCES
    main_window/window.cpp
    main_window/controller.cpp
)

# Options dialog (settings)
set(OPTIONS_DIALOG_SOURCES
    options_dialog/ui.cpp
    options_dialog/logic.cpp
)

# Add job dialog
set(ADD_JOB_DIALOG_SOURCES
    add_job_dialog/ui.cpp
)

# Job queue dialog
set(JOB_QUEUE_DIALOG_SOURCES
    job_queue_dialog/ui.cpp
    job_queue_dialog/logic.cpp
)

# Track widget component
set(TRACK_WIDGET_SOURCES
    track_widget/ui.cpp
    track_widget/logic.cpp
)

# Manual selection dialog
set(MANUAL_SELECTION_DIALOG_SOURCES
    manual_selection_dialog/ui.cpp
    manual_selection_dialog/logic.cpp
)

# Track settings dialog
set(TRACK_SETTINGS_DIALOG_SOURCES
    track_settings_dialog/ui.cpp
    track_settings_dialog/logic.cpp
)

# =============================================================================
# All sources combined
# =============================================================================
set(SOURCES
    main.cpp
    ${MAIN_WINDOW_SOURCES}
    ${OPTIONS_DIALOG_SOURCES}
    ${ADD_JOB_DIALOG_SOURCES}
    ${JOB_QUEUE_DIALOG_SOURCES}
    ${TRACK_WIDGET_SOURCES}
    ${MANUAL_SELECTION_DIALOG_SOURCES}
    ${TRACK_SETTINGS_DIALOG_SOURCES}
)

# Create executable
add_executable(${PROJECT_NAME} ${SOURCES})

# Link libraries
target_link_libraries(${PROJECT_NAME}
    Qt6::Widgets
    vsg_bridge
)

# Include directories
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CXX_INCLUDE_DIR}
)

# CXX generates a crate header at build time
add_dependencies(${PROJECT_NAME} cargo-build_vsg_bridge)
