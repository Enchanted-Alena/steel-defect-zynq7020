proc apply_vendor_ps {ps board_inputs} {
 set in [open [file join $board_inputs vendor_ps_parameters.tsv] r]
 set settings {}
 set available [list_property $ps]
 while {[gets $in line]>=0} {
  set fields [split $line \t]
  set key [lindex $fields 0]
  set value [join [lrange $fields 1 end] \t]
  if {[lsearch -exact $available CONFIG.$key]<0} {error "Vendor parameter unavailable: $key"}
  lappend settings CONFIG.$key $value
 }
 close $in
 set_property -dict $settings $ps
 # Integration changes only: 100 MHz FCLK0, GP0/HP0/HP1, IRQ_F2P and one EMIO LED.
 # UART, DDR, MIO and QSPI settings stay inherited from the official UART reference.
 set_property -dict [list \
 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
 CONFIG.PCW_EN_CLK0_PORT {1} CONFIG.PCW_EN_RST0_PORT {1} \
 CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_HP1 {1} \
 CONFIG.PCW_USE_FABRIC_INTERRUPT {1} CONFIG.PCW_IRQ_F2P_INTR {1} \
 CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE {1} CONFIG.PCW_GPIO_EMIO_GPIO_IO {1}] $ps
}
