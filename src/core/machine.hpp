#pragma once

#include "core/interrupt3214.hpp"
#include "core/io_bus.hpp"
#include "core/memory_map.hpp"
#include "core/ppi8255.hpp"
#include "core/video.hpp"

#include <cstdint>

namespace fk1 {

using Tick = std::uint64_t;

// Owns all FK1 hardware. A Z80 adapter will drive memory and I/O through this
// class, while the SDL frontend only supplies input and displays Video output.
class Machine {
public:
    Machine();

    void reset();
    void run_until(Tick target);

    [[nodiscard]] Tick now() const;
    [[nodiscard]] std::uint8_t memory_read(std::uint16_t address) const;
    void memory_write(std::uint16_t address, std::uint8_t value);
    [[nodiscard]] std::uint8_t io_read(std::uint16_t port);
    void io_write(std::uint16_t port, std::uint8_t value);

    // External hardware edges. The scheduler will call these methods once its
    // video and input event sources are implemented.
    void vertical_sync_pulse();
    void set_mouse_signals(std::uint8_t signals);
    void video_ras_edge();

    [[nodiscard]] bool video_interrupt_pending() const;
    [[nodiscard]] bool mouse_interrupt_pending() const;
    [[nodiscard]] bool disk_timing_enabled() const;
    [[nodiscard]] std::uint8_t selected_drive() const;
    [[nodiscard]] bool drive_activity(std::uint8_t drive) const;

    [[nodiscard]] MemoryMap& memory();
    [[nodiscard]] Video& video();
    [[nodiscard]] Interrupt3214& interrupts();
    [[nodiscard]] Ppi8255& printer_keyboard_ppi();
    [[nodiscard]] Ppi8255& disk_data_ppi();
    [[nodiscard]] Ppi8255& machine_control_ppi();

private:
    Tick now_{};
    MemoryMap memory_;
    Video video_;
    Interrupt3214 interrupts_;
    Ppi8255 printer_keyboard_ppi_;
    Ppi8255 disk_data_ppi_;
    Ppi8255 machine_control_ppi_;
    IoBus io_bus_;
    std::uint8_t mouse_signals_{0xff};
    bool video_interrupt_latch_{};
    bool mouse_interrupt_latch_{};
};

} // namespace fk1
