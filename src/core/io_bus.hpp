#pragma once

#include <cstdint>

namespace fk1 {

class Ppi8255;

// FK1 I/O decoder. CPU cores use this through their port-read/write callbacks.
class IoBus {
public:
    IoBus(Ppi8255& printer_keyboard_ppi, Ppi8255& disk_data_ppi,
          Ppi8255& machine_control_ppi);

    [[nodiscard]] std::uint8_t read(std::uint16_t port);
    void write(std::uint16_t port, std::uint8_t value);

private:
    Ppi8255& printer_keyboard_ppi_;
    Ppi8255& disk_data_ppi_;
    Ppi8255& machine_control_ppi_;
};

} // namespace fk1
