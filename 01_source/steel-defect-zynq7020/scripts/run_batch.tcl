# Modified by B on 2026-11-01; notice added in R2 on 2026-11-02.
# Adds offline-demo ELF rejection before any board operation.
# Prepared only: called after fresh user connection/power confirmation.
if {[llength $argv] != 3} {puts stderr "Expected bit, ps7_init.tcl, ELF";exit 1}
lassign $argv bit init elf
# New user-model offline artifacts are never eligible for this board launcher.
# Inspect before connect/reset/program; do not print private ELF contents.
if {[file isfile $elf]} {
 set fd [open $elf rb];set elf_data [read $fd];close $fd
 set offline [expr {[string first {USER_MODEL_OFFLINE_BUILD_DO_NOT_PROGRAM} $elf_data]>=0 ||
                    [string first {USER_MODEL_OFFLINE_DEMO_NOT_BOARD_VALIDATED} $elf_data]>=0}]
 unset elf_data
 if {$offline || [file tail $elf] eq {user_model_offline_demo.elf}} {
  puts stderr "REFUSED: offline demo ELF is not authorized for board programming"
  exit 1
 }
}
proc require_stopped {} {
 if {[catch {stop} message]} {
  if {![string equal -nocase [string trim $message] "Already stopped"]} {error $message}
  puts "CPU_STOP_STATE_CONFIRMED=ALREADY_STOPPED"
 } else {puts "CPU_STOP_STATE_CONFIRMED=STOP_SUCCEEDED"}
}
proc phase {name body} {
 set start [clock clicks -milliseconds]
 uplevel 1 $body
 puts "JTAG_PHASE,$name,[expr {[clock clicks -milliseconds]-$start}]"
}
if {[catch {
 foreach p [list $bit $init $elf] {if {![file isfile $p]} {error "Missing input: $p"}}
 connect -url tcp:localhost:3121
 targets -set -filter {name =~ "ARM*#0"}
 catch {stop};rst -system;after 1000
 targets -set -filter {name =~ "ARM*#0"};catch {stop}
 targets -set -filter {name =~ "ARM*#1"};require_stopped;puts "CORE1_STOP_COMMAND_SUCCEEDED"
 targets -set -filter {name =~ "xc7z020"}
 phase FPGA_PROGRAM {fpga -file $bit}
 targets -set -filter {name =~ "ARM*#0"}
 phase PS_INITIALIZATION {source $init;ps7_init;ps7_post_config;rst -processor}
 set raw [lindex [mrd -value 0xF8000910] 0]
 puts "OCM_MAPPING_RAW_VALUE=$raw"
 if {[catch {expr {wide($raw)}} cfg] || ($cfg & 7) != 0} {error "Low OCM bank mapping preflight failed: $raw"}
 puts "OCM_MAPPING_PREFLIGHT_PASS=[format 0x%08X $cfg]"
 targets -set -filter {name =~ "ARM*#1"};require_stopped;puts "CORE1_STOP_AFTER_INIT_SUCCEEDED"
 targets -set -filter {name =~ "ARM*#0"}
 phase ELF_DOWNLOAD {dow $elf}
 phase PROCESSOR_RESUME {con}
 puts "LAUNCHED_SUITE=USER_SUPPLIED_ELF"
 disconnect
} problem]} {puts stderr "SUITE_LAUNCH_FAILED: $problem";exit 1}
exit
