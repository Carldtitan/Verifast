// golden/seq_detect_101.sv
//
// Hand-written, known-correct behavioral oracle for examples/seq_detect_101.fsm.
// Overlapping "101" sequence detector: Moore output `y` is 1 only in the state
// reached after a "101" pattern completes, 0 otherwise.
//
// This is a behavioral oracle (Req 17.3): it is co-simulated against the
// transpiler output, so its port names/directions/widths match the generated
// module exactly (clk, rst implicit inputs; input x; output y). The module is
// three-always-block Moore style with synchronous active-high reset, an enum
// state encoding, full case + default (latch-free, Req 14.3) and is lint-clean
// under `verilator --lint-only -Wall` (Req 14.2).
module seq_detect_101 (
    input  logic clk,
    input  logic rst,
    input  logic x,
    output logic y
);

    typedef enum logic [1:0] { S0, S1, S2, S3 } state_t;
    state_t state, next_state;

    // Combinational next-state logic (blocking assignments only).
    always_comb begin
        next_state = state;
        case (state)
            S0: begin
                if (x) next_state = S1;
                else   next_state = S0;
            end
            S1: begin
                if (x) next_state = S1;
                else   next_state = S2;
            end
            S2: begin
                if (x) next_state = S3;
                else   next_state = S0;
            end
            S3: begin
                if (x) next_state = S1;
                else   next_state = S2;
            end
            default: next_state = state;
        endcase
    end

    // Combinational Moore output logic (function of state only).
    always_comb begin
        y = 1'b0;
        case (state)
            S0:      y = 1'b0;
            S1:      y = 1'b0;
            S2:      y = 1'b0;
            S3:      y = 1'b1;
            default: y = 1'b0;
        endcase
    end

    // Sequential state register with synchronous active-high reset.
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end

endmodule
