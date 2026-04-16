// SDRAM manager: arbitrates between CPU (read/write) and video (read-only) ports.
// Uses a single-port SDRAM controller with SRAM-like handshake.

module sdram_manager #(
    parameter integer ADDR_WIDTH = 23
) (
    input  wire                  clk,
    input  wire                  reset_n,

    // CPU full-access port
    input  wire [ADDR_WIDTH-1:0] cpu_addr_in,
    input  wire [7:0]            cpu_data_in,
    output reg  [7:0]            cpu_data_out,
    input  wire                  cpu_read_in,
    input  wire                  cpu_write_in,
    output reg                   cpu_ready,

    // Video read-only port
    input  wire [ADDR_WIDTH-1:0] vid_addr_in,
    output reg  [7:0]            vid_data_out,
    input  wire                  vid_read_in,
    output reg                   vid_ready,

    // SDRAM controller interface
    output reg  [ADDR_WIDTH-1:0] sdram_addr_in,
    output reg  [7:0]            sdram_data_in,
    input  wire [7:0]            sdram_data_out,
    output reg                   sdram_read_in,
    output reg                   sdram_write_in,
    input  wire                  sdram_ready
);

    localparam [2:0]
        ST_IDLE            = 3'd0,
        ST_CPU_WAIT        = 3'd1,
        ST_VID_WAIT        = 3'd2,
        ST_PREFETCH_WAIT   = 3'd3;

    reg [2:0] state;
    reg [ADDR_WIDTH-1:0] vid_addr_pending;

    // Cache one 16-bit word (two neighboring bytes differing in A0).
    reg [ADDR_WIDTH-2:0] pair_word_addr;
    reg [7:0]            pair_byte_lo;
    reg [7:0]            pair_byte_hi;
    reg                  pair_valid;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            sdram_addr_in  <= {ADDR_WIDTH{1'b0}};
            sdram_data_in  <= 8'h00;
            sdram_read_in  <= 1'b0;
            sdram_write_in <= 1'b0;

            cpu_data_out <= 8'h00;
            cpu_ready <= 1'b0;
            vid_data_out <= 8'h00;
            vid_ready <= 1'b0;

            state <= ST_IDLE;
            vid_addr_pending <= {ADDR_WIDTH{1'b0}};
            pair_word_addr <= {(ADDR_WIDTH-1){1'b0}};
            pair_byte_lo <= 8'h00;
            pair_byte_hi <= 8'h00;
            pair_valid <= 1'b0;
        end else begin
            cpu_ready <= 1'b0;
            vid_ready <= 1'b0;
            sdram_read_in <= 1'b0;
            sdram_write_in <= 1'b0;

            case (state)
                ST_IDLE: begin
                    // Video port has priority.
                    if (vid_read_in) begin
                        // Hit in cached pair (same word address, pick byte by A0).
                        if (pair_valid && (pair_word_addr == vid_addr_in[ADDR_WIDTH-1:1])) begin
                            vid_data_out <= vid_addr_in[0] ? pair_byte_hi : pair_byte_lo;
                            vid_ready <= 1'b1;
                        end else begin
                            // Miss: read requested byte now, then prefetch sibling byte.
                            vid_addr_pending <= vid_addr_in;
                            sdram_addr_in <= vid_addr_in;
                            sdram_read_in <= 1'b1;
                            state <= ST_VID_WAIT;
                        end
                    end else if (cpu_read_in || cpu_write_in) begin
                        if (cpu_write_in) begin
                            // Keep coherency simple: invalidate cached pair on any CPU write.
                            pair_valid <= 1'b0;
                        end
                        sdram_addr_in <= cpu_addr_in;
                        sdram_data_in <= cpu_data_in;
                        sdram_read_in <= cpu_read_in;
                        sdram_write_in <= cpu_write_in;
                        state <= ST_CPU_WAIT;
                    end
                end

                ST_CPU_WAIT: begin
                    if (sdram_ready) begin
                        cpu_data_out <= sdram_data_out;
                        cpu_ready <= 1'b1;
                        state <= ST_IDLE;
                    end
                end

                ST_VID_WAIT: begin
                    if (sdram_ready) begin
                        // Return requested byte.
                        vid_data_out <= sdram_data_out;
                        vid_ready <= 1'b1;

                        // Store first byte to pair cache.
                        pair_word_addr <= vid_addr_pending[ADDR_WIDTH-1:1];
                        if (vid_addr_pending[0]) begin
                            pair_byte_hi <= sdram_data_out;
                        end else begin
                            pair_byte_lo <= sdram_data_out;
                        end

                        // Prefetch sibling byte immediately.
                        sdram_addr_in <= {vid_addr_pending[ADDR_WIDTH-1:1], ~vid_addr_pending[0]};
                        sdram_read_in <= 1'b1;
                        state <= ST_PREFETCH_WAIT;
                    end
                end

                ST_PREFETCH_WAIT: begin
                    if (sdram_ready) begin
                        // Fill second byte and mark cache valid.
                        if (vid_addr_pending[0]) begin
                            pair_byte_lo <= sdram_data_out;
                        end else begin
                            pair_byte_hi <= sdram_data_out;
                        end
                        pair_valid <= 1'b1;
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end
            end
        end
    end
endmodule
