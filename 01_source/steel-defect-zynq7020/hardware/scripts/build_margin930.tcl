# Portable source-based margin930 candidate. Prepared, not executed in this RC.
# Synthesis uses the PS-generated 10 ns clock. Only implementation analysis
# changes to 9.300 ns, after opening the NEW synthesis run and before opt_design.
if {[llength $argv] != 8} {error "Expected --hls-rtl DIR --board-inputs DIR --board-effective FILE --out NEW_DIR"}
array set args $argv
foreach key {--hls-rtl --board-inputs --board-effective --out} {if {![info exists args($key)]} {error "Missing $key"}}
if {[version -short] ne "2025.2"} {error "This recipe requires Vivado 2025.2"}
puts "ACTUAL_TOOL_VERSION [version]"
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file normalize $args(--out)]
set hls_rtl [file normalize $args(--hls-rtl)]
set board_inputs [file normalize $args(--board-inputs)]
set board_effective [file normalize $args(--board-effective)]
proc within {path base} {
 set p [file split [file normalize $path]]
 set b [file split [file normalize $base]]
 return [expr {[string equal -nocase [lrange $p 0 [expr {[llength $b]-1}]] $b]}]
}
if {[within $out [file dirname $root]] || [within $out $hls_rtl] || [within $hls_rtl $out]} {
 error "Use disjoint tree-external HLS and implementation output directories"
}
if {![file isfile [file join $hls_rtl int8_conv3x3.v]]} {error "Missing new HLS top RTL"}
if {[file exists $out]} {
 foreach child [glob -nocomplain -directory $out * .*] {
  if {[file tail $child] ni {. ..}} {error "Implementation output must be a new empty directory"}
 }
}
file mkdir $out
set reports [file join $out source_reports]
file mkdir $reports
source [file join $root scripts margin930 create_source_project.tcl]
if {abs([get_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $ps]-100.0)>0.00001} {
 error "PS FCLK must remain 100 MHz"
}
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
open_run synth_1
source [file join $root scripts margin930 clock_helpers.tcl]
set_analysis_period 9.300 10.000 [file join $out clock_target] temporary_target
# Performance_Explore stage directives from the accepted historical launcher.
# No seed change, fanout directive, bram_enable_opt, RTL or constraint exceptions.
opt_design -directive Explore
write_checkpoint [file join $out opted_930.dcp]
place_design -directive Explore
write_checkpoint [file join $out placed_930.dcp]
phys_opt_design -directive Explore
route_design -directive Explore
write_checkpoint [file join $out routed_930.dcp]
phys_opt_design
write_checkpoint [file join $out postroute_physopt_930.dcp]
report_timing_summary -report_unconstrained -file [file join $out experimental_930_timing.rpt]
set_analysis_period 10.000 9.300 [file join $out clock_restore] formal_restore
write_checkpoint [file join $out restored_100mhz.dcp]
puts "SOURCE_IMPL_FINISHED_INDEPENDENT_100MHZ_AUDIT_REQUIRED"
close_project
exit
