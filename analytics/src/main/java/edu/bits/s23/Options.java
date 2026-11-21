package edu.bits.s23;

import java.util.HashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

public record Options(String brokers, String mode, String checkpoint, String region) {
    public static Options parse(String[] args) {
        Map<String, String> values = new HashMap<>();
        Set<String> known = Set.of("--brokers", "--mode", "--checkpoint", "--region");
        if (args.length % 2 != 0) throw new IllegalArgumentException("Options require name/value pairs");
        for (int i = 0; i < args.length; i += 2) {
            if (!known.contains(args[i]) || values.putIfAbsent(args[i], args[i + 1]) != null) {
                throw new IllegalArgumentException("Unknown or repeated option: " + args[i]);
            }
        }
        for (String key : Set.of("--brokers", "--mode", "--checkpoint")) {
            if (!values.containsKey(key) || values.get(key).isBlank()) {
                throw new IllegalArgumentException("Missing option: " + key);
            }
        }
        String mode = values.get("--mode");
        if (!Set.of("local", "aws").contains(mode)) {
            throw new IllegalArgumentException("mode must be local or aws");
        }
        if ("aws".equals(mode) && values.getOrDefault("--region", "").isBlank()) {
            throw new IllegalArgumentException("AWS mode requires --region");
        }
        return new Options(values.get("--brokers"), mode, values.get("--checkpoint"),
            values.getOrDefault("--region", "ap-south-1"));
    }

    public Properties kafkaProperties() {
        Properties properties = new Properties();
        if ("aws".equals(mode)) {
            properties.setProperty("security.protocol", "SASL_SSL");
            properties.setProperty("sasl.mechanism", "AWS_MSK_IAM");
            properties.setProperty("sasl.jaas.config",
                "software.amazon.msk.auth.iam.IAMLoginModule required awsRegion=\"" + region + "\";");
            properties.setProperty("sasl.client.callback.handler.class",
                "software.amazon.msk.auth.iam.IAMClientCallbackHandler");
        }
        return properties;
    }
}
