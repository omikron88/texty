#pragma once

#include <array>
#include <cstdint>

namespace texty {

class MemoryMap {
public:
    enum class CpuMap { RomVideo, Ram };

    void reset();
    [[nodiscard]] std::uint8_t read(std::uint16_t address) const;
    void write(std::uint16_t address, std::uint8_t value);
    [[nodiscard]] std::uint8_t video_read(std::uint16_t address) const;
    void set_rom(std::array<std::uint8_t, 0x4000> rom);
    void select_ram_map();
    void select_rom_video_map();
    [[nodiscard]] CpuMap map() const;

private:
    std::array<std::uint8_t, 0x4000> rom_{};
    std::array<std::uint8_t, 0x4000> video_ram_{};
    std::array<std::uint8_t, 0x10000> ram_{};
    CpuMap map_{CpuMap::RomVideo};
};

} // namespace texty
