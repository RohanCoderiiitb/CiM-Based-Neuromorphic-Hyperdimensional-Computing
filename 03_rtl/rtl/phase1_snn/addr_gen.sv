// addr_gen.sv - block A. Combinational (no clock cycle): AER fields -> crossbar row address, NeuroHDC eq.19.
//   addr = p*256 + min(floor(16 y / H), 15)*16 + min(floor(16 x / W), 15)
// floor(16 c / W) is computed as (c * coord_mul_i) >> COORD_SHIFT, a reciprocal multiply, so ONE RTL covers
//   128x128 (mul = 128, i.e. c >> 3 exactly) and 34x34 (mul = 482, a true divide by 34, no divider).
module addr_gen
  import cim_neurohdc_pkg::*;
(
    input  logic [W_COORD-1:0]     x_i,
    input  logic [W_COORD-1:0]     y_i,
    input  logic                   p_i,
    input  logic [W_COORD_MUL-1:0] coord_mul_i,
    output logic [W_ADDR-1:0]      addr_o
);
  localparam int W_PROD = W_COORD + W_COORD_MUL;
  localparam logic [W_PROD-1:0] GRID_MAX = W_PROD'(GRID_DIM - 1);

  logic [W_PROD-1:0] x_prod, y_prod, x_cell, y_cell;
  logic [W_GRID-1:0] col, row;

  assign x_prod = W_PROD'(x_i) * W_PROD'(coord_mul_i);
  assign y_prod = W_PROD'(y_i) * W_PROD'(coord_mul_i);
  assign x_cell = x_prod >> COORD_SHIFT;
  assign y_cell = y_prod >> COORD_SHIFT;
  // clamp to the last grid cell, as the original events_to_frames does for out-of-range coordinates
  assign col    = (x_cell > GRID_MAX) ? W_GRID'(GRID_DIM - 1) : x_cell[W_GRID-1:0];
  assign row    = (y_cell > GRID_MAX) ? W_GRID'(GRID_DIM - 1) : y_cell[W_GRID-1:0];
  assign addr_o = {p_i, row, col};
endmodule
