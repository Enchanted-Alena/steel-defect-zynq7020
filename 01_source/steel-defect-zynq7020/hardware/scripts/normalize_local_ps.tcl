# Team-authored local configuration import, no synthesis or implementation.
# argv: external board-input directory; new external output directory.
if {[llength $argv] != 2} {error "Expected BOARD_INPUTS NEW_OUTPUT"}
if {[version -short] ne "2025.2"} {error "Requires Vivado 2025.2"}
lassign $argv input out
if {[file exists $out]} {error "Output must not exist"}
file mkdir $out
create_project local_ps [file join $out project] -part xc7z020clg484-1
create_bd_design local_ps
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
set f [open [file join $input vendor_ps_parameters.tsv] r]
set settings {}; set count 0
while {[gets $f line] >= 0} {
 set fields [split $line \t]
 if {[llength $fields] != 2} {error "Invalid PS settings line"}
 lassign $fields key value
 if {[lsearch -exact [list_property $ps] CONFIG.$key] < 0} {error "Unavailable PS setting $key"}
 lappend settings CONFIG.$key $value
 incr count
}
close $f
if {$count != 355} {error "Unexpected reference parameter count"}
set_property -dict $settings $ps
set f [open [file join $out vendor_2025_2_effective.tsv] w]
puts $f "parameter\tvalue"
foreach key [lsort [list_property $ps]] {
 if {[string match CONFIG.* $key]} {puts $f "[string range $key 7 end]\t[get_property $key $ps]"}
}
close $f
puts "LOCAL_PS_NORMALIZATION_ONLY [version]"
close_project
exit
