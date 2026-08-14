cmake_minimum_required(VERSION 3.8)
project(odi_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(action_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/MissionState.msg"
  "msg/BehaviorState.msg"
  "msg/DetectedObject.msg"
  "msg/DetectedObjectArray.msg"
  "msg/CuriosityDecision.msg"
  "msg/SemanticLabel.msg"
  "msg/EncounterResult.msg"
  "msg/ObservationResult.msg"

  "srv/EvaluateCuriosity.srv"

  "action/ObserveObject.action"
  "action/Explore.action"
  "action/FirstEncounter.action"
  "action/ReturnHome.action"

  DEPENDENCIES
  std_msgs
  geometry_msgs
  builtin_interfaces
  action_msgs
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
