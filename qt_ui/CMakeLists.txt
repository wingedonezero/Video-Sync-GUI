cmake_minimum_required(VERSION 3.20)
project(video-sync-gui LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt6
find_package(Qt6 REQUIRED COMPONENTS Widgets)

# =============================================================================
# Rust/CXX Bridge Integration
# =============================================================================
# These paths are passed from the vsg_app build.rs
# VSG_BRIDGE_LIB - path to libvsg_bridge.a
# VSG_CXXBRIDGE_DIR - path to generated CXX headers

if(DEFINED VSG_BRIDGE_LIB AND DEFINED VSG_CXXBRIDGE_DIR)
    message(STATUS "Rust bridge: ${VSG_BRIDGE_LIB}")
    message(STATUS "CXX headers: ${VSG_CXXBRIDGE_DIR}")
    set(USE_RUST_BRIDGE ON)
else()
    message(WARNING "Rust bridge not configured - building without vsg_core integration")
    set(USE_RUST_BRIDGE OFF)
endif()

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
)

# Include directories
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/bridge
)

# =============================================================================
# Rust Bridge Linking
# =============================================================================
if(USE_RUST_BRIDGE)
    # Add CXX include directory
    target_include_directories(${PROJECT_NAME} PRIVATE
        ${VSG_CXXBRIDGE_DIR}
        ${VSG_CXXBRIDGE_DIR}/vsg_bridge/src
    )

    # Link the Rust static library
    target_link_libraries(${PROJECT_NAME}
        ${VSG_BRIDGE_LIB}
    )

    # On Linux, Rust static libs need these system libraries
    if(UNIX AND NOT APPLE)
        target_link_libraries(${PROJECT_NAME}
            pthread
            dl
            m
        )
    endif()

    # Define macro so code knows bridge is available
    target_compile_definitions(${PROJECT_NAME} PRIVATE
        VSG_HAS_BRIDGE=1
    )
endif()
