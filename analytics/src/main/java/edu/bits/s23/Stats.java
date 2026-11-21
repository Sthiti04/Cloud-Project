package edu.bits.s23;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.Serializable;

public class Stats implements Serializable {
    public long readings;
    public long heartRateSum;
    public long created;
    public long deliveries;
    public long acknowledgements;
    public long ackDelaySum;
    public long escalations;
    public long failed;

    public Stats() {}

    public void add(Event event) {
        switch (event.kind) {
            case "reading" -> { readings++; heartRateSum += event.heartRate; }
            case "created" -> created++;
            case "delivered" -> deliveries++;
            case "acknowledged" -> {
                acknowledgements++;
                ackDelaySum += event.latencyMs == null ? 0 : event.latencyMs;
            }
            case "escalated" -> escalations++;
            case "failed" -> failed++;
            default -> throw new IllegalArgumentException("Unsupported event kind");
        }
    }

    public void merge(Stats other) {
        readings += other.readings;
        heartRateSum += other.heartRateSum;
        created += other.created;
        deliveries += other.deliveries;
        acknowledgements += other.acknowledgements;
        ackDelaySum += other.ackDelaySum;
        escalations += other.escalations;
        failed += other.failed;
    }

    public ObjectNode result(String deviceId, long start, long end) {
        ObjectNode result = new ObjectMapper().createObjectNode();
        result.put("device_id", deviceId);
        result.put("window_start", start);
        result.put("window_end", end);
        result.put("reading_count", readings);
        result.put("created_count", created);
        result.put("delivery_count", deliveries);
        result.put("ack_count", acknowledgements);
        result.put("escalation_count", escalations);
        result.put("failed_count", failed);
        if (readings == 0) result.putNull("average_heart_rate");
        else result.put("average_heart_rate", (double) heartRateSum / readings);
        if (acknowledgements == 0) result.putNull("average_ack_delay_ms");
        else result.put("average_ack_delay_ms", (double) ackDelaySum / acknowledgements);
        return result;
    }
}
