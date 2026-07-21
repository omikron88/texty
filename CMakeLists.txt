cmake_minimum_required(VERSION 3.25)

project(texty_emulator LANGUAGES CXX)

option(TEXTY_BUILD_TESTS "Build deterministic core tests" ON)

add_library(texty_core
    src/core/floppy.cpp
    src/core/interrupt3214.cpp
    src/core/memory_map.cpp
    src/core/video.cpp
)
target_include_directories(texty_core PUBLIC src)
target_compile_features(texty_core PUBLIC cxx_std_20)
target_compile_options(texty_core PRIVATE -Wall -Wextra -Wpedantic -Werror)

if(TEXTY_BUILD_TESTS)
    enable_testing()
    add_executable(texty_core_tests tests/core_tests.cpp)
    target_link_libraries(texty_core_tests PRIVATE texty_core)
    target_compile_options(texty_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
    add_test(NAME texty_core_tests COMMAND texty_core_tests)
endif()
