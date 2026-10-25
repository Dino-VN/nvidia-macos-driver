/* Serialized metadata only: no imports, family-lock acquisition or GPU waits. */
#pragma once
#include "copy_request.h"
#include "gpu_protocol.h"

struct NMRotationGPUFlip {
    uint32_t version, reserved;
    NMRotationMode mode;
    void *memory;
    uint64_t allocationCookie;
    uint32_t width, height, pitch, format;
    int32_t flipResult;
    uint32_t flags;
};
static_assert(sizeof(NMRotationGPUFlip) == 96, "GPU flip request ABI");

struct NMRotationGPUSource {
    uint32_t id, latest, ready;
    NMRotationMode mode;
};
struct NMRotationGPUSlot {
    uint32_t id, source, ticket;
    bool busy, presenting, pendingSeen;
    NMRotationMode mode;
};
struct NMRotationGPUHead {
    NMRotationGPUSource sources[NM_ROTATION_GPU_SOURCES];
    NMRotationGPUSlot slots[NM_ROTATION_GPU_SLOTS];
    uint32_t front, previous, nextSource, serial;
};
struct NMRotationGPUState {
    NMRotationGPUHead heads[NM_ROTATION_GPU_HEADS];

    NMRotationGPUSource *find(uint32_t id, unsigned head, unsigned *index = nullptr) {
        if (!id || head >= NM_ROTATION_GPU_HEADS) return nullptr;
        for (unsigned i = 0; i < NM_ROTATION_GPU_SOURCES; ++i) {
            if (heads[head].sources[i].id == id) {
                if (index) *index = i;
                return &heads[head].sources[i];
            }
        }
        return nullptr;
    }
    void invalidateSources(unsigned head) {
        if (head >= NM_ROTATION_GPU_HEADS) return;
        auto &h = heads[head];
        for (auto &source : h.sources) source = {};
        h.nextSource = 0;
        // Preserve serials, in-flight leases and scanout exclusions across a
        // framebuffer replacement. Old completions cannot match a new source.
    }
    unsigned observe(uint32_t id, const NMRotationMode &mode) {
        if (!id || !nmRotationModeValid(&mode) || !mode.degrees || mode.head >= NM_ROTATION_GPU_HEADS)
            return UINT32_MAX;
        auto &h = heads[mode.head];
        unsigned index = NM_ROTATION_GPU_SOURCES;
        find(id, mode.head, &index);
        if (index == NM_ROTATION_GPU_SOURCES) index = h.nextSource++ % NM_ROTATION_GPU_SOURCES;
        auto &source = h.sources[index];
        if (source.id != id || !nmRotationSameMode(source.mode, mode)) {
            source = {};
            source.id = id;
            source.mode = mode;
        }
        return index;
    }
    uint32_t begin(uint32_t id, const NMRotationMode &current) {
        auto *source = find(id, current.head);
        if (!source || !nmRotationSameMode(source->mode, current) || !current.degrees) return 0;
        source->ready = source->latest = 0;
        auto &serial = heads[current.head].serial;
        // Never wrap a ticket onto a delayed completion. Each display has an
        // independent budget; another display cannot exhaust this one's nonce.
        if (serial >= 0x00ffffffu) return 0;
        source->latest = (++serial << 4) | (current.head + 1u);
        return source->latest;
    }
    NMRotationGPUSlot *slotFor(uint32_t ticket) {
        const int head = nmRotationGPUTicketHead(ticket);
        if (head < 0) return nullptr;
        for (auto &slot : heads[head].slots) if (slot.ticket == ticket) return &slot;
        return nullptr;
    }
    int bind(uint32_t ticket, uint32_t destination) {
        const int head = nmRotationGPUTicketHead(ticket);
        if (head < 0 || !destination) return -1;
        auto &h = heads[head];
        NMRotationGPUSource *source = nullptr;
        for (auto &entry : h.sources) if (entry.latest == ticket) { source = &entry; break; }
        if (!source || destination == h.front || destination == h.previous) return -1;
        for (unsigned other = 0; other < NM_ROTATION_GPU_HEADS; ++other) {
            auto &foreign = heads[other];
            for (auto &input : foreign.sources) if (input.id == destination) return -1;
            if (other == (unsigned)head) continue;
            if (destination == foreign.front || destination == foreign.previous) return -1;
            for (auto &slot : foreign.slots) if (slot.id == destination) return -1;
        }
        int candidate = -1;
        for (unsigned i = 0; i < NM_ROTATION_GPU_SLOTS; ++i) {
            auto &slot = h.slots[i];
            if (slot.id == destination) { candidate = (int)i; break; }
            if (candidate < 0 && !slot.busy && !slot.presenting &&
                (!slot.id || (slot.id != h.front && slot.id != h.previous))) candidate = (int)i;
        }
        if (candidate < 0) return -1;
        auto &slot = h.slots[candidate];
        if (slot.busy || slot.presenting || (slot.id && (slot.id == h.front || slot.id == h.previous))) return -1;
        slot = {};
        slot.id = destination;
        slot.source = source->id;
        slot.ticket = ticket;
        slot.busy = true;
        slot.mode = source->mode;
        return candidate;
    }
    void pending(uint32_t id) {
        // One IOSurface can feed more than one display. A write invalidates
        // every consumer, and witnesses each job encoded in this submission.
        for (unsigned head = 0; head < NM_ROTATION_GPU_HEADS; ++head) {
            auto *source = find(id, head);
            if (!source) continue;
            source->ready = 0;
            auto *slot = slotFor(source->latest);
            if (slot && slot->busy && !slot->pendingSeen) slot->pendingSeen = true;
            else source->latest = 0;
        }
    }
    bool done(uint32_t id, uint32_t ticket) {
        auto *slot = slotFor(ticket);
        if (!slot || !slot->busy || slot->source != id) return false;
        slot->busy = false;
        auto *source = find(id, (unsigned)nmRotationGPUTicketHead(ticket));
        if (!source || source->latest != ticket || !slot->pendingSeen ||
            !nmRotationSameMode(source->mode, slot->mode)) return false;
        source->ready = ticket;
        return true;
    }
    bool cancel(uint32_t ticket, uint32_t id = 0) {
        const int head = nmRotationGPUTicketHead(ticket);
        if (head < 0) return false;
        auto *slot = slotFor(ticket);
        if (!id && slot) id = slot->source;
        auto *source = find(id, (unsigned)head);
        const bool ownsSource = source && source->latest == ticket;
        const bool ownsSlot = slot && slot->source == id;
        if (!ownsSource && !ownsSlot) return false;
        if (ownsSlot && slot->busy) slot->busy = false;
        if (ownsSource) source->latest = source->ready = 0;
        return true;
    }
    NMRotationGPUSlot *take(uint32_t id, const NMRotationMode &mode) {
        auto *source = find(id, mode.head);
        if (!source || !source->ready || source->ready != source->latest || !nmRotationSameMode(source->mode, mode))
            return nullptr;
        auto *slot = slotFor(source->ready);
        if (!slot || slot->busy || slot->presenting || !nmRotationSameMode(slot->mode, mode)) return nullptr;
        slot->presenting = true;
        return slot;
    }
    bool awaiting(uint32_t id, const NMRotationMode &mode) {
        auto *source = find(id, mode.head);
        if (!source || !source->latest || !nmRotationSameMode(source->mode, mode)) return false;
        auto *slot = slotFor(source->latest);
        return slot && slot->source == id && slot->busy && slot->pendingSeen &&
            !slot->presenting && nmRotationSameMode(slot->mode, mode);
    }
    void put(uint32_t ticket, bool flipped) {
        auto *slot = slotFor(ticket);
        if (!slot || !slot->presenting) return;
        if (flipped) {
            auto &h = heads[slot->mode.head];
            if (h.front != slot->id) { h.previous = h.front; h.front = slot->id; }
        }
        slot->presenting = false;
    }
};
