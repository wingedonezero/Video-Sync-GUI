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
# CXX generates headers during build, we need to find them
set(CXX_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/corrosion_generated/crates/vsg_bridge/cxxbridge")

# Main window sources
set(MAIN_WINDOW_SOURCES
    main_window/window.cpp
    main_window/controller.cpp
)

# All sources
set(SOURCES
    main.cpp
    ${MAIN_WINDOW_SOURCES}
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

# CXX generates a crate header, include it
# The header is generated at build time in the corrosion build dir
add_dependencies(${PROJECT_NAME} cargo-build_vsg_bridge)
