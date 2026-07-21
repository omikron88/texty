cmake_minimum_required(VERSION 3.25)

project(fk1_emulator LANGUAGES CXX)

option(FK1_BUILD_TESTS "Build deterministic core tests" ON)

add_library(fk1_core
    src/core/floppy.cpp
    src/core/interrupt3214.cpp
    src/core/memory_map.cpp
    src/core/video.cpp
)
target_include_directories(fk1_core PUBLIC src)
target_compile_features(fk1_core PUBLIC cxx_std_20)
target_compile_options(fk1_core PRIVATE -Wall -Wextra -Wpedantic -Werror)

if(FK1_BUILD_TESTS)
    enable_testing()
    add_executable(fk1_core_tests tests/core_tests.cpp)
    target_link_libraries(fk1_core_tests PRIVATE fk1_core)
    target_compile_options(fk1_core_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
    add_test(NAME fk1_core_tests COMMAND fk1_core_tests)
endif()
