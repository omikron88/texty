#include "core/video.hpp"

namespace fk1 {

void Video::set_scroll_ppi(const std::uint8_t value) { scroll_ppi_ = value; }
void Video::ras_edge() { scroll_latched_ = scroll_ppi_; }
std::uint8_t Video::scroll_latched() const { return scroll_latched_; }

Video::Framebuffer Video::render(const MemoryMap& memory) const {
    Framebuffer frame{};
    for (std::size_t y = 0; y < kHeight; ++y) {
        const auto source_y = static_cast<std::uint8_t>(y + scroll_latched_);
        for (std::size_t x = 0; x < kWidth; ++x) {
            const auto address = static_cast<std::uint16_t>(((x >> 3) << 8) | source_y);
            const auto mask = static_cast<std::uint8_t>(0x80U >> (x & 7));
            frame[y * kWidth + x] = (memory.video_read(address) & mask) ? 0xffffffffU : 0xff000000U;
        }
    }
    return frame;
}

} // namespace fk1
