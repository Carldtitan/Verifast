module fsm_wait (
    input  logic clk,
    input  logic rst,
    input  logic i0,
    output logic [1:0] o0
);
    typedef enum logic [3:0] { S0, S1, S2, S3, S4, S5, S6, S7, S8 } state_t;
    state_t state, next_state;
    always_comb begin
        next_state = state;
        case (state)
            S0: begin
                if (i0) next_state = S4;
                else next_state = S7;
            end
            S1: begin
                if (i0) next_state = S7;
                else if (i0) next_state = S8;
                else next_state = S2;
            end
            S2: begin
                if (i0) next_state = S6;
                else if (i0) next_state = S6;
                else if (i0) next_state = S0;
                else next_state = S5;
            end
            S3: begin
                if (i0) next_state = S7;
                else if (i0) next_state = S4;
                else if (i0) next_state = S5;
                else next_state = S5;
            end
            S4: next_state = S8;
            S5: begin
                if (i0) next_state = S5;
                else if (i0) next_state = S7;
                else if (i0) next_state = S0;
                else next_state = S4;
            end
            S6: begin
                if (i0) next_state = S1;
                else if (i0) next_state = S5;
                else next_state = S3;
            end
            S7: begin
                if (i0) next_state = S2;
                else if (i0) next_state = S2;
                else if (i0) next_state = S0;
                else next_state = S5;
            end
            S8: begin
                if (i0) next_state = S4;
                else if (i0) next_state = S0;
                else next_state = S6;
            end
            default: next_state = state;
        endcase
    end
    always_comb begin
        o0 = '0;
        case (state)
            S0: begin o0 = 2'd1; end
            S1: begin o0 = 2'd1; end
            S2: begin o0 = 2'd0; end
            S3: begin o0 = 2'd0; end
            S4: begin o0 = 2'd3; end
            S5: begin o0 = 2'd0; end
            S6: begin o0 = 2'd3; end
            S7: begin o0 = 2'd3; end
            S8: begin o0 = 2'd2; end
            default: begin o0 = '0; end
        endcase
    end
    always_ff @(posedge clk) begin
        if (rst) state <= S0;
        else     state <= next_state;
    end
endmodule
