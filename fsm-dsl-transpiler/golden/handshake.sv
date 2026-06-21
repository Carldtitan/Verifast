// golden/handshake.sv
//
// Hand-written, known-correct behavioral oracle for examples/handshake.fsm.
// Three-state req/ack/busy controller. Moore outputs:
//   IDLE: busy=0, ack=0   (wait for req)
//   BUSY: busy=1, ack=0   (one cycle of work)
//   DONE: busy=0, ack=1   (hold ack until req drops)
//
// This is a behavioral oracle (Req 17.3): port names/directions/widths match
// the generated module exactly (clk, rst implicit inputs; input req; output
// busy; output ack). Three-always-block Moore style, synchronous active-high
// reset, enum state encoding, full case + default (latch-free, Req 14.3),
// lint-clean under `verilator --lint-only -Wall` (Req 14.2).
module handshake (
    input  logic clk,
    input  logic rst,
    input  logic req,
    output logic busy,
    output logic ack
);

    typedef enum logic [1:0] { IDLE, BUSY, DONE } state_t;
    state_t state, next_state;

    // Combinational next-state logic (blocking assignments only).
    always_comb begin
        next_state = state;
        case (state)
            IDLE: begin
                if (req) next_state = BUSY;
                else     next_state = IDLE;
            end
            BUSY: begin
                next_state = DONE;
            end
            DONE: begin
                if (req) next_state = DONE;
                else     next_state = IDLE;
            end
            default: next_state = state;
        endcase
    end

    // Combinational Moore output logic (function of state only).
    always_comb begin
        busy = 1'b0;
        ack  = 1'b0;
        case (state)
            IDLE:    begin busy = 1'b0; ack = 1'b0; end
            BUSY:    begin busy = 1'b1; ack = 1'b0; end
            DONE:    begin busy = 1'b0; ack = 1'b1; end
            default: begin busy = 1'b0; ack = 1'b0; end
        endcase
    end

    // Sequential state register with synchronous active-high reset.
    always_ff @(posedge clk) begin
        if (rst) state <= IDLE;
        else     state <= next_state;
    end

endmodule
