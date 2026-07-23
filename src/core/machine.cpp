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
        return 0xff; // Mouse and I3 latch are connected by a later device.
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
        break; // Video I4 clear is connected by the video timing device.
    default:
        io_bus_.write(port, value);
        break;
    }
}

MemoryMap& Machine::memory() { return memory_; }
Video& Machine::video() { return video_; }
Interrupt3214& Machine::interrupts() { return interrupts_; }
Ppi8255& Machine::printer_keyboard_ppi() { return printer_keyboard_ppi_; }
Ppi8255& Machine::disk_data_ppi() { return disk_data_ppi_; }
Ppi8255& Machine::machine_control_ppi() { return machine_control_ppi_; }

} // namespace fk1
