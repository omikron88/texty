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

    localparam [1:0]
        GRANT_NONE = 2'd0,
        GRANT_CPU  = 2'd1,
        GRANT_VID  = 2'd2;

    reg [1:0] grant;
    reg cpu_read_prev;
    reg cpu_write_prev;
    reg vid_read_prev;

    reg                    cpu_req_pending;
    reg                    cpu_req_is_write;
    reg [ADDR_WIDTH-1:0]   cpu_addr_pending;
    reg [7:0]              cpu_wdata_pending;
    reg                    vid_req_pending;
    reg [ADDR_WIDTH-1:0]   vid_addr_pending;

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

            grant <= GRANT_NONE;
            cpu_read_prev <= 1'b0;
            cpu_write_prev <= 1'b0;
            vid_read_prev <= 1'b0;
            cpu_req_pending <= 1'b0;
            cpu_req_is_write <= 1'b0;
            cpu_addr_pending <= {ADDR_WIDTH{1'b0}};
            cpu_wdata_pending <= 8'h00;
            vid_req_pending <= 1'b0;
            vid_addr_pending <= {ADDR_WIDTH{1'b0}};
        end else begin
            cpu_ready <= 1'b0;
            vid_ready <= 1'b0;
            sdram_read_in <= 1'b0;
            sdram_write_in <= 1'b0;

            // Capture only request edges to avoid repeated accesses while strobe stays asserted.
            if (vid_read_in && !vid_read_prev) begin
                vid_req_pending <= 1'b1;
                vid_addr_pending <= vid_addr_in;
            end
            if (cpu_read_in && !cpu_read_prev) begin
                cpu_req_pending <= 1'b1;
                cpu_req_is_write <= 1'b0;
                cpu_addr_pending <= cpu_addr_in;
            end
            if (cpu_write_in && !cpu_write_prev) begin
                cpu_req_pending <= 1'b1;
                cpu_req_is_write <= 1'b1;
                cpu_addr_pending <= cpu_addr_in;
                cpu_wdata_pending <= cpu_data_in;
            end

            if (grant == GRANT_NONE) begin
                if (vid_req_pending) begin
                    grant <= GRANT_VID;
                    sdram_addr_in <= vid_addr_pending;
                    sdram_read_in <= 1'b1;
                    vid_req_pending <= 1'b0;
                end else if (cpu_req_pending) begin
                    grant <= GRANT_CPU;
                    sdram_addr_in <= cpu_addr_pending;
                    sdram_data_in <= cpu_wdata_pending;
                    sdram_read_in <= !cpu_req_is_write;
                    sdram_write_in <= cpu_req_is_write;
                    cpu_req_pending <= 1'b0;
                end
            end else if (sdram_ready) begin
                if (grant == GRANT_CPU) begin
                    cpu_data_out <= sdram_data_out;
                    cpu_ready <= 1'b1;
                end else if (grant == GRANT_VID) begin
                    vid_data_out <= sdram_data_out;
                    vid_ready <= 1'b1;
                end
                grant <= GRANT_NONE;
            end

            cpu_read_prev <= cpu_read_in;
            cpu_write_prev <= cpu_write_in;
            vid_read_prev <= vid_read_in;
        end
    end
endmodule
