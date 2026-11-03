proc save_clock_model {dir label} {
 file mkdir $dir
 set f [open [file join $dir ${label}_clocks.tsv] w]
 puts $f "clock\tproperty\tvalue"
 foreach c [get_clocks] {
  foreach p {PERIOD WAVEFORM SOURCE_PINS INPUT_JITTER SYSTEM_JITTER IS_GENERATED IS_PROPAGATED IS_VIRTUAL WEIGHT} {
   puts $f "$c\t$p\t[get_property $p $c]"
  }
 }
 close $f
 write_xdc -force -no_tool_comments -exclude_physical [file join $dir ${label}_timing.xdc]
}
proc set_analysis_period {new_period expected_period dir label} {
 set c [get_clocks clk_fpga_0]
 if {[llength [get_clocks]]!=1 || [llength $c]!=1} {error "Unexpected clock collection"}
 if {abs([get_property PERIOD $c]-$expected_period)>0.00001} {error "Unexpected input analysis period"}
 if {[get_property IS_GENERATED $c] || [get_property IS_VIRTUAL $c]} {error "Unexpected clock type"}
 set sources [get_property SOURCE_PINS $c]
 set sourcepins [get_pins $sources]
 if {[llength $sourcepins]!=1 || [get_property REF_PIN_NAME $sourcepins] ne {FCLKCLK[0]}} {error "Unexpected clock source pin"}
 set jitter [get_property INPUT_JITTER $c]
 if {abs($jitter-0.300)>0.00001} {error "Original PS7 input jitter differs from C0"}
 save_clock_model $dir ${label}_before
 create_clock -name clk_fpga_0 -period $new_period -waveform [list 0 [expr {$new_period/2.0}]] $sourcepins
 # Reapply the same existing jitter in case clock replacement cleared its attachment.
 set_input_jitter [get_clocks clk_fpga_0] $jitter
 set after [get_clocks clk_fpga_0]
 if {[get_property SOURCE_PINS $after] ne $sources || abs([get_property INPUT_JITTER $after]-$jitter)>0.00001 || abs([get_property PERIOD $after]-$new_period)>0.00001} {error "Clock replacement identity failed"}
 save_clock_model $dir ${label}_after
 puts "ANALYSIS_ONLY_PERIOD $expected_period -> $new_period; PS7/FCLK configuration not edited"
}
