// golden/traffic_light.sv
//
// Hand-written, known-correct behavioral oracle for examples/traffic_light.fsm.
// Three-phase light that advances one phase per `tick`. Each state drives a
// distinct 2-bit code on `light` (Moore output): RED=0, GREEN=1, YELLOW=2.
//
// This is a behavioral oracle (Req 17.3): port names/directions/widths match
// the generated module exactly (clk, rst implicit inputs; input tick; output
// [1:0] light). Three-always-block Moore style, synchronous active-high reset,
// enum state encoding, full case + default (latch-free, Req 14.3), lint-clean
// under `verilator --lint-only -Wall` (Req 14.2).
module traffic_light (
    input  logic       clk,
    input  logic       rst,
    input  logic       tick,
    output logic [1:0] light
);

    typedef enum logic [1:0] { RED, GREEN, YELLOW } state_t;
    state_t state, next_state;

    // Combinational next-state logic (blocking assignments only).
    always_comb begin
        next_state = state;
        case (state)
            RED: begin
                if (tick) next_state = GREEN;
                else      next_state = RED;
            end
            GREEN: begin
                if (tick) next_state = YELLOW;
                else      next_state = GREEN;
            end
            YELLOW: begin
                if (tick) next_state = RED;
                else      next_state = YELLOW;
            end
            default: next_state = state;
        endcase
    end

    // Combinational Moore output logic (function of state only).
    always_comb begin
        light = 2'd0;
        case (state)
            RED:     light = 2'd0;
            GREEN:   light = 2'd1;
            YELLOW:  light = 2'd2;
            default: light = 2'd0;
        endcase
    end

    // Sequential state register with synchronous active-high reset.
    always_ff @(posedge clk) begin
        if (rst) state <= RED;
        else     state <= next_state;
    end

endmodule
