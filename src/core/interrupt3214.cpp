#include "core/interrupt3214.hpp"

namespace texty {

void Interrupt3214::reset() {
    inputs_.fill(false);
    mask_ = 0;
}

void Interrupt3214::set_mask(const std::uint8_t enabled_inputs) {
    mask_ = enabled_inputs > 8 ? 8 : enabled_inputs;
}

void Interrupt3214::set_input(const std::uint8_t input, const bool active) {
    if (input < inputs_.size()) {
        inputs_[input] = active;
    }
}

int Interrupt3214::selected_input() const {
    for (int input = 7; input >= 0; --input) {
        // Mask 1 exposes I7, mask 2 I7/I6, etc.
        if (inputs_[static_cast<std::size_t>(input)] && input >= 8 - mask_) {
            return input;
        }
    }
    return -1;
}

bool Interrupt3214::requested() const {
    return selected_input() >= 0;
}

std::uint8_t Interrupt3214::acknowledge_im2() {
    const int input = selected_input();
    return input < 0 ? 0xff : static_cast<std::uint8_t>((7 - input) << 1);
}

} // namespace texty
