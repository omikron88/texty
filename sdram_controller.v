// SDRAM controller for IS42S16320D-7
// User interface: 8-bit SRAM-like access with ready handshake.

module sdram_controller (
    input  wire        clk,
    input  wire        reset_n,

    input  wire [ADDR_WIDTH-1:0] addr_in,
    input  wire [7:0]  data_in,
    output reg  [7:0]  data_out,
    input  wire        read_in,
    input  wire        write_in,
    output reg         ready,

    // SDRAM interface
    output reg  [12:0] sdram_addr,
    output reg  [1:0]  sdram_ba,
    inout  wire [15:0] sdram_dq,
    output reg  [1:0]  sdram_dqm,
    output reg         sdram_cs_n,
    output reg         sdram_ras_n,
    output reg         sdram_cas_n,
    output reg         sdram_we_n,
    output reg         sdram_cke
);

    // Geometry for IS42S16320D: 4 banks, 4096 rows, 256 columns (x16)
    localparam integer ROW_BITS  = 12;
    localparam integer COL_BITS  = 8;
    localparam integer BANK_BITS = 2;
    localparam integer ADDR_WIDTH = ROW_BITS + COL_BITS + BANK_BITS + 1; // +1 for byte select

    // Timing parameters in cycles @133MHz (7.5ns)
    localparam integer tRCD_CYCLES = 3;   // ACT to RD/WR
    localparam integer tRP_CYCLES  = 3;   // PRECHARGE time
    localparam integer tRFC_CYCLES = 10;  // REFRESH recovery
    localparam integer tMRD_CYCLES = 2;   // MODE register set
    localparam integer tWR_CYCLES  = 2;   // Write recovery
    localparam integer CAS_LATENCY = 2;   // CL=2

    // Refresh: 7.8us interval -> 1040 cycles at 133MHz
    localparam integer REFRESH_INTERVAL = 1040;

    // Initialization delay: 200us -> 26600 cycles at 133MHz
    localparam integer INIT_DELAY = 26600;

    localparam [3:0]
        ST_RESET          = 4'd0,
        ST_INIT_WAIT      = 4'd1,
        ST_PRECHARGE      = 4'd2,
        ST_WAIT           = 4'd3,
        ST_REFRESH1       = 4'd4,
        ST_REFRESH2       = 4'd5,
        ST_MODE           = 4'd6,
        ST_IDLE           = 4'd7,
        ST_TRCD_WAIT      = 4'd8,
        ST_READ           = 4'd9,
        ST_WRITE          = 4'd10,
        ST_CAS_WAIT       = 4'd11,
        ST_WRITE_REC      = 4'd12,
        ST_REFRESH        = 4'd13;

    reg [3:0] state;
    reg [15:0] wait_cnt;
    reg [15:0] refresh_cnt;
    reg [3:0] next_state;

    reg [ADDR_WIDTH-1:0] addr_latched;
    reg op_read;
    reg op_write;

    reg [15:0] dq_out;
    reg dq_oe;

    wire [ADDR_WIDTH-2:0] word_addr = addr_latched[ADDR_WIDTH-1:1];
    wire byte_sel = addr_latched[0];

    wire [COL_BITS-1:0] col = word_addr[COL_BITS-1:0];
    wire [ROW_BITS-1:0] row = word_addr[COL_BITS + ROW_BITS - 1:COL_BITS];
    wire [BANK_BITS-1:0] bank = word_addr[COL_BITS + ROW_BITS + BANK_BITS - 1:COL_BITS + ROW_BITS];

    assign sdram_dq = dq_oe ? dq_out : 16'hzzzz;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= ST_RESET;
            wait_cnt <= 0;
            refresh_cnt <= 0;
            next_state <= ST_IDLE;
            ready <= 1'b0;
            data_out <= 8'h00;
            addr_latched <= {ADDR_WIDTH{1'b0}};
            op_read <= 1'b0;
            op_write <= 1'b0;
            dq_out <= 16'h0000;
            dq_oe <= 1'b0;

            sdram_addr <= 13'h0000;
            sdram_ba <= 2'b00;
            sdram_dqm <= 2'b11;
            sdram_cs_n <= 1'b1;
            sdram_ras_n <= 1'b1;
            sdram_cas_n <= 1'b1;
            sdram_we_n <= 1'b1;
            sdram_cke <= 1'b0;
        end else begin
            // Default SDRAM signals: NOP
            sdram_cs_n <= 1'b0;
            sdram_ras_n <= 1'b1;
            sdram_cas_n <= 1'b1;
            sdram_we_n <= 1'b1;
            sdram_dqm <= 2'b00;
            dq_oe <= 1'b0;
            ready <= 1'b0;

            // Refresh counter
            if (state == ST_IDLE) begin
                if (refresh_cnt >= REFRESH_INTERVAL) begin
                    refresh_cnt <= 0;
                end else begin
                    refresh_cnt <= refresh_cnt + 1'b1;
                end
            end else if (state == ST_REFRESH) begin
                refresh_cnt <= 0;
            end

            case (state)
                ST_RESET: begin
                    sdram_cke <= 1'b1;
                    wait_cnt <= INIT_DELAY;
                    state <= ST_INIT_WAIT;
                end

                ST_INIT_WAIT: begin
                    if (wait_cnt == 0) begin
                        state <= ST_PRECHARGE;
                    end else begin
                        wait_cnt <= wait_cnt - 1'b1;
                    end
                end

                ST_PRECHARGE: begin
                    // Precharge all banks
                    sdram_addr <= 13'b0010_0000_0000; // A10=1
                    sdram_ras_n <= 1'b0;
                    sdram_we_n <= 1'b0;
                    wait_cnt <= tRP_CYCLES;
                    next_state <= ST_REFRESH1;
                    state <= ST_WAIT;
                end

                ST_REFRESH1: begin
                    sdram_ras_n <= 1'b0;
                    sdram_cas_n <= 1'b0;
                    wait_cnt <= tRFC_CYCLES;
                    next_state <= ST_REFRESH2;
                    state <= ST_WAIT;
                end

                ST_REFRESH2: begin
                    sdram_ras_n <= 1'b0;
                    sdram_cas_n <= 1'b0;
                    wait_cnt <= tRFC_CYCLES;
                    next_state <= ST_MODE;
                    state <= ST_WAIT;
                end

                ST_MODE: begin
                    // Mode Register Set: burst length 1, sequential, CAS=2
                    sdram_addr <= 13'b0000_0010_0000; // A6..A4=010 (CL=2), A2..A0=000 (BL=1)
                    sdram_ras_n <= 1'b0;
                    sdram_cas_n <= 1'b0;
                    sdram_we_n <= 1'b0;
                    wait_cnt <= tMRD_CYCLES;
                    next_state <= ST_IDLE;
                    state <= ST_WAIT;
                end

                ST_WAIT: begin
                    if (wait_cnt == 0) begin
                        state <= next_state;
                    end else begin
                        wait_cnt <= wait_cnt - 1'b1;
                    end
                end

                ST_IDLE: begin
                    if (refresh_cnt >= REFRESH_INTERVAL) begin
                        state <= ST_REFRESH;
                    end else if (read_in || write_in) begin
                        addr_latched <= addr_in;
                        op_read <= read_in;
                        op_write <= write_in;
                        sdram_ba <= bank;
                        sdram_addr <= {1'b0, row};
                        sdram_ras_n <= 1'b0; // ACTIVATE
                        wait_cnt <= tRCD_CYCLES;
                        state <= ST_TRCD_WAIT;
                    end
                end

                ST_TRCD_WAIT: begin
                    if (wait_cnt == 0) begin
                        if (op_read) begin
                            state <= ST_READ;
                        end else begin
                            state <= ST_WRITE;
                        end
                    end else begin
                        wait_cnt <= wait_cnt - 1'b1;
                    end
                end

                ST_READ: begin
                    sdram_ba <= bank;
                    sdram_addr <= {3'b001, col}; // A10=1 for auto-precharge
                    sdram_ras_n <= 1'b1;
                    sdram_cas_n <= 1'b0;
                    sdram_we_n <= 1'b1;
                    sdram_dqm <= byte_sel ? 2'b01 : 2'b10; // mask opposite byte
                    wait_cnt <= CAS_LATENCY;
                    state <= ST_CAS_WAIT;
                end

                ST_CAS_WAIT: begin
                    if (wait_cnt == 0) begin
                        data_out <= byte_sel ? sdram_dq[15:8] : sdram_dq[7:0];
                        ready <= 1'b1;
                        state <= ST_IDLE;
                    end else begin
                        wait_cnt <= wait_cnt - 1'b1;
                    end
                end

                ST_WRITE: begin
                    sdram_ba <= bank;
                    sdram_addr <= {3'b001, col}; // A10=1 for auto-precharge
                    sdram_ras_n <= 1'b1;
                    sdram_cas_n <= 1'b0;
                    sdram_we_n <= 1'b0;
                    sdram_dqm <= byte_sel ? 2'b01 : 2'b10;
                    dq_out <= byte_sel ? {data_in, 8'h00} : {8'h00, data_in};
                    dq_oe <= 1'b1;
                    wait_cnt <= tWR_CYCLES;
                    state <= ST_WRITE_REC;
                end

                ST_WRITE_REC: begin
                    if (wait_cnt == 0) begin
                        ready <= 1'b1;
                        state <= ST_IDLE;
                    end else begin
                        wait_cnt <= wait_cnt - 1'b1;
                    end
                end

                ST_REFRESH: begin
                    sdram_ras_n <= 1'b0;
                    sdram_cas_n <= 1'b0;
                    wait_cnt <= tRFC_CYCLES;
                    next_state <= ST_IDLE;
                    state <= ST_WAIT;
                end

                default: state <= ST_IDLE;
            endcase

        end
    end
endmodule
