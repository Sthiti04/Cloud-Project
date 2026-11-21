FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY analytics/pom.xml .
COPY analytics/src ./src
RUN mvn --batch-mode --quiet verify

FROM flink:1.20.0-scala_2.12-java17
USER root
RUN mkdir -p /checkpoints && chown flink:flink /checkpoints
COPY --from=build /build/target/clinical-analytics.jar /opt/flink/usrlib/clinical-analytics.jar
COPY --from=build /build/target/runtime/flink-metrics-prometheus.jar /opt/flink/lib/
COPY --from=build /build/target/runtime/flink-s3-fs-hadoop.jar /opt/flink/plugins/s3-fs-hadoop/
USER flink
