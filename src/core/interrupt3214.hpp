#pragma once

#include <array>
#include <cstdint>

namespace fk1 {

class Interrupt3214 {
public:
    void reset();
    void set_mask(std::uint8_t enabled_inputs);
    void set_input(std::uint8_t input, bool active);
    [[nodiscard]] bool requested() const;
    [[nodiscard]] std::uint8_t acknowledge_im2();

private:
    [[nodiscard]] int selected_input() const;

    std::array<bool, 8> inputs_{};
    std::uint8_t mask_{};
};

} // namespace fk1
