# Vendor V1.3B schematic + old PS DDR reference agree on these PL pins.
# Must be reviewed against the actual borrowed board before programming.
set_property -dict {PACKAGE_PIN L17 IOSTANDARD LVCMOS33} [get_ports UART_txd]
set_property -dict {PACKAGE_PIN M17 IOSTANDARD LVCMOS33} [get_ports UART_rxd]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports LED_HEARTBEAT]
set_property -dict {PACKAGE_PIN P21 IOSTANDARD LVCMOS33} [get_ports {PS_LED_tri_io[0]}]
# LED and UART are asynchronous board peripherals, not synchronous FPGA inputs.
set_false_path -from [get_ports UART_rxd]
set_false_path -to [get_ports UART_txd]
set_false_path -to [get_ports LED_HEARTBEAT]
set_false_path -from [get_ports {PS_LED_tri_io[0]}]
set_false_path -to [get_ports {PS_LED_tri_io[0]}]