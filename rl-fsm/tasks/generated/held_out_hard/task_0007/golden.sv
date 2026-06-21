module fsm_run (
    input  logic clk,
    input  logic rst,
    input  logic i0,
    output logic o0,
    output logic [1:0] o1
);
    typedef enum logic [2:0] { S0, S1, S2, S3, S4, S5, S6 } state_t;
    state_t state, next_state;
    always_comb begin
        next_state = state;
        case (state)
            S0: begin
                if (i0) next_state = S5;
                else if (i0) next_state = S2;
                else if (i0) next_state = S4;
                else next_state = S6;
            end
            S1: next_state = S5;
            S2: next_state = S3;
            S3: begin
                if (i0) next_state = S6;
                else next_state = S2;
            end
            S4: next_state = S0;
            S5: begin
                if (i0) next_state = S3;
                else if (i0) next_state = S6;
                else if (i0) next_state = S1;
                else next_state = S5;
            end
            S6: begin
                if (i0) next_state = S3;
                else if (i0) next_state = S1;
                else next_state = S0;
            end
            default: next_state = state;
        endcase
    end
    always_comb begin
        o0 = '0;
        o1 = '0;
        case (state)
            S0: begin o0 = 1'd0; o1 = 2'd1; end
            S1: begin o0 = 1'd1; o1 = 2'd2; end
            S2: begin o0 = 1'd0; o1 = 2'd2; end
            S3: begin o0 = 1'd0; o1 = 2'd0; end
            S4: begin o0 = 1'd1; o1 = 2'd1; end
            S5: begin o0 = 1'd0; o1 = 2'd0; end
            S6: begin o0 = 1'd0; o1 = 2'd1; end
            default: begin o0 = '0; o1 = '0; end
        endcase
    end
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end
endmodule
