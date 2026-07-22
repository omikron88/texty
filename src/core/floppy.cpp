#include "core/floppy.hpp"

#include <algorithm>
#include <exception>

namespace fk1 {
namespace {

constexpr std::size_t kPreIndexGapBytes = 40;
constexpr std::size_t kSyncBytes = 6;
constexpr std::size_t kIndexGapBytes = 26;
constexpr std::size_t kGap1Bytes = 11;
constexpr std::size_t kGap2Bytes = 27;
constexpr std::size_t kPostIndexGapBytes = 247;

void append(FMTrack& track, std::size_t& position, const std::uint8_t data,
            const std::uint8_t clocks = kNormalFmClocks) {
    track[position++] = FMByte{data, clocks};
}

void append_repeated(FMTrack& track, std::size_t& position, const std::size_t count,
                     const std::uint8_t data) {
    for (std::size_t i = 0; i < count; ++i) append(track, position, data);
}

void append_crc(FMTrack& track, std::size_t& position, const std::uint16_t crc) {
    append(track, position, static_cast<std::uint8_t>(crc >> 8));
    append(track, position, static_cast<std::uint8_t>(crc));
}

} // namespace

std::uint16_t crc16_ccitt_update_byte(std::uint16_t crc, const std::uint8_t data) {
    for (unsigned int bit = 0; bit < 8; ++bit) {
        const auto feedback = static_cast<std::uint16_t>(((crc >> 15) ^ (data >> (7 - bit))) & 1U);
        crc = static_cast<std::uint16_t>(crc << 1);
        if (feedback != 0) crc ^= 0x1021U;
    }
    return crc;
}

std::uint16_t crc16_ccitt(const std::span<const std::uint8_t> data) {
    std::uint16_t crc = 0xffff;
    for (const auto byte : data) crc = crc16_ccitt_update_byte(crc, byte);
    return crc;
}

bool FloppyDrive::insert_raw_image(std::vector<std::uint8_t> image, const bool write_protected) {
    if (image.size() != kFloppyImageBytes) return false;
    raw_image_ = std::move(image);
    write_protected_ = write_protected;
    phase_ = 0;
    build_tracks();
    return true;
}

void FloppyDrive::eject() {
    raw_image_.clear();
    phase_ = 0;
    write_protected_ = false;
}

void FloppyDrive::advance(const std::uint64_t ticks) {
    if (has_media()) phase_ = (phase_ + ticks) % kFloppyRevolutionTicks;
}

void FloppyDrive::step(const Direction direction) {
    if (direction == Direction::TowardTrackZero) {
        if (track_ > 0) --track_;
    } else if (track_ < static_cast<std::uint8_t>(kFloppyTracks - 1)) {
        ++track_;
    }
}

bool FloppyDrive::has_media() const { return !raw_image_.empty(); }
bool FloppyDrive::write_protected() const { return has_media() && write_protected_; }
bool FloppyDrive::track_zero() const { return track_ == 0; }
bool FloppyDrive::index_active(const std::uint64_t pulse_width_ticks) const {
    return has_media() && phase_ < std::min(pulse_width_ticks, kFloppyRevolutionTicks);
}
std::uint8_t FloppyDrive::track() const { return track_; }
std::uint64_t FloppyDrive::phase() const { return phase_; }

std::span<const FMByte> FloppyDrive::current_track_bytes() const {
    if (!has_media()) return {};
    return tracks_[track_];
}

std::optional<FMByte> FloppyDrive::fm_byte_at_phase() const {
    if (!has_media()) return std::nullopt;
    const auto byte_index = static_cast<std::size_t>(phase_ / kFmDataByteTicks);
    if (byte_index >= kFmBytesPerTrack) return std::nullopt;
    return tracks_[track_][byte_index];
}

void FloppyDrive::build_tracks() {
    for (std::size_t track_number = 0; track_number < kFloppyTracks; ++track_number) {
        auto& fm_track = tracks_[track_number];
        std::size_t position = 0;
        append_repeated(fm_track, position, kPreIndexGapBytes, 0xff);
        append_repeated(fm_track, position, kSyncBytes, 0x00);
        append(fm_track, position, kIndexMark, kIndexMarkClocks);
        append_repeated(fm_track, position, kIndexGapBytes, 0xff);

        for (std::size_t sector = 0; sector < kFloppySectorsPerTrack; ++sector) {
            append_repeated(fm_track, position, kSyncBytes, 0x00);
            append(fm_track, position, kAddressMark, kAddressDataMarkClocks);
            append(fm_track, position, static_cast<std::uint8_t>(track_number));
            append(fm_track, position, 0); // One-sided media: head 0.
            append(fm_track, position, static_cast<std::uint8_t>(sector + 1));
            append(fm_track, position, 0); // N = 0 encodes 128 bytes.
            const std::array address_bytes{kAddressMark, static_cast<std::uint8_t>(track_number),
                                           std::uint8_t{0}, static_cast<std::uint8_t>(sector + 1),
                                           std::uint8_t{0}};
            append_crc(fm_track, position, crc16_ccitt(address_bytes));
            append_repeated(fm_track, position, kGap1Bytes, 0xff);
            append_repeated(fm_track, position, kSyncBytes, 0x00);
            append(fm_track, position, kDataMark, kAddressDataMarkClocks);

            const auto raw_offset =
                (track_number * kFloppySectorsPerTrack + sector) * kFloppyBytesPerSector;
            const auto payload = std::span{raw_image_}.subspan(raw_offset, kFloppyBytesPerSector);
            for (const auto byte : payload) append(fm_track, position, byte);
            std::uint16_t crc = crc16_ccitt_update_byte(0xffff, kDataMark);
            for (const auto byte : payload) crc = crc16_ccitt_update_byte(crc, byte);
            append_crc(fm_track, position, crc);
            append_repeated(fm_track, position, kGap2Bytes, 0xff);
        }

        append_repeated(fm_track, position, kPostIndexGapBytes, 0xff);
        if (position != kFmBytesPerTrack) std::terminate();
    }
}

} // namespace fk1
