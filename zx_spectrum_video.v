// VGA-style video generator for a ZX Spectrum 48K display window.
// Input pixels are ZX bitmap/attribute bytes supplied by an external line buffer.

module zx_spectrum_video (
    input  wire        clk_28mhz,
    input  wire        reset_n,

    output wire [12:0] bitmap_addr,
    output wire [12:0] attr_addr,
    input  wire [7:0]  bitmap_byte,
    input  wire [7:0]  attr_byte,

    input  wire [2:0]  border_color,

    output reg  [5:0]  rgb_r,
    output reg  [5:0]  rgb_g,
    output reg  [5:0]  rgb_b,
    output reg         hsync,
    output reg         vsync,
    output wire        frame_irq
);

    localparam integer H_ACTIVE = 640;
    localparam integer H_FRONT  = 16;
    localparam integer H_SYNC   = 96;
    localparam integer H_BACK   = 48;
    localparam integer H_TOTAL  = H_ACTIVE + H_FRONT + H_SYNC + H_BACK;

    localparam integer V_ACTIVE = 480;
    localparam integer V_FRONT  = 10;
    localparam integer V_SYNC   = 2;
    localparam integer V_BACK   = 33;
    localparam integer V_TOTAL  = V_ACTIVE + V_FRONT + V_SYNC + V_BACK;

    localparam integer ZX_LEFT = 64;
    localparam integer ZX_TOP  = 48;

    reg [9:0] hcnt;
    reg [9:0] vcnt;
    reg [4:0] frame_cnt;

    wire active_video = (hcnt < H_ACTIVE) && (vcnt < V_ACTIVE);
    wire in_zx_window = active_video &&
                        (hcnt >= ZX_LEFT) && (hcnt < ZX_LEFT + 512) &&
                        (vcnt >= ZX_TOP)  && (vcnt < ZX_TOP + 384);

    wire [7:0] zx_x = (hcnt - ZX_LEFT) >> 1;
    wire [7:0] zx_y = (vcnt - ZX_TOP) >> 1;
    wire [4:0] char_x = zx_x[7:3];
    wire [2:0] pixel_bit = 3'd7 - zx_x[2:0];

    assign bitmap_addr = {zx_y[7:6], zx_y[2:0], zx_y[5:3], char_x};
    assign attr_addr = 13'h1800 + {zx_y[7:3], char_x};
    wire pixel_on = bitmap_byte[pixel_bit];

    wire flash_phase = frame_cnt[4];
    wire flash = attr_byte[7] && flash_phase;
    wire bright = attr_byte[6];
    wire [2:0] paper = attr_byte[5:3];
    wire [2:0] ink = attr_byte[2:0];
    wire [2:0] zx_color = flash ? (pixel_on ? paper : ink) : (pixel_on ? ink : paper);
    wire [2:0] out_color = in_zx_window ? zx_color : border_color;
    wire out_bright = in_zx_window ? bright : 1'b0;

    assign frame_irq = (hcnt == 0) && (vcnt == V_ACTIVE + V_FRONT);

    function [5:0] expand_component;
        input component_on;
        input bright_on;
        begin
            if (!component_on) begin
                expand_component = 6'h00;
            end else if (bright_on) begin
                expand_component = 6'h3f;
            end else begin
                expand_component = 6'h2a;
            end
        end
    endfunction

    always @(posedge clk_28mhz or negedge reset_n) begin
        if (!reset_n) begin
            hcnt <= 10'd0;
            vcnt <= 10'd0;
            rgb_r <= 6'd0;
            rgb_g <= 6'd0;
            rgb_b <= 6'd0;
            hsync <= 1'b1;
            vsync <= 1'b1;
            frame_cnt <= 5'd0;
        end else begin
            if (hcnt == H_TOTAL - 1) begin
                hcnt <= 10'd0;
                if (vcnt == V_TOTAL - 1) begin
                    vcnt <= 10'd0;
                    frame_cnt <= frame_cnt + 5'd1;
                end else begin
                    vcnt <= vcnt + 10'd1;
                end
            end else begin
                hcnt <= hcnt + 10'd1;
            end

            hsync <= ~((hcnt >= H_ACTIVE + H_FRONT) && (hcnt < H_ACTIVE + H_FRONT + H_SYNC));
            vsync <= ~((vcnt >= V_ACTIVE + V_FRONT) && (vcnt < V_ACTIVE + V_FRONT + V_SYNC));

            if (active_video) begin
                rgb_r <= expand_component(out_color[1], out_bright);
                rgb_g <= expand_component(out_color[2], out_bright);
                rgb_b <= expand_component(out_color[0], out_bright);
            end else begin
                rgb_r <= 6'd0;
                rgb_g <= 6'd0;
                rgb_b <= 6'd0;
            end
        end
    end
endmodule
