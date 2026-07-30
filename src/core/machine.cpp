#include "core/machine.hpp"

namespace fk1 {

Machine::Machine()
    : io_bus_(printer_keyboard_ppi_, disk_data_ppi_, machine_control_ppi_) {
    reset();
}

void Machine::reset() {
    now_ = 0;
    memory_.reset();
    interrupts_.reset();
    printer_keyboard_ppi_.reset();
    disk_data_ppi_.reset();
    machine_control_ppi_.reset();
    video_.set_scroll_ppi(0);
    video_.ras_edge();
    mouse_signals_ = 0xff;
    video_interrupt_latch_ = false;
    mouse_interrupt_latch_ = false;
}

void Machine::run_until(const Tick target) {
    if (target <= now_) return;

    // CPU/PIT/video/floppy event scheduling belongs here. Until the Z80 adapter
    // is connected, advancing is intentionally side-effect free and deterministic.
    now_ = target;
}

Tick Machine::now() const { return now_; }
std::uint8_t Machine::memory_read(const std::uint16_t address) const { return memory_.read(address); }
void Machine::memory_write(const std::uint16_t address, const std::uint8_t value) { memory_.write(address, value); }

std::uint8_t Machine::io_read(const std::uint16_t port) {
    switch (port & 0x70U) {
    case 0x30:
        memory_.select_ram_map();
        return 0xff;
    case 0x50:
        memory_.select_rom_video_map();
        return 0xff;
    case 0x70:
        mouse_interrupt_latch_ = false;
        interrupts_.set_input(3, false);
        return mouse_signals_;
    default:
        return io_bus_.read(port);
    }
}

void Machine::io_write(const std::uint16_t port, const std::uint8_t value) {
    switch (port & 0x70U) {
    case 0x30:
        interrupts_.set_mask(value);
        break;
    case 0x70:
        video_interrupt_latch_ = false;
        interrupts_.set_input(4, false);
        break;
    default:
        io_bus_.write(port, value);
        if ((port & 0x70U) == 0x60U) {
            // PB is wired to a separate /RAS-clocked scroll register. A mode
            // set also clears the PPI output latch and must be observable.
            video_.set_scroll_ppi(machine_control_ppi_.port_b_latch());
        }
        break;
    }
}

void Machine::vertical_sync_pulse() {
    if (machine_control_ppi_.port_a_output_enabled() &&
        (machine_control_ppi_.port_a_latch() & 0x04U) != 0) {
        video_interrupt_latch_ = true;
        interrupts_.set_input(4, true);
    }
}

void Machine::set_mouse_signals(const std::uint8_t signals) {
    if (signals != mouse_signals_ && machine_control_ppi_.port_a_output_enabled() &&
        (machine_control_ppi_.port_a_latch() & 0x08U) != 0) {
        mouse_interrupt_latch_ = true;
        interrupts_.set_input(3, true);
    }
    mouse_signals_ = signals;
}

void Machine::video_ras_edge() { video_.ras_edge(); }
bool Machine::video_interrupt_pending() const { return video_interrupt_latch_; }
bool Machine::mouse_interrupt_pending() const { return mouse_interrupt_latch_; }
bool Machine::disk_timing_enabled() const {
    // PA6 has a pull-up while the reset/input state leaves the pin floating.
    return machine_control_ppi_.port_a_output_enabled() &&
           (machine_control_ppi_.port_a_latch() & 0x40U) == 0;
}
std::uint8_t Machine::selected_drive() const {
    // PC5 also has a pull-up, selecting B until firmware makes it an output.
    if (!disk_data_ppi_.port_c_output_enabled(5)) return 1U;
    return (disk_data_ppi_.port_c_latch() & 0x20U) == 0 ? 0U : 1U;
}
bool Machine::drive_activity(const std::uint8_t drive) const {
    return drive < 2U && disk_timing_enabled() && selected_drive() == drive;
}

MemoryMap& Machine::memory() { return memory_; }
Video& Machine::video() { return video_; }
Interrupt3214& Machine::interrupts() { return interrupts_; }
Ppi8255& Machine::printer_keyboard_ppi() { return printer_keyboard_ppi_; }
Ppi8255& Machine::disk_data_ppi() { return disk_data_ppi_; }
Ppi8255& Machine::machine_control_ppi() { return machine_control_ppi_; }

} // namespace fk1
