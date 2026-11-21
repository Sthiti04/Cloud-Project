package edu.bits.s23;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.Serializable;
import java.util.Set;

public class Event implements Serializable {
    public String eventId;
    public String kind;
    public String deviceId;
    public long occurredAt;
    public Integer heartRate;
    public Integer latencyMs;
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<String> KINDS =
        Set.of("reading", "created", "delivered", "acknowledged", "escalated", "failed");

    public Event() {}

    public static Event parse(String payload) throws IOException {
        JsonNode value = JSON.readTree(payload);
        if (value == null || !value.path("event_id").isTextual()
            || !value.path("event_id").asText().matches("[A-Za-z0-9_:-]{1,100}")
            || !value.path("device_id").isTextual()
            || !value.path("device_id").asText().matches("[A-Za-z0-9_-]{1,80}")
            || !KINDS.contains(value.path("kind").asText())
            || !value.path("occurred_at").isIntegralNumber()
            || !value.path("occurred_at").canConvertToLong()
            || value.path("occurred_at").asLong() < 946684800000L) {
            throw new IllegalArgumentException("Invalid synthetic clinical-event schema");
        }
        Integer rate = value.path("heart_rate").isNull() || value.path("heart_rate").isMissingNode()
            ? null : value.path("heart_rate").intValue();
        if (("reading".equals(value.path("kind").asText()) && rate == null)
            || (rate != null && (!value.path("heart_rate").isIntegralNumber()
                || !value.path("heart_rate").canConvertToInt() || rate < 0 || rate > 300))) {
            throw new IllegalArgumentException("Reading requires an integer heart_rate in 0..300");
        }
        Integer latency = value.path("latency_ms").isNull() || value.path("latency_ms").isMissingNode()
            ? null : value.path("latency_ms").intValue();
        if (latency != null && (!value.path("latency_ms").isIntegralNumber()
            || !value.path("latency_ms").canConvertToInt() || latency < 0)) {
            throw new IllegalArgumentException("latency_ms must be a nonnegative integer");
        }
        Event event = of(value.path("event_id").asText(), value.path("kind").asText(),
            value.path("occurred_at").asLong(), rate, latency);
        event.deviceId = value.path("device_id").asText();
        return event;
    }

    public static Event of(String id, String kind, long timestamp, Integer rate, Integer latency) {
        Event event = new Event();
        event.eventId = id;
        event.kind = kind;
        event.deviceId = "device-1";
        event.occurredAt = timestamp;
        event.heartRate = rate;
        event.latencyMs = latency;
        return event;
    }
}
