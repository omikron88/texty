#pragma once

#include <cstdint>

namespace fk1 {

class Ppi8255 {
public:
    void reset();

    [[nodiscard]] std::uint8_t read(std::uint8_t register_select);
    void write(std::uint8_t register_select, std::uint8_t value);

    // Peripheral-side pins. Both handshake inputs are active low.
    void set_acknowledge_a(bool high);
    void set_port_b_input(std::uint8_t value);
    void set_strobe_b(bool high);

    // Convenience methods for a complete active-low handshake pulse.
    void acknowledge_a();
    void strobe_b(std::uint8_t value);

    void set_port_c_inputs(std::uint8_t value);

    [[nodiscard]] std::uint8_t port_a_latch() const;
    [[nodiscard]] std::uint8_t port_b_latch() const;
    [[nodiscard]] std::uint8_t port_c_latch() const;
    [[nodiscard]] bool port_a_output_enabled() const;
    [[nodiscard]] bool port_c_output_enabled(std::uint8_t bit) const;
    [[nodiscard]] bool interrupt_a() const;
    [[nodiscard]] bool interrupt_b() const;

private:
    void mode_set(std::uint8_t control);
    void bit_set_reset(std::uint8_t control);
    [[nodiscard]] bool group_a_mode_1() const;
    [[nodiscard]] bool group_b_mode_1() const;
    [[nodiscard]] bool port_a_input() const;
    [[nodiscard]] bool port_b_input() const;
    [[nodiscard]] bool port_c_upper_input() const;
    [[nodiscard]] bool port_c_lower_input() const;
    [[nodiscard]] std::uint8_t read_port_c() const;

    std::uint8_t control_{0x9b};
    std::uint8_t port_a_latch_{};
    std::uint8_t port_b_latch_{};
    std::uint8_t port_b_input_{0xff};
    std::uint8_t port_c_latch_{};
    std::uint8_t port_c_inputs_{0xff};
    bool obf_a_{true};
    bool ibf_b_{};
    bool inte_a_{};
    bool inte_b_{};
    bool intr_a_{};
    bool intr_b_{};
    bool acknowledge_a_high_{true};
    bool strobe_b_high_{true};
};

} // namespace fk1
