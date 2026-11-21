package edu.bits.s23;

import java.time.Duration;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.AggregateFunction;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.functions.RichFlatMapFunction;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.StateTtlConfig;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.assigners.TumblingEventTimeWindows;
import org.apache.flink.streaming.api.windowing.time.Time;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

public class ClinicalAnalytics {
    public static final OutputTag<Event> LATE = new OutputTag<>("late-events") {};

    public static class Deduplicate extends RichFlatMapFunction<Event, Event> {
        private transient MapState<String, Boolean> seen;

        @Override
        public void open(OpenContext context) throws Exception {
            var descriptor = new MapStateDescriptor<>("event-ids", String.class, Boolean.class);
            descriptor.enableTimeToLive(StateTtlConfig.newBuilder(Duration.ofMinutes(10))
                .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
                .setStateVisibility(StateTtlConfig.StateVisibility.NeverReturnExpired).build());
            seen = getRuntimeContext().getMapState(descriptor);
        }

        @Override
        public void flatMap(Event event, Collector<Event> output) throws Exception {
            if (!seen.contains(event.eventId)) {
                seen.put(event.eventId, true);
                output.collect(event);
            }
        }
    }

    public static class Aggregate implements AggregateFunction<Event, Stats, Stats> {
        public Stats createAccumulator() { return new Stats(); }
        public Stats add(Event value, Stats accumulator) { accumulator.add(value); return accumulator; }
        public Stats getResult(Stats accumulator) { return accumulator; }
        public Stats merge(Stats first, Stats second) { first.merge(second); return first; }
    }

    public static class WindowResult extends ProcessWindowFunction<Stats, String, String, TimeWindow> {
        @Override
        public void process(String device, Context context, Iterable<Stats> values,
                            Collector<String> output) {
            String result = values.iterator().next().result(
                device, context.window().getStart(), context.window().getEnd()).toString();
            System.out.println("{\"event\":\"analytics_window\",\"result\":" + result + "}");
            output.collect(result);
        }
    }

    public static DataStream<String> windows(DataStream<Event> events) {
        var deduplicated = events.keyBy(event -> event.deviceId)
            .flatMap(new Deduplicate()).name("deduplicate").uid("deduplicate");
        var windows = deduplicated.keyBy(event -> event.deviceId)
            .window(TumblingEventTimeWindows.of(Time.minutes(1)))
            .allowedLateness(Time.seconds(10)).sideOutputLateData(LATE)
            .aggregate(new Aggregate(), new WindowResult()).name("minute-windows").uid("minute-windows");
        windows.getSideOutput(LATE)
            .map(event -> "{\"event\":\"late_event_dropped\",\"event_id\":\"" + event.eventId + "\"}")
            .name("late-events").print("s23-late-events");
        return windows;
    }

    public static void build(StreamExecutionEnvironment env, Options options) {
        env.setParallelism(2);
        env.enableCheckpointing(60000);
        env.getCheckpointConfig().setCheckpointStorage(options.checkpoint());
        var source = KafkaSource.<String>builder()
            .setBootstrapServers(options.brokers()).setTopics("clinical-events")
            .setGroupId("clinical-analytics").setStartingOffsets(OffsetsInitializer.earliest())
            .setProperties(options.kafkaProperties()).setValueOnlyDeserializer(new SimpleStringSchema())
            .build();
        var events = env.fromSource(source, WatermarkStrategy.noWatermarks(), "Kafka clinical-events")
            .map(Event::parse).returns(Event.class)
            .assignTimestampsAndWatermarks(WatermarkStrategy.<Event>forBoundedOutOfOrderness(
                Duration.ofSeconds(5)).withTimestampAssigner((event, previous) -> event.occurredAt)
                .withIdleness(Duration.ofSeconds(15)));
        var sink = KafkaSink.<String>builder().setBootstrapServers(options.brokers())
            .setKafkaProducerConfig(options.kafkaProperties())
            .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
            .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                .setTopic("clinical-results").setValueSerializationSchema(new SimpleStringSchema())
                .build()).build();
        windows(events).sinkTo(sink).name("Kafka clinical-results").uid("clinical-results");
    }

    public static void main(String[] args) throws Exception {
        var env = StreamExecutionEnvironment.getExecutionEnvironment();
        build(env, Options.parse(args));
        env.execute("S23 Clinical Analytics");
    }
}
