// popcount.sv - balanced-tree population count of an N-bit vector (recursive halving).
// Used for the 512-bit active-row count `a` (block G) and the activity instrumentation.
module popcount #(
    parameter int N = 512,
    parameter int W = $clog2(N + 1)
) (
    input  logic [N-1:0] bits_i,
    output logic [W-1:0] count_o
);
  if (N == 1) begin : g_leaf
    assign count_o = bits_i[0];
  end else begin : g_split
    localparam int H = N / 2;
    localparam int WL = $clog2(H + 1);
    localparam int WH = $clog2(N - H + 1);
    logic [WL-1:0] lo_cnt;
    logic [WH-1:0] hi_cnt;
    popcount #(
        .N(H)
    ) u_lo (
        .bits_i (bits_i[H-1:0]),
        .count_o(lo_cnt)
    );
    popcount #(
        .N(N - H)
    ) u_hi (
        .bits_i (bits_i[N-1:H]),
        .count_o(hi_cnt)
    );
    assign count_o = W'(lo_cnt) + W'(hi_cnt);
  end
endmodule
