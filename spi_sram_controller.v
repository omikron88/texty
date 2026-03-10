// SPI SRAM controller with a simple asynchronous-SRAM-like user interface.
// Supports single-byte READ (0x03) and WRITE (0x02) with 24-bit address.

module spi_sram_controller #(
    parameter integer ADDR_WIDTH = 24,
    parameter integer CLK_DIV    = 4  // sysclk ticks per half SPI clock period
) (
    input  wire                  clk,
    input  wire                  reset_n,

    // SRAM-like user interface
    input  wire [ADDR_WIDTH-1:0] addr_in,
    input  wire [7:0]            data_in,
    output reg  [7:0]            data_out,
    input  wire                  read_in,
    input  wire                  write_in,
    output reg                   ready,

    // SPI interface (mode 0: CPOL=0, CPHA=0)
    output reg                   spi_cs_n,
    output reg                   spi_sck,
    output reg                   spi_mosi,
    input  wire                  spi_miso
);

    localparam [2:0]
        ST_IDLE         = 3'd0,
        ST_START_RW_CMD = 3'd1,
        ST_TRANSFER     = 3'd2,
        ST_FINISH       = 3'd3;

    localparam [1:0]
        OP_NONE  = 2'd0,
        OP_READ  = 2'd1,
        OP_WRITE = 2'd2;

    reg [2:0] state;
    reg [1:0] op;

    reg [ADDR_WIDTH-1:0] addr_latched;
    reg [7:0] data_latched;

    reg [39:0] tx_shift;
    reg [5:0]  bit_pos;      // 0..39
    reg [5:0]  bits_total;    // number of transmitted bits - 1 (7 or 39)
    reg [7:0]  rx_shift;

    reg [15:0] div_cnt;

    wire is_read_phase  = (op == OP_READ)  && (bits_total == 6'd39);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= ST_IDLE;
            op <= OP_NONE;
            addr_latched <= {ADDR_WIDTH{1'b0}};
            data_latched <= 8'h00;
            tx_shift <= 40'h0;
            bit_pos <= 6'd0;
            bits_total <= 6'd0;
            rx_shift <= 8'h00;
            div_cnt <= 16'd0;

            data_out <= 8'h00;
            ready <= 1'b1;

            spi_cs_n <= 1'b1;
            spi_sck <= 1'b0;
            spi_mosi <= 1'b0;
        end else begin
            case (state)
                ST_IDLE: begin
                    ready <= 1'b1;
                    spi_cs_n <= 1'b1;
                    spi_sck <= 1'b0;
                    spi_mosi <= 1'b0;
                    div_cnt <= CLK_DIV - 1;

                    if (write_in) begin
                        ready <= 1'b0;
                        op <= OP_WRITE;
                        addr_latched <= addr_in;
                        data_latched <= data_in;
                        state <= ST_START_RW_CMD;
                    end else if (read_in) begin
                        ready <= 1'b0;
                        op <= OP_READ;
                        addr_latched <= addr_in;
                        state <= ST_START_RW_CMD;
                    end
                end

                ST_START_RW_CMD: begin
                    // Full transaction: [CMD][A23..A0][DATA]
                    // READ  = 0x03, DATA byte is dummy and sampled from MISO.
                    // WRITE = 0x02, DATA byte is user payload from data_in.
                    spi_cs_n <= 1'b0;
                    spi_sck <= 1'b0;
                    tx_shift <= {
                        (op == OP_READ) ? 8'h03 : 8'h02,
                        addr_latched,
                        (op == OP_READ) ? 8'h00 : data_latched
                    };
                    bits_total <= 6'd39;
                    bit_pos <= 6'd39;
                    rx_shift <= 8'h00;
                    spi_mosi <= (op == OP_READ) ? 1'b0 : 1'b0; // tx_shift[39]
                    div_cnt <= CLK_DIV - 1;
                    state <= ST_TRANSFER;
                end

                ST_TRANSFER: begin
                    if (div_cnt != 0) begin
                        div_cnt <= div_cnt - 1'b1;
                    end else begin
                        div_cnt <= CLK_DIV - 1;

                        spi_sck <= ~spi_sck;

                        // Rising edge: sample MISO and advance bit counter.
                        if (!spi_sck) begin
                            if (is_read_phase && (bit_pos < 6'd8)) begin
                                rx_shift <= {rx_shift[6:0], spi_miso};
                            end

                            if (bit_pos == 0) begin
                                state <= ST_FINISH;
                            end else begin
                                bit_pos <= bit_pos - 1'b1;
                            end
                        end
                        // Falling edge: prepare next MOSI bit.
                        else begin
                            if (bit_pos > 0) begin
                                spi_mosi <= tx_shift[bit_pos - 1'b1];
                            end else begin
                                spi_mosi <= 1'b0;
                            end
                        end
                    end
                end

                ST_FINISH: begin
                    spi_cs_n <= 1'b1;
                    spi_sck <= 1'b0;
                    spi_mosi <= 1'b0;

                    // End of transfer handling.
                    if (op == OP_READ && bits_total == 6'd39) begin
                        data_out <= rx_shift;
                        ready <= 1'b1;
                        op <= OP_NONE;
                        state <= ST_IDLE;
                    end else begin
                        // Write command/data done.
                        ready <= 1'b1;
                        op <= OP_NONE;
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
