#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace fk1 {

inline constexpr std::size_t kFloppyHeads = 1;
inline constexpr std::size_t kFloppyTracks = 77;
inline constexpr std::size_t kFloppySectorsPerTrack = 26;
inline constexpr std::size_t kFloppyBytesPerSector = 128;
inline constexpr std::size_t kFloppyImageBytes =
    kFloppyHeads * kFloppyTracks * kFloppySectorsPerTrack * kFloppyBytesPerSector;

inline constexpr std::uint64_t kFloppyRevolutionTicks = 2'000'000;
inline constexpr std::uint64_t kFmDataByteTicks = 384;
inline constexpr std::size_t kFmBytesPerTrack = 5'208;

inline constexpr std::uint8_t kNormalFmClocks = 0xff;
inline constexpr std::uint8_t kIndexMarkClocks = 0xd7;
inline constexpr std::uint8_t kIndexMark = 0xfc;
inline constexpr std::uint8_t kAddressDataMarkClocks = 0xc7;
inline constexpr std::uint8_t kAddressMark = 0xfe;
inline constexpr std::uint8_t kDataMark = 0xfb;

struct FMByte {
    std::uint8_t data{};
    std::uint8_t clocks{kNormalFmClocks};

    [[nodiscard]] constexpr bool operator==(const FMByte&) const = default;
};

using FMTrack = std::array<FMByte, kFmBytesPerTrack>;

[[nodiscard]] std::uint16_t crc16_ccitt_update_byte(std::uint16_t crc, std::uint8_t data);
[[nodiscard]] std::uint16_t crc16_ccitt(std::span<const std::uint8_t> data);

class FloppyDrive {
public:
    enum class Direction { TowardTrackZero, AwayFromTrackZero };

    [[nodiscard]] bool insert_raw_image(std::vector<std::uint8_t> image, bool write_protected);
    void eject();
    void advance(std::uint64_t ticks);
    void step(Direction direction);

    [[nodiscard]] bool has_media() const;
    [[nodiscard]] bool write_protected() const;
    [[nodiscard]] bool track_zero() const;
    [[nodiscard]] bool index_active(std::uint64_t pulse_width_ticks) const;
    [[nodiscard]] std::uint8_t track() const;
    [[nodiscard]] std::uint64_t phase() const;
    [[nodiscard]] std::span<const FMByte> current_track_bytes() const;
    [[nodiscard]] std::optional<FMByte> fm_byte_at_phase() const;

private:
    void build_tracks();

    std::vector<std::uint8_t> raw_image_;
    std::array<FMTrack, kFloppyTracks> tracks_{};
    std::uint64_t phase_{};
    std::uint8_t track_{};
    bool write_protected_{};
};

} // namespace fk1
