#include "core/memory_map.hpp"

namespace fk1 {

void MemoryMap::reset() { map_ = CpuMap::RomVideo; }

std::uint8_t MemoryMap::read(const std::uint16_t address) const {
    if (map_ == CpuMap::Ram) return ram_[address];
    if (address < 0x4000) return rom_[address];
    if (address < 0x8000) return video_ram_[address - 0x4000];
    return ram_[address];
}

void MemoryMap::write(const std::uint16_t address, const std::uint8_t value) {
    if (map_ == CpuMap::Ram) {
        ram_[address] = value;
    } else if (address >= 0x4000 && address < 0x8000) {
        video_ram_[address - 0x4000] = value;
    } else if (address >= 0x8000) {
        ram_[address] = value;
    }
}

std::uint8_t MemoryMap::video_read(const std::uint16_t address) const {
    return video_ram_[address & 0x3fff];
}

void MemoryMap::set_rom(std::array<std::uint8_t, 0x4000> rom) { rom_ = rom; }
void MemoryMap::select_ram_map() { map_ = CpuMap::Ram; }
void MemoryMap::select_rom_video_map() { map_ = CpuMap::RomVideo; }
MemoryMap::CpuMap MemoryMap::map() const { return map_; }

} // namespace fk1
