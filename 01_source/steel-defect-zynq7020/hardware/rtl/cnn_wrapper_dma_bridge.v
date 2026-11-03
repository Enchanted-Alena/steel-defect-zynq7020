`timescale 1ns / 1ps

// System integration bridge for AXI DMA, whose AXI4-Stream ports have no TUSER.
// Protocol 2.0 reserves TUSER=0. Keep cnn_wrapper_mvp unchanged.
module cnn_wrapper_dma_bridge (
    input  wire        aclk,
    input  wire        aresetn,

    input  wire [11:0] s_axi_ctrl_awaddr,
    input  wire        s_axi_ctrl_awvalid,
    output wire        s_axi_ctrl_awready,
    input  wire [31:0] s_axi_ctrl_wdata,
    input  wire [3:0]  s_axi_ctrl_wstrb,
    input  wire        s_axi_ctrl_wvalid,
    output wire        s_axi_ctrl_wready,
    output wire [1:0]  s_axi_ctrl_bresp,
    output wire        s_axi_ctrl_bvalid,
    input  wire        s_axi_ctrl_bready,
    input  wire [11:0] s_axi_ctrl_araddr,
    input  wire        s_axi_ctrl_arvalid,
    output wire        s_axi_ctrl_arready,
    output wire [31:0] s_axi_ctrl_rdata,
    output wire [1:0]  s_axi_ctrl_rresp,
    output wire        s_axi_ctrl_rvalid,
    input  wire        s_axi_ctrl_rready,

    input  wire [31:0] s_axis_job_tdata,
    input  wire [3:0]  s_axis_job_tkeep,
    input  wire        s_axis_job_tvalid,
    output wire        s_axis_job_tready,
    input  wire        s_axis_job_tlast,

    output wire [31:0] m_axis_result_tdata,
    output wire [3:0]  m_axis_result_tkeep,
    output wire        m_axis_result_tvalid,
    input  wire        m_axis_result_tready,
    output wire        m_axis_result_tlast,

    output wire        irq
);
    wire unused_result_tuser;

    cnn_wrapper_mvp u_wrapper (
        .aclk(aclk),
        .aresetn(aresetn),
        .s_axi_ctrl_awaddr(s_axi_ctrl_awaddr),
        .s_axi_ctrl_awvalid(s_axi_ctrl_awvalid),
        .s_axi_ctrl_awready(s_axi_ctrl_awready),
        .s_axi_ctrl_wdata(s_axi_ctrl_wdata),
        .s_axi_ctrl_wstrb(s_axi_ctrl_wstrb),
        .s_axi_ctrl_wvalid(s_axi_ctrl_wvalid),
        .s_axi_ctrl_wready(s_axi_ctrl_wready),
        .s_axi_ctrl_bresp(s_axi_ctrl_bresp),
        .s_axi_ctrl_bvalid(s_axi_ctrl_bvalid),
        .s_axi_ctrl_bready(s_axi_ctrl_bready),
        .s_axi_ctrl_araddr(s_axi_ctrl_araddr),
        .s_axi_ctrl_arvalid(s_axi_ctrl_arvalid),
        .s_axi_ctrl_arready(s_axi_ctrl_arready),
        .s_axi_ctrl_rdata(s_axi_ctrl_rdata),
        .s_axi_ctrl_rresp(s_axi_ctrl_rresp),
        .s_axi_ctrl_rvalid(s_axi_ctrl_rvalid),
        .s_axi_ctrl_rready(s_axi_ctrl_rready),
        .s_axis_job_tdata(s_axis_job_tdata),
        .s_axis_job_tkeep(s_axis_job_tkeep),
        .s_axis_job_tvalid(s_axis_job_tvalid),
        .s_axis_job_tready(s_axis_job_tready),
        .s_axis_job_tlast(s_axis_job_tlast),
        .s_axis_job_tuser(1'b0),
        .m_axis_result_tdata(m_axis_result_tdata),
        .m_axis_result_tkeep(m_axis_result_tkeep),
        .m_axis_result_tvalid(m_axis_result_tvalid),
        .m_axis_result_tready(m_axis_result_tready),
        .m_axis_result_tlast(m_axis_result_tlast),
        .m_axis_result_tuser(unused_result_tuser),
        .irq(irq)
    );
endmodule
