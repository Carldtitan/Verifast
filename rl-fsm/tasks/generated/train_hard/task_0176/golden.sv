module fsm_load (
    input  logic clk,
    input  logic rst,
    input  logic i0,
    input  logic i1,
    input  logic i2,
    output logic [1:0] o0,
    output logic o1
);
    typedef enum logic [1:0] { S0, S1, S2 } state_t;
    state_t state, next_state;
    always_comb begin
        next_state = state;
        case (state)
            S0: begin
                if (i0) next_state = S0;
                else if (i2) next_state = S0;
                else if (i1) next_state = S0;
                else next_state = S0;
            end
            S1: next_state = S1;
            S2: next_state = S1;
            default: next_state = state;
        endcase
    end
    always_comb begin
        o0 = '0;
        o1 = '0;
        case (state)
            S0: begin o0 = 2'd2; o1 = 1'd0; end
            S1: begin o0 = 2'd2; o1 = 1'd0; end
            S2: begin o0 = 2'd2; o1 = 1'd0; end
            default: begin o0 = '0; o1 = '0; end
        endcase
    end
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end
endmodule
