#include "core/ppi8255.hpp"

namespace fk1 {

void Ppi8255::reset() {
    control_ = 0x9b;
    port_a_latch_ = 0;
    port_b_latch_ = 0;
    port_b_input_ = 0xff;
    port_c_latch_ = 0;
    port_c_inputs_ = 0xff;
    obf_a_ = true;
    ibf_b_ = false;
    inte_a_ = false;
    inte_b_ = false;
    intr_a_ = false;
    intr_b_ = false;
    acknowledge_a_high_ = true;
    strobe_b_high_ = true;
}

bool Ppi8255::group_a_mode_1() const { return ((control_ >> 5U) & 0x03U) == 1U; }
bool Ppi8255::group_b_mode_1() const { return (control_ & 0x04U) != 0; }
bool Ppi8255::port_a_input() const { return (control_ & 0x10U) != 0; }
bool Ppi8255::port_b_input() const { return (control_ & 0x02U) != 0; }
bool Ppi8255::port_c_upper_input() const { return (control_ & 0x08U) != 0; }
bool Ppi8255::port_c_lower_input() const { return (control_ & 0x01U) != 0; }

void Ppi8255::mode_set(const std::uint8_t control) {
    control_ = control;
    port_a_latch_ = 0;
    port_b_latch_ = 0;
    port_b_input_ = 0xff;
    port_c_latch_ = 0;
    obf_a_ = true;
    ibf_b_ = false;
    inte_a_ = false;
    inte_b_ = false;
    intr_a_ = false;
    intr_b_ = false;
    acknowledge_a_high_ = true;
    strobe_b_high_ = true;
}

void Ppi8255::bit_set_reset(const std::uint8_t control) {
    const std::uint8_t bit = static_cast<std::uint8_t>((control >> 1U) & 0x07U);
    const bool set = (control & 1U) != 0;

    // In mode 1 these BSR addresses feed the hidden interrupt-enable latches.
    if (group_a_mode_1() && !port_a_input() && bit == 6U) {
        inte_a_ = set;
        if (!inte_a_) {
            intr_a_ = false;
        }
        return;
    }
    if (group_b_mode_1() && port_b_input() && bit == 2U) {
        inte_b_ = set;
        if (!inte_b_) {
            intr_b_ = false;
        }
        return;
    }

    const std::uint8_t mask = static_cast<std::uint8_t>(1U << bit);
    if (set) {
        port_c_latch_ |= mask;
    } else {
        port_c_latch_ &= static_cast<std::uint8_t>(~mask);
    }
}

void Ppi8255::write(const std::uint8_t register_select, const std::uint8_t value) {
    switch (register_select & 0x03U) {
    case 0:
        if (!port_a_input()) {
            port_a_latch_ = value;
            if (group_a_mode_1()) {
                obf_a_ = false;
                intr_a_ = false;
            }
        }
        break;
    case 1:
        if (!port_b_input()) {
            port_b_latch_ = value;
        }
        break;
    case 2:
        port_c_latch_ = value;
        break;
    case 3:
        if ((value & 0x80U) != 0) {
            mode_set(value);
        } else {
            bit_set_reset(value);
        }
        break;
    }
}

std::uint8_t Ppi8255::read_port_c() const {
    std::uint8_t value = 0;
    for (std::uint8_t bit = 0; bit != 8U; ++bit) {
        const std::uint8_t mask = static_cast<std::uint8_t>(1U << bit);
        const bool input = bit >= 4U ? port_c_upper_input() : port_c_lower_input();
        const bool pin = input ? (port_c_inputs_ & mask) != 0 : (port_c_latch_ & mask) != 0;
        if (pin) {
            value |= mask;
        }
    }

    if (group_a_mode_1() && !port_a_input()) {
        value = static_cast<std::uint8_t>((value & ~0xc8U) | (obf_a_ ? 0x80U : 0U) |
                                          (inte_a_ ? 0x40U : 0U) |
                                          (intr_a_ ? 0x08U : 0U));
    }
    if (group_b_mode_1() && port_b_input()) {
        value = static_cast<std::uint8_t>((value & ~0x07U) | (inte_b_ ? 0x04U : 0U) |
                                          (ibf_b_ ? 0x02U : 0U) |
                                          (intr_b_ ? 0x01U : 0U));
    }
    return value;
}

std::uint8_t Ppi8255::read(const std::uint8_t register_select) {
    switch (register_select & 0x03U) {
    case 0:
        return port_a_latch_;
    case 1:
        if (group_b_mode_1() && port_b_input()) {
            ibf_b_ = false;
            intr_b_ = false;
            return port_b_latch_;
        }
        return port_b_input() ? port_b_input_ : port_b_latch_;
    case 2:
        return read_port_c();
    default:
        return 0xff;
    }
}

void Ppi8255::set_acknowledge_a(const bool high) {
    if (group_a_mode_1() && !port_a_input() && acknowledge_a_high_ && !high) {
        obf_a_ = true;
        intr_a_ = false;
    } else if (group_a_mode_1() && !port_a_input() && !acknowledge_a_high_ && high) {
        intr_a_ = inte_a_ && obf_a_;
    }
    acknowledge_a_high_ = high;
}

void Ppi8255::set_port_b_input(const std::uint8_t value) { port_b_input_ = value; }

void Ppi8255::set_strobe_b(const bool high) {
    if (group_b_mode_1() && port_b_input() && strobe_b_high_ && !high) {
        port_b_latch_ = port_b_input_;
        ibf_b_ = true;
        intr_b_ = false;
    } else if (group_b_mode_1() && port_b_input() && !strobe_b_high_ && high) {
        intr_b_ = inte_b_ && ibf_b_;
    }
    strobe_b_high_ = high;
}

void Ppi8255::acknowledge_a() { set_acknowledge_a(false); set_acknowledge_a(true); }

void Ppi8255::strobe_b(const std::uint8_t value) {
    set_port_b_input(value);
    set_strobe_b(false);
    set_strobe_b(true);
}

void Ppi8255::set_port_c_inputs(const std::uint8_t value) { port_c_inputs_ = value; }
std::uint8_t Ppi8255::port_a_latch() const { return port_a_latch_; }
std::uint8_t Ppi8255::port_b_latch() const { return port_b_latch_; }
std::uint8_t Ppi8255::port_c_latch() const { return port_c_latch_; }
bool Ppi8255::port_a_output_enabled() const { return !port_a_input(); }
bool Ppi8255::port_c_output_enabled(const std::uint8_t bit) const {
    return bit < 8U && !(bit >= 4U ? port_c_upper_input() : port_c_lower_input());
}
bool Ppi8255::interrupt_a() const { return intr_a_; }
bool Ppi8255::interrupt_b() const { return intr_b_; }

} // namespace fk1
