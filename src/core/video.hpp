#pragma once

#include "core/memory_map.hpp"

#include <array>
#include <cstdint>

namespace texty {

class Video {
public:
    static constexpr std::size_t kWidth = 512;
    static constexpr std::size_t kHeight = 256;
    using Framebuffer = std::array<std::uint32_t, kWidth * kHeight>;

    void set_scroll_ppi(std::uint8_t value);
    void ras_edge();
    [[nodiscard]] std::uint8_t scroll_latched() const;
    [[nodiscard]] Framebuffer render(const MemoryMap& memory) const;

private:
    std::uint8_t scroll_ppi_{};
    std::uint8_t scroll_latched_{};
};

} // namespace texty
