package edu.bits.s23;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.util.ArrayList;
import java.util.List;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.functions.RuntimeContext;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;
import org.junit.jupiter.api.Test;

class AnalyticsTest {
    static final long NOW = 1800000000000L;

    @Test
    void parsesValidatedSyntheticEvents() throws Exception {
        Event event = Event.parse("""
            {"event_id":"reading:r","kind":"reading","device_id":"device-1",
             "occurred_at":1800000000000,"heart_rate":72,"latency_ms":null}
            """);
        assertEquals(72, event.heartRate);
        assertEquals(NOW, event.occurredAt);
        assertThrows(IllegalArgumentException.class, () -> Event.parse("{}"));
        assertThrows(IllegalArgumentException.class, () -> Event.parse("""
            {"event_id":"x","kind":"diagnosis","device_id":"device-1","occurred_at":1800000000000}
            """));
    }

    @Test
    void computesReadingsDeliveryAcknowledgementsAndEscalations() throws Exception {
        Stats stats = new Stats();
        for (Event event : List.of(
            Event.of("a", "reading", NOW, 70, null),
            Event.of("b", "reading", NOW, 90, null),
            Event.of("c", "created", NOW, null, null),
            Event.of("d", "delivered", NOW, null, 200),
            Event.of("e", "acknowledged", NOW, null, 800),
            Event.of("f", "escalated", NOW, null, null),
            Event.of("g", "failed", NOW, null, null))) {
            stats.add(event);
        }
        var result = stats.result("device-1", NOW, NOW + 60000);
        assertEquals(2, result.get("reading_count").asInt());
        assertEquals(80, result.get("average_heart_rate").asDouble());
        assertEquals(1, result.get("delivery_count").asInt());
        assertEquals(800, result.get("average_ack_delay_ms").asDouble());
        assertEquals(1, result.get("escalation_count").asInt());
        assertEquals(1, result.get("failed_count").asInt());
        assertTrue(new Stats().result("d", NOW, NOW + 60000).get("average_heart_rate").isNull());
        Stats combined = new Stats();
        combined.merge(stats);
        assertEquals(result, combined.result("device-1", NOW, NOW + 60000));
    }

    @Test
    void buildsRealKafkaWindowedTopologyWithoutNetwork() throws Exception {
        Options options = Options.parse(new String[]{
            "--brokers", "kafka:9092", "--mode", "local", "--checkpoint", "file:///tmp/checkpoints"
        });
        assertTrue(options.kafkaProperties().isEmpty());
        var env = StreamExecutionEnvironment.getExecutionEnvironment();
        ClinicalAnalytics.build(env, options);
        var graph = env.getStreamGraph().getStreamingPlanAsJSON();
        assertTrue(graph.contains("Kafka"));
        assertTrue(graph.contains("minute-windows"));
        assertTrue(graph.contains("deduplicate"));
        assertTrue(graph.contains("late-events"));
        assertEquals(60000, env.getCheckpointConfig().getCheckpointInterval());
    }

    @Test
    void awsUsesIamAndRejectsIncompleteOrUnexpectedOptions() {
        Options options = Options.parse(new String[]{
            "--brokers", "broker:9098", "--mode", "aws", "--region", "ap-south-1",
            "--checkpoint", "s3://demo/checkpoints"
        });
        assertEquals("AWS_MSK_IAM", options.kafkaProperties().getProperty("sasl.mechanism"));
        assertThrows(IllegalArgumentException.class, () -> Options.parse(new String[]{}));
        assertThrows(IllegalArgumentException.class, () -> Options.parse(new String[]{
            "--brokers", "b", "--mode", "wrong", "--checkpoint", "c"
        }));
        assertThrows(IllegalArgumentException.class, () -> Options.parse(new String[]{"--unknown"}));
    }

    @Test
    @SuppressWarnings({"unchecked", "rawtypes"})
    void statefulDeduplicationAndWindowOutputUseFlinkInterfaces() throws Exception {
        MapState<String, Boolean> state = mock(MapState.class);
        RuntimeContext runtime = mock(RuntimeContext.class);
        when(runtime.<String, Boolean>getMapState(any())).thenReturn(state);
        when(state.contains("event-a")).thenReturn(false, true);
        var deduplicate = new ClinicalAnalytics.Deduplicate();
        deduplicate.setRuntimeContext(runtime);
        deduplicate.open(mock(OpenContext.class));
        List<Event> accepted = new ArrayList<>();
        Collector<Event> collector = new Collector<>() {
            public void collect(Event event) { accepted.add(event); }
            public void close() {}
        };
        Event event = Event.of("event-a", "reading", NOW, 80, null);
        deduplicate.flatMap(event, collector);
        deduplicate.flatMap(event, collector);
        assertEquals(List.of(event), accepted);
        verify(state, times(1)).put("event-a", true);

        var aggregate = new ClinicalAnalytics.Aggregate();
        var first = aggregate.createAccumulator();
        aggregate.add(event, first);
        var second = aggregate.createAccumulator();
        aggregate.add(Event.of("event-b", "reading", NOW, 90, null), second);
        assertEquals(2, aggregate.getResult(aggregate.merge(first, second)).readings);

        ProcessWindowFunction.Context context = mock(ProcessWindowFunction.Context.class);
        when(context.window()).thenReturn(new TimeWindow(NOW, NOW + 60000));
        List<String> emitted = new ArrayList<>();
        new ClinicalAnalytics.WindowResult().process("device-1", context, List.of(first),
            new Collector<>() {
                public void collect(String result) { emitted.add(result); }
                public void close() {}
            });
        assertTrue(emitted.get(0).contains("\"reading_count\":2"));
        assertTrue(emitted.get(0).contains("\"window_end\":1800000060000"));
    }

    @Test
    void rejectsJsonLogInjectionAndNumericOverflow() throws Exception {
        var base = new ObjectMapper().createObjectNode()
            .put("event_id", "reading:r").put("kind", "reading")
            .put("device_id", "device-1").put("occurred_at", NOW).put("heart_rate", 72);
        for (var invalid : List.of(
            base.deepCopy().put("event_id", "bad\"id"),
            base.deepCopy().put("heart_rate", 4294967368L),
            base.deepCopy().put("latency_ms", 4294967296L),
            base.deepCopy().put("device_id", 123))) {
            assertThrows(IllegalArgumentException.class, () -> Event.parse(invalid.toString()));
        }
    }

    @Test
    void mainExecutesTheConfiguredJobWithoutStartingAnExternalCluster() throws Exception {
        var env = spy(StreamExecutionEnvironment.getExecutionEnvironment());
        doReturn(null).when(env).execute("S23 Clinical Analytics");
        try (var factory = mockStatic(StreamExecutionEnvironment.class)) {
            factory.when(StreamExecutionEnvironment::getExecutionEnvironment).thenReturn(env);
            ClinicalAnalytics.main(new String[]{
                "--brokers", "kafka:9092", "--mode", "local",
                "--checkpoint", "file:///tmp/checkpoints"
            });
        }
        verify(env).execute("S23 Clinical Analytics");
    }
}
