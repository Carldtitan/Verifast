module fsm_hold (
    input  logic clk,
    input  logic rst,
    input  logic i0,
    output logic [1:0] o0
);
    typedef enum logic [1:0] { S0, S1, S2 } state_t;
    state_t state, next_state;
    always_comb begin
        next_state = state;
        case (state)
            S0: next_state = S2;
            S1: begin
                if (i0) next_state = S0;
                else if (i0) next_state = S0;
                else if (i0) next_state = S2;
                else next_state = S2;
            end
            S2: begin
                if (i0) next_state = S2;
                else if (i0) next_state = S0;
                else if (i0) next_state = S0;
                else next_state = S1;
            end
            default: next_state = state;
        endcase
    end
    always_comb begin
        o0 = '0;
        case (state)
            S0: begin o0 = 2'd0; end
            S1: begin o0 = 2'd0; end
            S2: begin o0 = 2'd2; end
            default: begin o0 = '0; end
        endcase
    end
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end
endmodule
