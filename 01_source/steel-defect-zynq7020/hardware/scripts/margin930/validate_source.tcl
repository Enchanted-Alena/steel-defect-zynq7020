# Optional source/BD validation using user-supplied HLS RTL. No synthesis/route.
if {[llength $argv] != 8} {error "Expected --hls-rtl DIR --board-inputs DIR --board-effective FILE --out NEW_DIR"}
array set args $argv
if {[version -short] ne "2025.2"} {error "Requires Vivado 2025.2"}
set root [file normalize [file join [file dirname [info script]] ../..]]
set out [file normalize $args(--out)]
set hls_rtl [file normalize $args(--hls-rtl)]
set board_inputs [file normalize $args(--board-inputs)]
set board_effective [file normalize $args(--board-effective)]
if {[file exists $out]} {error "Output must not exist"}
file mkdir $out
set reports [file join $out reports];file mkdir $reports
set source_validate_only 1
source [file join $root scripts margin930 create_source_project.tcl]
close_project
exit
