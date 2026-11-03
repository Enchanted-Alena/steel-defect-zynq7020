# Fresh-process audit of newly rebuilt DCP; only exports after all gates pass.
if {[llength $argv] != 4} {error "Expected --dcp FILE --out NEW_DIR"}
array set args $argv
foreach key {--dcp --out} {if {![info exists args($key)]} {error "Missing $key"}}
if {[version -short] ne "2025.2"} {error "Requires Vivado 2025.2"}
puts "ACTUAL_TOOL_VERSION [version]"
set dcp [file normalize $args(--dcp)]
set out [file normalize $args(--out)]
if {![file isfile $dcp]} {error "Missing restored checkpoint"}
if {[file exists $out]} {
 foreach child [glob -nocomplain -directory $out * .*] {
  if {[file tail $child] ni {. ..}} {error "Audit output must be a new empty directory"}
 }
}
file mkdir $out
source [file join [file dirname [info script]] clock_helpers.tcl]
open_checkpoint $dcp
if {[get_property PART [current_design]] ne "xc7z020clg484-1"} {error "Part mismatch"}
set c [get_clocks clk_fpga_0]
if {[llength [get_clocks]]!=1 || [llength $c]!=1} {error "Unexpected clock set"}
foreach {prop expected} {PERIOD 10.000 INPUT_JITTER 0.300} {
 if {abs([get_property $prop $c]-$expected)>0.00001} {error "Unexpected $prop"}
}
if {[get_property WAVEFORM $c] ne "0.000 5.000" ||
    [get_property SOURCE_PINS $c] ne {cnn_system_i/processing_system7_0/inst/PS7_i/FCLKCLK[0]}} {
 error "Formal clock source or waveform changed"
}
save_clock_model $out independently_reopened_100mhz
set timing_file [file join $out timing_summary.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file $timing_file
report_timing -max_paths 10 -file [file join $out top10_setup.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $out top10_hold.rpt]
report_utilization -file [file join $out utilization.rpt]
report_route_status -file [file join $out route_status.rpt]
report_high_fanout_nets -max_nets 100 -timing -file [file join $out high_fanout.rpt]
report_exceptions -file [file join $out exceptions.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -file [file join $out drc.rpt]
set errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]!=1 || [llength $hold]!=1} {error "Missing timed paths"}
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
# Read the first design-wide summary row, never a later clock/group subtotal.
set f [open $timing_file r];set content [read $f];close $f
set summary {}
set armed 0
foreach line [split $content \n] {
 if {[regexp {^\s*WNS\(ns\)\s+TNS\(ns\)} $line]} {set armed 1;continue}
 if {$armed && [regexp {^\s*[-+]?[0-9]+\.[0-9]+\s+[-+]?[0-9]+\.[0-9]+\s+[0-9]+\s+[0-9]+\s+[-+]?[0-9]+\.[0-9]+\s+[-+]?[0-9]+\.[0-9]+\s+[0-9]+\s+[0-9]+} $line]} {
  set summary [regexp -all -inline {\S+} $line];break
 }
}
if {[llength $summary]<8} {error "Cannot parse design-wide setup/hold summary"}
set tns [lindex $summary 1];set ths [lindex $summary 5]
set failed_setup [lindex $summary 2];set failed_hold [lindex $summary 6]
set f [open [file join $out audit_facts.tsv] w]
puts $f "key\tvalue"
foreach {key value} [list period_ns 10.000 wns_ns $wns whs_ns $whs tns_ns $tns ths_ns $ths failing_setup $failed_setup failing_hold $failed_hold drc_errors $errors] {
 puts $f "$key\t$value"
}
close $f
if {$wns<0.500 || $whs<0 || $tns!=0 || $ths!=0 || $failed_setup!=0 || $failed_hold!=0 || $errors!=0} {
 error "STOP: timing/hold/DRC gate failed; no bit or XSA exported"
}
# This operates on the independently reopened restored design, as in the
# historical export recipe. Artifact names alone never establish equivalence.
write_bitstream [file join $out cnn_system_wrapper.bit]
write_hw_platform -fixed -include_bit [file join $out margin930_rebuilt_100mhz.xsa]
puts "REBUILT_CANDIDATE_AUDIT_PASS_NOT_BOARD_MEASURED"
close_design
exit
