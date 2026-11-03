`timescale 1ns / 1ps

// Storage for one HLS read-only ap_memory array.
// LOADING: loader writes. CORE_BUSY: HLS reads, with one clock of latency.
module hls_input_ram #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 4,
    parameter DEPTH = 16
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  core_active,
    input  wire                  load_we,
    input  wire [ADDR_WIDTH-1:0] load_addr,
    input  wire [DATA_WIDTH-1:0] load_data,
    input  wire                  hls_ce,
    input  wire [ADDR_WIDTH-1:0] hls_addr,
    output reg  [DATA_WIDTH-1:0] hls_q
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // RAM contents are written by the loader; reset only clears the read register.
    always @(posedge clk) begin
        if (!rst_n) begin
            hls_q <= {DATA_WIDTH{1'b0}};
        end else if (core_active) begin
            if (hls_ce)
                hls_q <= mem[hls_addr];
        end else if (load_we) begin
            mem[load_addr] <= load_data;
        end
    end
endmodule

// Storage for the HLS 8-bit output array.
// CORE_BUSY: HLS writes when both CE and WE are high.
// DRAINING: the output packer reads, with one clock of latency.
module hls_output_ram #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 4,
    parameter DEPTH = 16
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  core_active,
    input  wire                  hls_ce,
    input  wire                  hls_we,
    input  wire [ADDR_WIDTH-1:0] hls_addr,
    input  wire [DATA_WIDTH-1:0] hls_data,
    input  wire                  drain_ce,
    input  wire [ADDR_WIDTH-1:0] drain_addr,
    output reg  [DATA_WIDTH-1:0] drain_q
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (!rst_n) begin
            drain_q <= {DATA_WIDTH{1'b0}};
        end else if (core_active) begin
            if (hls_ce && hls_we)
                mem[hls_addr] <= hls_data;
        end else if (drain_ce) begin
            drain_q <= mem[drain_addr];
        end
    end
endmodule
