#include "core/io_bus.hpp"

#include "core/ppi8255.hpp"

namespace fk1 {

IoBus::IoBus(Ppi8255& printer_keyboard_ppi, Ppi8255& disk_data_ppi,
             Ppi8255& machine_control_ppi)
    : printer_keyboard_ppi_(printer_keyboard_ppi), disk_data_ppi_(disk_data_ppi),
      machine_control_ppi_(machine_control_ppi) {}

std::uint8_t IoBus::read(const std::uint16_t port) {
    switch (port & 0x70U) {
    case 0x00:
        return printer_keyboard_ppi_.read(static_cast<std::uint8_t>(port & 0x03U));
    case 0x20:
        return disk_data_ppi_.read(static_cast<std::uint8_t>(port & 0x03U));
    case 0x60:
        return machine_control_ppi_.read(static_cast<std::uint8_t>(port & 0x03U));
    default:
        return 0xff;
    }
}

void IoBus::write(const std::uint16_t port, const std::uint8_t value) {
    const auto register_select = static_cast<std::uint8_t>(port & 0x03U);
    switch (port & 0x70U) {
    case 0x00:
        printer_keyboard_ppi_.write(register_select, value);
        break;
    case 0x20:
        disk_data_ppi_.write(register_select, value);
        break;
    case 0x60:
        machine_control_ppi_.write(register_select, value);
        break;
    default:
        break;
    }
}

} // namespace fk1
