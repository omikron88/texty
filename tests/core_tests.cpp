#include "core/floppy.hpp"
#include "core/interrupt3214.hpp"
#include "core/io_bus.hpp"
#include "core/machine.hpp"
#include "core/memory_map.hpp"
#include "core/ppi8255.hpp"
#include "core/video.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <vector>

using namespace fk1;

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

    Ppi8255 disk_ppi;
    disk_ppi.reset();
    disk_ppi.write(3, 0xa6); // PA mode-1 output, PB mode-1 input.
    disk_ppi.write(3, 0x0d); // BSR: enable INTE_A through PC6.
    disk_ppi.write(3, 0x05); // BSR: enable INTE_B through PC2.
    disk_ppi.write(0, 0x5a);
    assert(disk_ppi.port_a_latch() == 0x5a);
    assert(!disk_ppi.interrupt_a());
    assert((disk_ppi.read(2) & 0x80) == 0); // /OBF_A asserted.
    disk_ppi.set_acknowledge_a(false);
    assert(!disk_ppi.interrupt_a());
    assert((disk_ppi.read(2) & 0xc0) == 0xc0);
    disk_ppi.set_acknowledge_a(true);
    assert(disk_ppi.interrupt_a());
    assert((disk_ppi.read(2) & 0x88) == 0x88);
    disk_ppi.write(0, 0x3c);
    assert(!disk_ppi.interrupt_a());
    disk_ppi.set_port_b_input(0xa5);
    disk_ppi.set_strobe_b(false);
    assert(!disk_ppi.interrupt_b());
    assert((disk_ppi.read(2) & 0x06) == 0x06);
    disk_ppi.set_strobe_b(true);
    assert(disk_ppi.interrupt_b());
    assert((disk_ppi.read(2) & 0x03) == 0x03);
    assert(disk_ppi.read(1) == 0xa5);
    assert(!disk_ppi.interrupt_b());

    Ppi8255 printer_ppi;
    Ppi8255 control_ppi;
    IoBus io_bus(printer_ppi, disk_ppi, control_ppi);
    io_bus.write(0x1223, 0xa6); // A15-A8 and A7 must not affect FK1 decode.
    io_bus.write(0x9920, 0x3c);
    assert(disk_ppi.port_a_latch() == 0x3c);
    disk_ppi.set_port_b_input(0x96);
    disk_ppi.set_strobe_b(false);
    disk_ppi.set_strobe_b(true);
    assert(io_bus.read(0xf121) == 0x96);
    assert(io_bus.read(0x0014) == 0xff);

    Machine machine;
    machine.io_write(0x1233, 2);
    machine.interrupts().set_input(6, true);
    assert(machine.interrupts().requested());
    assert(machine.io_read(0xab30) == 0xff);
    assert(machine.memory().map() == MemoryMap::CpuMap::Ram);
    assert(machine.io_read(0x8050) == 0xff);
    assert(machine.memory().map() == MemoryMap::CpuMap::RomVideo);
    machine.run_until(1'234);
    assert(machine.now() == 1'234);
    machine.reset();
    assert(machine.now() == 0);
    assert(machine.memory().map() == MemoryMap::CpuMap::RomVideo);

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
