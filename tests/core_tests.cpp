#include "core/floppy.hpp"
#include "core/interrupt3214.hpp"
#include "core/memory_map.hpp"
#include "core/video.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <vector>

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

    static_assert(kFloppyImageBytes == 256'256);
    assert(crc16_ccitt(std::array<std::uint8_t, 0>{}) == 0xffff);
    assert(crc16_ccitt(std::array<std::uint8_t, 9>{'1', '2', '3', '4', '5', '6', '7', '8', '9'}) ==
           0x29b1);

    FloppyDrive drive;
    assert(!drive.insert_raw_image(std::vector<std::uint8_t>(kFloppyImageBytes - 1), false));
    std::vector<std::uint8_t> image(kFloppyImageBytes);
    image[0] = 0xa5;
    assert(drive.insert_raw_image(std::move(image), true));
    assert(drive.write_protected());
    const auto track = drive.current_track_bytes();
    assert(track.size() == kFmBytesPerTrack);
    assert((track[40] == FMByte{0x00, 0xff}));
    assert((track[46] == FMByte{kIndexMark, kIndexMarkClocks}));
    assert((track[79] == FMByte{kAddressMark, kAddressDataMarkClocks}));
    assert((track[84] == FMByte{0xd2, 0xff}));
    assert((track[85] == FMByte{0xc3, 0xff}));
    assert((track[103] == FMByte{kDataMark, kAddressDataMarkClocks}));
    assert((track[104] == FMByte{0xa5, 0xff}));
    assert((track[232] == FMByte{0x43, 0xff}));
    assert((track[233] == FMByte{0x14, 0xff}));
    assert((drive.fm_byte_at_phase() == FMByte{0xff, 0xff}));
    drive.advance(46 * kFmDataByteTicks);
    assert((drive.fm_byte_at_phase() == FMByte{kIndexMark, kIndexMarkClocks}));
    drive.advance(kFloppyRevolutionTicks - 46 * kFmDataByteTicks);
    assert(drive.index_active(1));
}
