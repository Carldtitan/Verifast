module mux4 (
    input  logic [7:0] d0,
    input  logic [7:0] d1,
    input  logic [7:0] d2,
    input  logic [7:0] d3,
    input  logic [1:0] sel,
    output logic [7:0] y
);
    always_comb begin
        unique case (sel)
            2'd0: y = d0;
            2'd1: y = d1;
            2'd2: y = d2;
            2'd3: y = d3;
            default: y = '0;
        endcase
    end
endmodule
