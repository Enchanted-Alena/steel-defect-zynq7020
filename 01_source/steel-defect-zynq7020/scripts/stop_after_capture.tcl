connect -url tcp:localhost:3121
foreach core {0 1} {
 targets -set -filter "name =~ \"ARM*#$core\""
 if {[catch {stop} message]} {
  if {![string equal -nocase [string trim $message] "Already stopped"]} {puts stderr $message;exit 1}
 }
 puts "CAPTURE_CORE${core}_STOP_CONFIRMED"
}
disconnect
exit
