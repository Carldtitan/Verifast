module fsm_lock (
    input  logic clk,
    input  logic rst,
    input  logic i0,
    input  logic i1,
    output logic o0
);
    typedef enum logic [1:0] { S0, S1, S2 } state_t;
    state_t state, next_state;
    always_comb begin
        next_state = state;
        case (state)
            S0: next_state = S2;
            S1: next_state = S2;
            S2: begin
                if (i0) next_state = S0;
                else next_state = S2;
            end
            default: next_state = state;
        endcase
    end
    always_comb begin
        o0 = '0;
        case (state)
            S0: begin o0 = 1'd0; end
            S1: begin o0 = 1'd1; end
            S2: begin o0 = 1'd1; end
            default: begin o0 = '0; end
        endcase
    end
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end
    // inputs not read at full width are legal (fixed interface / reserved / partial-bit use);
    // this intentional whole-signal read keeps lint -Wall clean (UNUSEDSIGNAL).
    wire _unused_ok = &{1'b0, i1};
endmodule
