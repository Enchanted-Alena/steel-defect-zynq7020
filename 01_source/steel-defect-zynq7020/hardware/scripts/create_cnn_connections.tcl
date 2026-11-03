# Team-authored topology reconstruction using documented Vivado APIs.
# Board values are supplied locally, never embedded in this source file.
# Caller defines hardware $root, $board_inputs and normalized $board_effective.
create_bd_design cnn_system
create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0 DDR
create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
source [file join $root scripts apply_vendor_ps.tcl]
apply_vendor_ps $ps $board_inputs
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0
set_property CONFIG.c_include_sg 0 [get_bd_cells axi_dma_0]
create_bd_cell -type module -reference cnn_wrapper_dma_bridge cnn_wrapper_dma_brid_0
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 xlconstant_0
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc
set_property -dict {CONFIG.NUM_MI 2 CONFIG.NUM_SI 1} [get_bd_cells axi_smc]
foreach cell {axi_mem_intercon axi_mem_intercon_1} {
 create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 $cell
 set_property CONFIG.NUM_MI 1 [get_bd_cells $cell]
}
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 xlconcat_0
set_property CONFIG.NUM_PORTS 3 [get_bd_cells xlconcat_0]
foreach {a b} {
 processing_system7_0/M_AXI_GP0 axi_smc/S00_AXI
 axi_smc/M00_AXI axi_dma_0/S_AXI_LITE
 axi_smc/M01_AXI cnn_wrapper_dma_brid_0/s_axi_ctrl
 axi_dma_0/M_AXIS_MM2S cnn_wrapper_dma_brid_0/s_axis_job
 cnn_wrapper_dma_brid_0/m_axis_result axi_dma_0/S_AXIS_S2MM
 axi_dma_0/M_AXI_MM2S axi_mem_intercon/S00_AXI
 axi_mem_intercon/M00_AXI processing_system7_0/S_AXI_HP0
 axi_dma_0/M_AXI_S2MM axi_mem_intercon_1/S00_AXI
 axi_mem_intercon_1/M00_AXI processing_system7_0/S_AXI_HP1
} {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]}
foreach port {DDR FIXED_IO} {
 connect_bd_intf_net [get_bd_intf_ports $port] [get_bd_intf_pins processing_system7_0/$port]
}
foreach {a b} {
 cnn_wrapper_dma_brid_0/irq xlconcat_0/In0
 axi_dma_0/mm2s_introut xlconcat_0/In1
 axi_dma_0/s2mm_introut xlconcat_0/In2
 xlconcat_0/dout processing_system7_0/IRQ_F2P
 processing_system7_0/FCLK_RESET0_N proc_sys_reset_0/ext_reset_in
 xlconstant_0/dout proc_sys_reset_0/dcm_locked
} {connect_bd_net [get_bd_pins $a] [get_bd_pins $b]}
foreach pin {
 proc_sys_reset_0/slowest_sync_clk cnn_wrapper_dma_brid_0/aclk
 axi_dma_0/s_axi_lite_aclk axi_dma_0/m_axi_mm2s_aclk axi_dma_0/m_axi_s2mm_aclk
 processing_system7_0/M_AXI_GP0_ACLK processing_system7_0/S_AXI_HP0_ACLK processing_system7_0/S_AXI_HP1_ACLK
 axi_smc/aclk axi_mem_intercon/S00_ACLK axi_mem_intercon/M00_ACLK axi_mem_intercon/ACLK
 axi_mem_intercon_1/S00_ACLK axi_mem_intercon_1/M00_ACLK axi_mem_intercon_1/ACLK
} {connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins $pin]}
foreach pin {
 cnn_wrapper_dma_brid_0/aresetn axi_dma_0/axi_resetn axi_smc/aresetn
 axi_mem_intercon/S00_ARESETN axi_mem_intercon/M00_ARESETN axi_mem_intercon/ARESETN
 axi_mem_intercon_1/S00_ARESETN axi_mem_intercon_1/M00_ARESETN axi_mem_intercon_1/ARESETN
} {connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] [get_bd_pins $pin]}
foreach {space seg offset range} {
 processing_system7_0/Data axi_dma_0/S_AXI_LITE/Reg 0x40400000 0x00010000
 processing_system7_0/Data cnn_wrapper_dma_brid_0/s_axi_ctrl/reg0 0x40000000 0x00001000
 axi_dma_0/Data_MM2S processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM 0x00000000 0x20000000
 axi_dma_0/Data_S2MM processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM 0x00000000 0x20000000
} {assign_bd_address -offset $offset -range $range -target_address_space [get_bd_addr_spaces $space] [get_bd_addr_segs $seg] -force}
validate_bd_design
save_bd_design
