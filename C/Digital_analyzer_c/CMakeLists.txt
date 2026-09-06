# Set the minimum version of CMake that can be used
cmake_minimum_required(VERSION 3.20)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)
set(CMAKE_C_COMPILER_FORCED TRUE)
set(CMAKE_CXX_COMPILER_FORCED TRUE)

# Set target definition variables required by the toolchain file
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/target.cmake)

# Set the toolchain file for cross-compilation
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/gcc-arm-none-eabi.cmake)

# Project definition
project(Digital_analyzer_c)

# Enable CMake support for ASM and C/CPP languages
enable_language(C ASM)

set(PROJECT_NAME Digital_analyzer_c)

# Create an executable object type
add_executable(${PROJECT_NAME})

# Include additional CMake files for flags, components, and files
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/flags.cmake)
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/components.cmake)
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/files.cmake)

# Add sources to executable/library
target_sources(${PROJECT_NAME} PRIVATE
  # User defined sources
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/CMSIS/Device/ST/STM32F7xx/Source/Templates/system_stm32f7xx.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_cortex.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_gpio.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_pwr.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_pwr_ex.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_rcc.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Src/stm32f7xx_hal_rcc_ex.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Src/gpio_driver.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Src/drain_loop.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Src/uart_frame.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Src/cli.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/Src/spi_test.c"
)

# Add include directories
target_include_directories(${PROJECT_NAME} PRIVATE
  # User defined include directories
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/CMSIS/Include"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/CMSIS/Device/ST/STM32F7xx/Include"
  "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F7xx_HAL_Driver/Inc"
)

# Compiler options
target_compile_options(${PROJECT_NAME} PRIVATE
  # User defined compiler options
)

# Add additional defined symbols
target_compile_definitions(${PROJECT_NAME} PRIVATE
  # Add additional defined symbols here
  STM32F767xx
)

# Linker options
target_link_options(${PROJECT_NAME} PRIVATE 
  # User defined linker options
)

# Add additional linker search directories
target_link_directories(${PROJECT_NAME} PRIVATE
  # Add additional linker search directories here
)

# Add additional linker libraries
target_link_libraries(${PROJECT_NAME} PRIVATE
  # Add additional linker libraries here
)
