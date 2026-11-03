# Source-project assembly derived from the historical build_system.tcl.
# Caller defines root (hardware source), out, reports and hls_rtl.
create_project smart_sl_cnn_dma [file join $out project] -part xc7z020clg484-1
set_property target_language Verilog [current_project]
add_files [glob -directory [file join $root rtl] *.v]
add_files [glob -directory $hls_rtl *.v]
update_compile_order -fileset sources_1
source [file join $board_inputs cnn_system_bd.tcl]
set ps [get_bd_cells processing_system7_0]
foreach {pin name} {UART_0 UART GPIO_0 PS_LED} {
 set before [get_bd_intf_ports]
 make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/$pin]
 foreach ext [get_bd_intf_ports] {if {[lsearch -exact $before $ext]<0} {set_property name $name $ext}}
}
create_bd_cell -type module -reference clock_heartbeat heartbeat
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins heartbeat/clk]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] [get_bd_pins heartbeat/reset_n]
create_bd_port -dir O LED_HEARTBEAT
connect_bd_net [get_bd_pins heartbeat/led] [get_bd_ports LED_HEARTBEAT]
validate_bd_design
save_bd_design
write_bd_tcl -force [file join $reports smart_sl_cnn_bd.tcl]
set cfg [open [file join $reports integrated_2025_2_effective.tsv] w]
puts $cfg "parameter\tvalue"
foreach key [lsort [list_property $ps]] {if {[string match CONFIG.* $key]} {puts $cfg "[string range $key 7 end]\t[get_property $key $ps]"}}
close $cfg
set ref [open $board_effective r]
gets $ref header
set diffs [open [file join $reports integration_parameter_differences.tsv] w]
puts $diffs "parameter\tvendor_2025_2\tintegrated_2025_2"
while {[gets $ref line]>=0} {
 set fields [split $line \t]
 set key [lindex $fields 0]
 set old [join [lrange $fields 1 end] \t]
 set new [get_property CONFIG.$key $ps]
 if {$old ne $new} {
  puts $diffs "$key\t$old\t$new"
  if {[regexp {^PCW_(UIPARAM_(ACT_)?DDR|DDR_|PACKAGE_DDR|MIO_|QSPI_|UART|ACT_UART|ACT_QSPI|CRYSTAL)} $key]} {error "Unexpected DDR/MIO/QSPI/UART/crystal difference: $key"}
 }
}
close $ref
close $diffs
puts "PASS: COMPLETE_DDR_MIO_QSPI_UART_CONFIGURATION_PRESERVED"
set bd [get_files */cnn_system.bd]
set_property synth_checkpoint_mode None $bd
if {[info exists source_validate_only] && $source_validate_only} {
 puts "BD_SOURCE_VALIDATION_ONLY_NO_SYNTHESIS_NO_IMPLEMENTATION"
 return
}
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top cnn_system_wrapper [get_filesets sources_1]
add_files -fileset constrs_1 [file join $root constraints smart_sl_basic.xdc]
update_compile_order -fileset sources_1
set f [open [file join $reports effective_config.txt] w]
foreach k {PCW_UIPARAM_DDR_PARTNO PCW_UIPARAM_DDR_BUS_WIDTH PCW_UIPARAM_DDR_FREQ_MHZ PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_UART0_UART0_IO PCW_USE_M_AXI_GP0 PCW_USE_S_AXI_HP0 PCW_USE_S_AXI_HP1} {puts $f "$k=[get_property CONFIG.$k $ps]"}
close $f
