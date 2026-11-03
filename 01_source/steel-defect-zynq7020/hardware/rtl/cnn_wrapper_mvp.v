`timescale 1ns / 1ps

// Protocol 2.0, TM=2 / effective TN=1 integration top.
module cnn_wrapper_mvp (
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
    input  wire        s_axis_job_tuser,
    output wire [31:0] m_axis_result_tdata,
    output wire [3:0]  m_axis_result_tkeep,
    output wire        m_axis_result_tvalid,
    input  wire        m_axis_result_tready,
    output wire        m_axis_result_tlast,
    output wire        m_axis_result_tuser,
    output wire        irq
);
    localparam IDLE=4'd0, ARMED=4'd1, LOADING=4'd2,
               CORE_START=4'd3, CORE_BUSY=4'd4,
               DRAINING=4'd5, ERROR=4'd6;
    reg [3:0] state;
    reg done_sticky;
    reg [12:0] error_status;
    reg [31:0] core_return;
    wire [31:0] cfg_batch, cfg_input_channels, cfg_output_channels;
    wire [31:0] cfg_height, cfg_width, cfg_padding, cfg_zero_point, cfg_post_op;
    wire [31:0] cfg_watchdog_limit;
    wire [1:0] irq_enable;
    wire cmd_start, cmd_abort, cmd_clear_done, cmd_clear_error;
    wire cfg_write_busy, cfg_updated, bad_command;
    wire [12:0] error_w1c_mask;

    // Pipeline shape arithmetic. AXI reads of EXPECTED_* wait until these
    // registered lengths reflect the most recent configuration write.
    wire [5:0] h_calc = cfg_height[5:0] +
                        {4'd0, cfg_padding[0], 1'b0} - 6'd2;
    wire [5:0] w_calc = cfg_width[5:0] +
                        {4'd0, cfg_padding[0], 1'b0} - 6'd2;
    wire [11:0] conv_area_calc = h_calc * w_calc;
    wire config_valid =
        cfg_batch >= 1 && cfg_batch <= 2 &&
        cfg_input_channels >= 1 && cfg_input_channels <= 16 &&
        cfg_output_channels >= 1 && cfg_output_channels <= 16 &&
        cfg_height >= 1 && cfg_height <= 32 &&
        cfg_width >= 1 && cfg_width <= 32 &&
        cfg_padding <= 1 &&
        ((cfg_padding == 1) || cfg_height >= 3) &&
        ((cfg_padding == 1) || cfg_width >= 3) &&
        cfg_zero_point[31:8] == {24{cfg_zero_point[7]}} &&
        cfg_post_op <= 2 &&
        ((cfg_post_op == 0) || (cfg_zero_point == 0)) &&
        ((cfg_post_op != 2) || (!h_calc[0] && !w_calc[0]));
    reg [11:0] p1_input_hw, p1_output_hw;
    reg [9:0] p1_cin_cout;
    reg [4:0] p1_cin, p1_cout;
    reg [1:0] p1_batch;
    reg p1_valid;
    reg [16:0] p2_input_chw, p2_output_chw;
    reg [11:0] p2_weight;
    reg [4:0] p2_cout;
    reg [1:0] p2_batch;
    reg p2_valid;
    reg [15:0] p3_input, p3_output;
    reg [11:0] p3_weight;
    reg [6:0] p3_bias;
    reg [4:0] p3_shift;
    reg p3_valid;
    reg [15:0] p4_prefix, p4_input, p4_output;
    reg [11:0] p4_weight;
    reg [6:0] p4_bias;
    reg [4:0] p4_shift;
    reg p4_valid;
    reg [15:0] computed_payload, computed_output;
    reg computed_valid;
    reg [5:0] calc_busy;
    wire lengths_ready = (calc_busy == 0);
    wire [31:0] expected_input_bytes = computed_valid ?
                                       {16'd0, computed_payload} : 32'd0;
    wire [31:0] expected_output_bytes = computed_valid ?
                                        {16'd0, computed_output} : 32'd0;
    wire [31:0] weight_bytes = {20'd0, p4_weight};
    wire [31:0] bias_bytes = {25'd0, p4_bias};
    wire [31:0] mult_bytes = bias_bytes;
    wire [31:0] shift_bytes = {27'd0, p4_shift};
    wire [31:0] input_bytes = {16'd0, p4_input};

    always @(posedge aclk) begin
        if (!aresetn) begin
            p1_input_hw <= 0; p1_output_hw <= 0; p1_cin_cout <= 0;
            p1_cin <= 0; p1_cout <= 0; p1_batch <= 0; p1_valid <= 0;
            p2_input_chw <= 0; p2_output_chw <= 0; p2_weight <= 0;
            p2_cout <= 0; p2_batch <= 0; p2_valid <= 0;
            p3_input <= 0; p3_output <= 0; p3_weight <= 0;
            p3_bias <= 0; p3_shift <= 0; p3_valid <= 0;
            p4_prefix <= 0; p4_input <= 0; p4_output <= 0;
            p4_weight <= 0; p4_bias <= 0; p4_shift <= 0; p4_valid <= 0;
            computed_payload <= 0; computed_output <= 0;
            computed_valid <= 0; calc_busy <= 0;
        end else begin
            if (cfg_updated) calc_busy <= 6'b111111;
            else calc_busy <= {1'b0, calc_busy[5:1]};
            p1_input_hw <= cfg_height[5:0] * cfg_width[5:0];
            p1_output_hw <= (cfg_post_op == 2) ?
                            (conv_area_calc >> 2) : conv_area_calc;
            p1_cin_cout <= cfg_input_channels[4:0] * cfg_output_channels[4:0];
            p1_cin <= cfg_input_channels[4:0];
            p1_cout <= cfg_output_channels[4:0];
            p1_batch <= cfg_batch[1:0];
            p1_valid <= config_valid;
            p2_input_chw <= p1_input_hw * p1_cin;
            p2_output_chw <= p1_output_hw * p1_cout;
            p2_weight <= p1_cin_cout * 4'd9;
            p2_cout <= p1_cout;
            p2_batch <= p1_batch;
            p2_valid <= p1_valid;
            p3_input <= p2_input_chw * p2_batch;
            p3_output <= p2_output_chw * p2_batch;
            p3_weight <= p2_weight;
            p3_bias <= {p2_cout, 2'b00};
            p3_shift <= p2_cout;
            p3_valid <= p2_valid;
            p4_prefix <= (({4'd0, p3_weight} + 16'd3) & 16'hFFFC) +
                         {8'd0, p3_bias, 1'b0} +
                         (({11'd0, p3_shift} + 16'd3) & 16'hFFFC);
            p4_input <= p3_input;
            p4_output <= p3_output;
            p4_weight <= p3_weight;
            p4_bias <= p3_bias;
            p4_shift <= p3_shift;
            p4_valid <= p3_valid;
            computed_payload <= p4_prefix +
                                ((p4_input + 16'd3) & 16'hFFFC);
            computed_output <= p4_output;
            computed_valid <= p4_valid;
        end
    end

    reg [31:0] job_batch, job_cin, job_cout, job_h, job_w, job_pad, job_post_op;
    reg [7:0] job_zp;
    reg [31:0] job_output_bytes, job_watchdog_limit;
    wire start_valid = cmd_start && state == IDLE && computed_valid && lengths_ready;
    wire core_active = (state == CORE_START || state == CORE_BUSY);
    wire ap_start = (state == CORE_START);
    wire ap_done, ap_idle, ap_ready;
    wire [31:0] ap_return;
    wire [14:0] inputs_address0, outputs_address0, accumulators_address0;
    wire inputs_ce0, outputs_ce0, outputs_we0;
    wire accumulators_ce0, accumulators_we0;
    wire [7:0] inputs_q0, outputs_d0;
    wire [31:0] accumulators_d0;
    wire [11:0] weights_address0;
    wire weights_ce0;
    wire [7:0] weights_q0;
    wire [3:0] bias_address0, multipliers_address0, shifts_address0;
    wire bias_ce0, multipliers_ce0, shifts_ce0;
    wire [31:0] bias_q0, multipliers_q0;
    wire [5:0] shifts_q0;

    wire load_inputs_we, load_weights_we, load_bias_we;
    wire load_multipliers_we, load_shifts_we;
    wire [14:0] load_inputs_addr;
    wire [11:0] load_weights_addr;
    wire [3:0] load_bias_addr, load_multipliers_addr, load_shifts_addr;
    wire [7:0] load_inputs_data, load_weights_data;
    wire [31:0] load_bias_data, load_multipliers_data;
    wire [5:0] load_shifts_data;
    wire [31:0] ingress_expected_bytes;
    wire ingress_done;
    wire [12:0] ingress_error;
    wire ingress_ready;
    wire egress_done, egress_busy;
    wire [14:0] drain_addr;
    wire drain_ce;
    wire [7:0] drain_q;
    wire [31:0] accumulator_write_count;
    wire [31:0] egress_data;
    wire [3:0] egress_keep;
    wire egress_valid, egress_last, egress_user;
    wire input_handshake = s_axis_job_tvalid && s_axis_job_tready;
    wire output_handshake = m_axis_result_tvalid && m_axis_result_tready;

    reg [63:0] cycle_counter;
    // Preserve the exact modulo-2^64 timestamp difference, but keep its
    // increment in a register instead of subtracting two timestamps on
    // watchdog/cancel/stream-control paths. After a valid START edge:
    // cycle_counter - live_start + 1 == 3 (live_start captures old counter-1).
    reg [63:0] live_elapsed;
    reg watchdog_expired;
    reg [63:0] live_last_out_elapsed;
    reg [63:0] live_start, live_first_in, live_last_in;
    reg [63:0] live_core_done, live_first_out, live_last_out;
    reg [63:0] live_input_stalls, live_output_stalls;
    reg [63:0] snap_start, snap_first_in, snap_last_in;
    reg [63:0] snap_core_done, snap_first_out, snap_last_out;
    reg [63:0] snap_input_stalls, snap_output_stalls, snap_active;
    reg first_in_seen, first_out_seen;
    wire watchdog_hit = (state != IDLE && state != ERROR &&
                          job_watchdog_limit != 0 &&
                          watchdog_expired);
    wire cancel_path = cmd_abort || state == ERROR || watchdog_hit;
    wire path_rst_n = aresetn && !cancel_path;
    wire [12:0] error_set =
        {bad_command, cmd_abort, watchdog_hit,
         (state == CORE_BUSY && ap_done && ap_return != 0),
         ((state == ARMED || state == LOADING) ? ingress_error[8:3] : 6'd0),
         cfg_write_busy, (cmd_start && state != IDLE),
         (cmd_start && state == IDLE && (!computed_valid || !lengths_ready))};
    wire clear_allowed = (state == IDLE || state == ERROR);
    wire [12:0] clear_mask = clear_allowed ?
        (cmd_clear_error ? 13'h1FFF : error_w1c_mask) : 13'd0;
    wire [12:0] next_errors = (error_status & ~clear_mask) | error_set;

    assign s_axis_job_tready = ingress_ready &&
                               (state == ARMED || state == LOADING) && !cancel_path;
    assign m_axis_result_tdata = egress_data;
    assign m_axis_result_tkeep = egress_keep;
    assign m_axis_result_tvalid = egress_valid && state == DRAINING && !cancel_path;
    assign m_axis_result_tlast = egress_last;
    assign m_axis_result_tuser = egress_user;

    axi_lite_ctrl ctrl (
        .clk(aclk), .rst_n(aresetn),
        .s_axi_awaddr(s_axi_ctrl_awaddr), .s_axi_awvalid(s_axi_ctrl_awvalid),
        .s_axi_awready(s_axi_ctrl_awready),
        .s_axi_wdata(s_axi_ctrl_wdata), .s_axi_wstrb(s_axi_ctrl_wstrb),
        .s_axi_wvalid(s_axi_ctrl_wvalid), .s_axi_wready(s_axi_ctrl_wready),
        .s_axi_bresp(s_axi_ctrl_bresp), .s_axi_bvalid(s_axi_ctrl_bvalid),
        .s_axi_bready(s_axi_ctrl_bready),
        .s_axi_araddr(s_axi_ctrl_araddr), .s_axi_arvalid(s_axi_ctrl_arvalid),
        .s_axi_arready(s_axi_ctrl_arready),
        .s_axi_rdata(s_axi_ctrl_rdata), .s_axi_rresp(s_axi_ctrl_rresp),
        .s_axi_rvalid(s_axi_ctrl_rvalid), .s_axi_rready(s_axi_ctrl_rready),
        .current_state(state), .done_sticky(done_sticky),
        .error_status(error_status),
        .expected_input_bytes(expected_input_bytes),
        .expected_output_bytes(expected_output_bytes),
        .lengths_ready(lengths_ready), .core_return(core_return),
        .start_cycle(snap_start), .first_in_cycle(snap_first_in),
        .last_in_cycle(snap_last_in), .core_done_cycle(snap_core_done),
        .first_out_cycle(snap_first_out), .last_out_cycle(snap_last_out),
        .input_stall_cycles(snap_input_stalls),
        .output_stall_cycles(snap_output_stalls), .active_cycles(snap_active),
        .irq(irq), .cfg_batch(cfg_batch),
        .cfg_input_channels(cfg_input_channels),
        .cfg_output_channels(cfg_output_channels),
        .cfg_height(cfg_height), .cfg_width(cfg_width),
        .cfg_padding(cfg_padding), .cfg_zero_point(cfg_zero_point),
        .cfg_post_op(cfg_post_op),
        .cfg_watchdog_limit(cfg_watchdog_limit), .irq_enable(irq_enable),
        .cmd_start(cmd_start), .cmd_abort(cmd_abort),
        .cmd_clear_done(cmd_clear_done), .cmd_clear_error(cmd_clear_error),
        .cfg_write_busy(cfg_write_busy), .cfg_updated(cfg_updated),
        .bad_command(bad_command),
        .error_w1c_mask(error_w1c_mask)
    );

    axis_job_ingress ingress (
        .clk(aclk), .rst_n(path_rst_n), .arm(start_valid),
        .cfg_weight_bytes(weight_bytes), .cfg_bias_bytes(bias_bytes),
        .cfg_mult_bytes(mult_bytes), .cfg_shift_bytes(shift_bytes),
        .cfg_input_bytes(input_bytes), .cfg_prevalidated(1'b1),
        .cfg_expected_payload_bytes(expected_input_bytes),
        .expected_input_bytes(ingress_expected_bytes),
        .packet_done(ingress_done), .error_status(ingress_error),
        .s_axis_job_tdata(s_axis_job_tdata), .s_axis_job_tkeep(s_axis_job_tkeep),
        .s_axis_job_tvalid(s_axis_job_tvalid &&
                           (state == ARMED || state == LOADING)),
        .s_axis_job_tready(ingress_ready),
        .s_axis_job_tlast(s_axis_job_tlast), .s_axis_job_tuser(s_axis_job_tuser),
        .load_weights_we(load_weights_we), .load_weights_addr(load_weights_addr),
        .load_weights_data(load_weights_data),
        .load_bias_we(load_bias_we), .load_bias_addr(load_bias_addr),
        .load_bias_data(load_bias_data),
        .load_multipliers_we(load_multipliers_we),
        .load_multipliers_addr(load_multipliers_addr),
        .load_multipliers_data(load_multipliers_data),
        .load_shifts_we(load_shifts_we), .load_shifts_addr(load_shifts_addr),
        .load_shifts_data(load_shifts_data),
        .load_inputs_we(load_inputs_we), .load_inputs_addr(load_inputs_addr),
        .load_inputs_data(load_inputs_data)
    );

    int8_conv3x3 core (
        .ap_clk(aclk), .ap_rst(!path_rst_n), .ap_start(ap_start),
        .ap_done(ap_done), .ap_idle(ap_idle), .ap_ready(ap_ready),
        .inputs_address0(inputs_address0), .inputs_ce0(inputs_ce0), .inputs_q0(inputs_q0),
        .weights_address0(weights_address0), .weights_ce0(weights_ce0), .weights_q0(weights_q0),
        .bias_address0(bias_address0), .bias_ce0(bias_ce0), .bias_q0(bias_q0),
        .multipliers_address0(multipliers_address0), .multipliers_ce0(multipliers_ce0),
        .multipliers_q0(multipliers_q0),
        .shifts_address0(shifts_address0), .shifts_ce0(shifts_ce0), .shifts_q0(shifts_q0),
        .outputs_address0(outputs_address0), .outputs_ce0(outputs_ce0),
        .outputs_we0(outputs_we0), .outputs_d0(outputs_d0),
        .accumulators_address0(accumulators_address0),
        .accumulators_ce0(accumulators_ce0), .accumulators_we0(accumulators_we0),
        .accumulators_d0(accumulators_d0),
        .batch(job_batch), .input_channels(job_cin),
        .output_channels(job_cout), .height(job_h), .width(job_w),
        .padding(job_pad), .zero_point(job_zp), .post_op(job_post_op),
        .ap_return(ap_return)
    );

    hls_memory_bank bank (
        .clk(aclk), .rst_n(aresetn), .core_active(core_active),
        .load_inputs_we(load_inputs_we), .load_inputs_addr(load_inputs_addr),
        .load_inputs_data(load_inputs_data),
        .load_weights_we(load_weights_we), .load_weights_addr(load_weights_addr),
        .load_weights_data(load_weights_data),
        .load_bias_we(load_bias_we), .load_bias_addr(load_bias_addr),
        .load_bias_data(load_bias_data),
        .load_multipliers_we(load_multipliers_we),
        .load_multipliers_addr(load_multipliers_addr),
        .load_multipliers_data(load_multipliers_data),
        .load_shifts_we(load_shifts_we), .load_shifts_addr(load_shifts_addr),
        .load_shifts_data(load_shifts_data),
        .inputs_address0(inputs_address0), .inputs_ce0(inputs_ce0), .inputs_q0(inputs_q0),
        .weights_address0(weights_address0), .weights_ce0(weights_ce0), .weights_q0(weights_q0),
        .bias_address0(bias_address0), .bias_ce0(bias_ce0), .bias_q0(bias_q0),
        .multipliers_address0(multipliers_address0), .multipliers_ce0(multipliers_ce0),
        .multipliers_q0(multipliers_q0),
        .shifts_address0(shifts_address0), .shifts_ce0(shifts_ce0), .shifts_q0(shifts_q0),
        .outputs_address0(outputs_address0), .outputs_ce0(outputs_ce0),
        .outputs_we0(outputs_we0), .outputs_d0(outputs_d0),
        .drain_ce(drain_ce), .drain_addr(drain_addr), .drain_q(drain_q),
        .accumulators_ce0(accumulators_ce0), .accumulators_we0(accumulators_we0),
        .accumulator_write_count(accumulator_write_count)
    );

    axis_result_egress egress (
        .clk(aclk), .rst_n(path_rst_n),
        .start(state == CORE_BUSY && ap_done && ap_return == 0),
        .output_bytes(job_output_bytes), .busy(egress_busy), .done(egress_done),
        .drain_ce(drain_ce), .drain_addr(drain_addr), .drain_q(drain_q),
        .m_axis_result_tdata(egress_data), .m_axis_result_tkeep(egress_keep),
        .m_axis_result_tvalid(egress_valid),
        .m_axis_result_tready(m_axis_result_tready &&
                              state == DRAINING && !cancel_path),
        .m_axis_result_tlast(egress_last), .m_axis_result_tuser(egress_user)
    );

    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= IDLE; done_sticky <= 0; error_status <= 0;
            core_return <= 0; cycle_counter <= 0;
            live_elapsed <= 64'd1; live_last_out_elapsed <= 0; watchdog_expired <= 1;
            job_batch <= 0; job_cin <= 0; job_cout <= 0;
            job_h <= 0; job_w <= 0; job_pad <= 0; job_zp <= 0;
            job_post_op <= 0;
            job_output_bytes <= 0; job_watchdog_limit <= 0;
            live_start <= 0; live_first_in <= 0; live_last_in <= 0;
            live_core_done <= 0; live_first_out <= 0; live_last_out <= 0;
            live_input_stalls <= 0; live_output_stalls <= 0;
            snap_start <= 0; snap_first_in <= 0; snap_last_in <= 0;
            snap_core_done <= 0; snap_first_out <= 0; snap_last_out <= 0;
            snap_input_stalls <= 0; snap_output_stalls <= 0;
            snap_active <= 0; first_in_seen <= 0; first_out_seen <= 0;
        end else begin
            cycle_counter <= cycle_counter + 64'd1;
            if (start_valid && !cmd_abort) begin
                live_elapsed <= 64'd3;
                watchdog_expired <= (64'd3 >= {32'd0, cfg_watchdog_limit});
            end else begin
                live_elapsed <= live_elapsed + 64'd1;
                watchdog_expired <= ((live_elapsed + 64'd1) >= {32'd0, job_watchdog_limit});
            end
            error_status <= next_errors;
            if (cmd_clear_done) done_sticky <= 0;
            if (state == ARMED || state == LOADING) begin
                if (!input_handshake) live_input_stalls <= live_input_stalls + 64'd1;
                if (input_handshake && !first_in_seen) begin
                    live_first_in <= cycle_counter;
                    first_in_seen <= 1;
                end
                if (input_handshake && s_axis_job_tlast)
                    live_last_in <= cycle_counter;
            end
            if (state == CORE_BUSY && ap_done) begin
                live_core_done <= cycle_counter;
                core_return <= ap_return;
            end
            if (state == DRAINING) begin
                if (m_axis_result_tvalid && !m_axis_result_tready)
                    live_output_stalls <= live_output_stalls + 64'd1;
                if (output_handshake && !first_out_seen) begin
                    live_first_out <= cycle_counter;
                    first_out_seen <= 1;
                end
                if (output_handshake && m_axis_result_tlast) begin
                    live_last_out <= cycle_counter;
                    live_last_out_elapsed <= live_elapsed;
                end
            end
            if (cmd_abort) begin
                state <= IDLE;
                snap_start <= live_start;
                snap_first_in <= live_first_in; snap_last_in <= live_last_in;
                snap_core_done <= live_core_done;
                snap_first_out <= live_first_out; snap_last_out <= live_last_out;
                snap_input_stalls <= live_input_stalls;
                snap_output_stalls <= live_output_stalls;
                snap_active <= live_elapsed;
            end else if (watchdog_hit ||
                         ((state == ARMED || state == LOADING) && |ingress_error) ||
                         (state == CORE_BUSY && ap_done && ap_return != 0)) begin
                state <= ERROR;
                snap_start <= live_start;
                snap_first_in <= live_first_in; snap_last_in <= live_last_in;
                snap_core_done <= live_core_done;
                snap_first_out <= live_first_out; snap_last_out <= live_last_out;
                snap_input_stalls <= live_input_stalls;
                snap_output_stalls <= live_output_stalls;
                snap_active <= live_elapsed;
            end else case (state)
                IDLE: if (cmd_start) begin
                    if (computed_valid && lengths_ready) begin
                        job_batch <= cfg_batch; job_cin <= cfg_input_channels;
                        job_cout <= cfg_output_channels; job_h <= cfg_height;
                        job_w <= cfg_width; job_pad <= cfg_padding;
                        job_zp <= cfg_zero_point[7:0];
                        job_post_op <= cfg_post_op;
                        job_output_bytes <= expected_output_bytes;
                        job_watchdog_limit <= cfg_watchdog_limit;
                        live_start <= cycle_counter - 64'd1;
                        live_last_out_elapsed <= 0;
                        live_first_in <= 0; live_last_in <= 0;
                        live_core_done <= 0; live_first_out <= 0; live_last_out <= 0;
                        live_input_stalls <= 0; live_output_stalls <= 0;
                        first_in_seen <= 0; first_out_seen <= 0;
                        state <= ARMED;
                    end else state <= ERROR;
                end
                ARMED: if (input_handshake) state <= LOADING;
                LOADING: if (ingress_done) state <= CORE_START;
                CORE_START: state <= CORE_BUSY;
                CORE_BUSY: if (ap_done && ap_return == 0) state <= DRAINING;
                DRAINING: if (egress_done) begin
                    state <= IDLE;
                    done_sticky <= 1;
                    snap_start <= live_start;
                    snap_first_in <= live_first_in; snap_last_in <= live_last_in;
                    snap_core_done <= live_core_done;
                    snap_first_out <= live_first_out; snap_last_out <= live_last_out;
                    snap_input_stalls <= live_input_stalls;
                    snap_output_stalls <= live_output_stalls;
                    snap_active <= live_last_out_elapsed;
                end
                ERROR: if ((cmd_clear_error || error_w1c_mask != 0) &&
                           next_errors == 0) state <= IDLE;
                default: state <= ERROR;
            endcase
        end
    end
endmodule



