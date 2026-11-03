if {[catch {
 connect -url tcp:localhost:3121
 targets -set -filter {name =~ "ARM*#0"}
 mwr 0x40000000 2
 mwr 0x40400000 4
 foreach core {0 1} {
  targets -set -filter [format {name =~ "ARM*#%s"} $core]
  if {[catch {stop} message] && ![string equal -nocase [string trim $message] "Already stopped"]} {error $message}
  puts "FAILURE_STOP_CORE_$core=CONFIRMED"
 }
 puts "CNN_ABORT_AND_DMA_RESET_WRITES_ISSUED; completion of hardware reset not independently verified"
 disconnect
} problem]} {puts stderr "FAILURE_STOP_UNCONFIRMED: $problem";exit 1}
exit
