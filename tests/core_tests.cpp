#include "core/interrupt3214.hpp"
#include "core/memory_map.hpp"
#include "core/video.hpp"

#include <array>
#include <cassert>
#include <cstdint>

using namespace texty;

int main() {
    MemoryMap memory;
    std::array<std::uint8_t, 0x4000> rom{};
    rom[0] = 0x42;
    memory.set_rom(rom);
    assert(memory.read(0) == 0x42);
    memory.write(0, 0x99);
    assert(memory.read(0) == 0x42);
    memory.write(0x4000, 0x80);
    assert(memory.video_read(0) == 0x80);
    memory.select_ram_map();
    memory.write(0x4000, 0x55);
    assert(memory.read(0x4000) == 0x55);
    memory.select_rom_video_map();
    assert(memory.read(0x4000) == 0x80);

    Video video;
    auto frame = video.render(memory);
    assert(frame[0] == 0xffffffffU);
    assert(frame[1] == 0xff000000U);
    video.set_scroll_ppi(1);
    assert(video.scroll_latched() == 0);
    video.ras_edge();
    assert(video.scroll_latched() == 1);

    Interrupt3214 interrupts;
    interrupts.set_mask(2);
    interrupts.set_input(6, true);
    assert(interrupts.requested());
    assert(interrupts.acknowledge_im2() == 0x02);
    interrupts.set_input(7, true);
    assert(interrupts.acknowledge_im2() == 0x00);
    interrupts.set_mask(0);
    assert(!interrupts.requested());
}
