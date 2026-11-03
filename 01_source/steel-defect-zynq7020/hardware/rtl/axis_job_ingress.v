`timescale 1ns / 1ps

// One-packet AXI4-Stream ingress for protocol 2.0.
// A 32-bit beat is buffered, then serialized into up to four single-port RAM
// writes. The parent wrapper supplies checked section lengths and pulses arm.
module axis_job_ingress (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        arm,
    input  wire [31:0] cfg_weight_bytes,
    input  wire [31:0] cfg_bias_bytes,
    input  wire [31:0] cfg_mult_bytes,
    input  wire [31:0] cfg_shift_bytes,
    input  wire [31:0] cfg_input_bytes,
    input  wire        cfg_prevalidated,
    input  wire [31:0] cfg_expected_payload_bytes,
    output reg  [31:0] expected_input_bytes,
    output reg         packet_done,
    output reg  [12:0] error_status,

    input  wire [31:0] s_axis_job_tdata,
    input  wire [3:0]  s_axis_job_tkeep,
    input  wire        s_axis_job_tvalid,
    output wire        s_axis_job_tready,
    input  wire        s_axis_job_tlast,
    input  wire        s_axis_job_tuser,

    output reg         load_weights_we,
    output reg  [11:0] load_weights_addr,
    output reg  [7:0]  load_weights_data,
    output reg         load_bias_we,
    output reg  [3:0]  load_bias_addr,
    output reg  [31:0] load_bias_data,
    output reg         load_multipliers_we,
    output reg  [3:0]  load_multipliers_addr,
    output reg  [31:0] load_multipliers_data,
    output reg         load_shifts_we,
    output reg  [3:0]  load_shifts_addr,
    output reg  [5:0]  load_shifts_data,
    output reg         load_inputs_we,
    output reg  [14:0] load_inputs_addr,
    output reg  [7:0]  load_inputs_data
);
    localparam ST_IDLE = 3'd0, ST_WAIT = 3'd1, ST_BYTES = 3'd2,
               ST_DONE = 3'd3, ST_ERROR = 3'd4;
    localparam ERR_BAD_CONFIG = 0, ERR_EARLY_TLAST = 3,
               ERR_MISSING_TLAST = 4, ERR_TKEEP = 5,
               ERR_TUSER = 6, ERR_PADDING = 7, ERR_SHIFT_RANGE = 8;

    reg [2:0] state;
    reg [31:0] weight_bytes, bias_bytes, mult_bytes, shift_bytes, input_bytes;
    reg [31:0] bias_offset, mult_offset, shift_offset, input_offset;
    reg [31:0] beat_index;
    reg [31:0] beat_data;
    reg [1:0] lane;
    reg beat_last;

    function [31:0] align4;
        input [31:0] value;
        begin align4 = (value + 32'd3) & 32'hFFFFFFFC; end
    endfunction

    wire [31:0] next_bias_offset = align4(cfg_weight_bytes);
    wire [31:0] next_mult_offset = next_bias_offset + cfg_bias_bytes;
    wire [31:0] next_shift_offset = next_mult_offset + cfg_mult_bytes;
    wire [31:0] next_input_offset = next_shift_offset + align4(cfg_shift_bytes);
    wire [31:0] next_payload_bytes = next_input_offset + align4(cfg_input_bytes);
    wire [31:0] byte_index = (beat_index << 2) + {30'd0, lane};
    wire [7:0] lane_byte = beat_data[8*lane +: 8];
    wire in_weight = (byte_index < weight_bytes);
    wire in_bias = (byte_index >= bias_offset && byte_index < mult_offset);
    wire in_mult = (byte_index >= mult_offset && byte_index < shift_offset);
    wire in_shift = (byte_index >= shift_offset &&
                     byte_index < shift_offset + shift_bytes);
    wire in_input = (byte_index >= input_offset &&
                     byte_index < input_offset + input_bytes);
    wire in_padding = (byte_index < expected_input_bytes &&
                      !(in_weight || in_bias || in_mult || in_shift || in_input));
    wire shift_bad = in_shift && (lane_byte[7:6] != 2'b00 || lane_byte > 8'd62);

    assign s_axis_job_tready = (state == ST_WAIT);

    // One RAM write per accepted byte, one cycle at a time.
    always @* begin
        load_weights_we = 1'b0; load_weights_addr = 12'd0; load_weights_data = 8'd0;
        load_bias_we = 1'b0; load_bias_addr = 4'd0; load_bias_data = 32'd0;
        load_multipliers_we = 1'b0; load_multipliers_addr = 4'd0;
        load_multipliers_data = 32'd0;
        load_shifts_we = 1'b0; load_shifts_addr = 4'd0; load_shifts_data = 6'd0;
        load_inputs_we = 1'b0; load_inputs_addr = 15'd0; load_inputs_data = 8'd0;
        if (state == ST_BYTES && !shift_bad && !in_padding) begin
            if (in_weight) begin
                load_weights_we = 1'b1;
                load_weights_addr = byte_index[11:0];
                load_weights_data = lane_byte;
            end else if (in_bias && lane == 2'd0) begin
                load_bias_we = 1'b1;
                load_bias_addr = (byte_index - bias_offset) >> 2;
                load_bias_data = beat_data;
            end else if (in_mult && lane == 2'd0) begin
                load_multipliers_we = 1'b1;
                load_multipliers_addr = (byte_index - mult_offset) >> 2;
                load_multipliers_data = beat_data;
            end else if (in_shift) begin
                load_shifts_we = 1'b1;
                load_shifts_addr = (byte_index - shift_offset);
                load_shifts_data = lane_byte[5:0];
            end else if (in_input) begin
                load_inputs_we = 1'b1;
                load_inputs_addr = (byte_index - input_offset);
                load_inputs_data = lane_byte;
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            expected_input_bytes <= 32'd0;
            packet_done <= 1'b0;
            error_status <= 13'd0;
            weight_bytes <= 32'd0; bias_bytes <= 32'd0; mult_bytes <= 32'd0;
            shift_bytes <= 32'd0; input_bytes <= 32'd0;
            bias_offset <= 32'd0; mult_offset <= 32'd0;
            shift_offset <= 32'd0; input_offset <= 32'd0;
            beat_index <= 32'd0; beat_data <= 32'd0;
            lane <= 2'd0; beat_last <= 1'b0;
        end else begin
            packet_done <= 1'b0;
            if (arm) begin
                weight_bytes <= cfg_weight_bytes;
                bias_bytes <= cfg_bias_bytes;
                mult_bytes <= cfg_mult_bytes;
                shift_bytes <= cfg_shift_bytes;
                input_bytes <= cfg_input_bytes;
                bias_offset <= next_bias_offset;
                mult_offset <= next_mult_offset;
                shift_offset <= next_shift_offset;
                input_offset <= next_input_offset;
                expected_input_bytes <= cfg_prevalidated ?
                                        cfg_expected_payload_bytes : next_payload_bytes;
                error_status <= 13'd0;
                beat_index <= 32'd0;
                lane <= 2'd0;
                if (!cfg_prevalidated &&
                    (cfg_weight_bytes == 0 || cfg_weight_bytes > 2304 ||
                    cfg_bias_bytes == 0 || cfg_bias_bytes > 64 ||
                    cfg_mult_bytes != cfg_bias_bytes ||
                    cfg_shift_bytes == 0 || cfg_shift_bytes > 16 ||
                    cfg_bias_bytes != (cfg_shift_bytes << 2) ||
                    cfg_input_bytes == 0 || cfg_input_bytes > 32768 ||
                    next_payload_bytes <= next_input_offset)) begin
                    state <= ST_ERROR;
                    error_status[ERR_BAD_CONFIG] <= 1'b1;
                end else begin
                    state <= ST_WAIT;
                end
            end else begin
                case (state)
                    ST_WAIT: if (s_axis_job_tvalid && s_axis_job_tready) begin
                        if (s_axis_job_tkeep != 4'b1111) begin
                            error_status[ERR_TKEEP] <= 1'b1;
                            state <= ST_ERROR;
                        end else if (s_axis_job_tuser != 1'b0) begin
                            error_status[ERR_TUSER] <= 1'b1;
                            state <= ST_ERROR;
                        end else if (s_axis_job_tlast &&
                                     beat_index != (expected_input_bytes >> 2) - 1) begin
                            error_status[ERR_EARLY_TLAST] <= 1'b1;
                            state <= ST_ERROR;
                        end else if (!s_axis_job_tlast &&
                                     beat_index == (expected_input_bytes >> 2) - 1) begin
                            error_status[ERR_MISSING_TLAST] <= 1'b1;
                            state <= ST_ERROR;
                        end else begin
                            beat_data <= s_axis_job_tdata;
                            beat_last <= s_axis_job_tlast;
                            lane <= 2'd0;
                            state <= ST_BYTES;
                        end
                    end
                    ST_BYTES: begin
                        if (in_padding && lane_byte != 8'd0) begin
                            error_status[ERR_PADDING] <= 1'b1;
                            state <= ST_ERROR;
                        end else if (shift_bad) begin
                            error_status[ERR_SHIFT_RANGE] <= 1'b1;
                            state <= ST_ERROR;
                        end else if (lane == 2'd3) begin
                            if (beat_last) begin
                                packet_done <= 1'b1;
                                state <= ST_DONE;
                            end else begin
                                beat_index <= beat_index + 32'd1;
                                state <= ST_WAIT;
                            end
                        end else begin
                            lane <= lane + 2'd1;
                        end
                    end
                    default: state <= state;
                endcase
            end
        end
    end
endmodule
