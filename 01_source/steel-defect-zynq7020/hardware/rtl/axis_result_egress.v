`timescale 1ns / 1ps

// Protocol 2.0 output packer for a synchronous, one-cycle-read output RAM.
// start is pulsed only after successful HLS ap_done and core_active is low.
module axis_result_egress (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [31:0] output_bytes,
    output wire        busy,
    output reg         done,
    output wire        drain_ce,
    output wire [14:0] drain_addr,
    input  wire [7:0]  drain_q,
    output reg  [31:0] m_axis_result_tdata,
    output reg  [3:0]  m_axis_result_tkeep,
    output reg         m_axis_result_tvalid,
    input  wire        m_axis_result_tready,
    output reg         m_axis_result_tlast,
    output wire        m_axis_result_tuser
);
    localparam ST_IDLE = 2'd0, ST_REQUEST = 2'd1,
               ST_CAPTURE = 2'd2, ST_SEND = 2'd3;
    reg [1:0] state;
    reg [31:0] total_bytes;
    reg [31:0] byte_index;
    reg [1:0] lane;

    assign busy = (state != ST_IDLE);
    assign drain_ce = (state == ST_REQUEST);
    assign drain_addr = byte_index[14:0];
    assign m_axis_result_tuser = 1'b0;

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            total_bytes <= 32'd0;
            byte_index <= 32'd0;
            lane <= 2'd0;
            done <= 1'b0;
            m_axis_result_tdata <= 32'd0;
            m_axis_result_tkeep <= 4'd0;
            m_axis_result_tvalid <= 1'b0;
            m_axis_result_tlast <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                ST_IDLE: if (start && output_bytes != 0 && output_bytes <= 32768) begin
                    total_bytes <= output_bytes;
                    byte_index <= 32'd0;
                    lane <= 2'd0;
                    m_axis_result_tdata <= 32'd0;
                    m_axis_result_tkeep <= 4'd0;
                    m_axis_result_tlast <= 1'b0;
                    m_axis_result_tvalid <= 1'b0;
                    state <= ST_REQUEST;
                end
                // RAM samples address at this edge and updates drain_q.
                ST_REQUEST: state <= ST_CAPTURE;
                // Capture drain_q one edge later so the sync RAM value is valid.
                ST_CAPTURE: begin
                    m_axis_result_tdata[8*lane +: 8] <= drain_q;
                    m_axis_result_tkeep[lane] <= 1'b1;
                    if (lane == 2'd3 || byte_index == total_bytes - 1) begin
                        m_axis_result_tlast <= (byte_index == total_bytes - 1);
                        m_axis_result_tvalid <= 1'b1;
                        state <= ST_SEND;
                    end else begin
                        byte_index <= byte_index + 32'd1;
                        lane <= lane + 2'd1;
                        state <= ST_REQUEST;
                    end
                end
                ST_SEND: if (m_axis_result_tvalid && m_axis_result_tready) begin
                    m_axis_result_tvalid <= 1'b0;
                    if (m_axis_result_tlast) begin
                        done <= 1'b1;
                        state <= ST_IDLE;
                    end else begin
                        byte_index <= byte_index + 32'd1;
                        lane <= 2'd0;
                        m_axis_result_tdata <= 32'd0;
                        m_axis_result_tkeep <= 4'd0;
                        m_axis_result_tlast <= 1'b0;
                        state <= ST_REQUEST;
                    end
                end
            endcase
        end
    end
endmodule
