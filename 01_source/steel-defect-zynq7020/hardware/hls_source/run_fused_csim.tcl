set script_dir [file normalize [file dirname [info script]]]
set project_dir [file join $script_dir build_fused_csim_2025_2]

open_project -reset $project_dir
set_top int8_conv3x3
add_files [file join $script_dir int8_conv3x3.cpp]
add_files -tb [file join $script_dir test_fused_postop.cpp]
open_solution -reset solution1
set_part {xc7z020-clg484-1}
create_clock -period 8.0 -name default
csim_design -clean
close_project
exit
