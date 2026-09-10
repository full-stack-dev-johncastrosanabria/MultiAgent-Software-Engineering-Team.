# syntax=docker/dockerfile:1.7

# Etapa 1: resolucion de dependencias.
# Solo se copia el pom para que esta capa se invalide unicamente cuando cambien las dependencias.
FROM maven:3.9-eclipse-temurin-21 AS deps
WORKDIR /build
COPY pom.xml .
RUN mvn -B dependency:go-offline

# Etapa 2: compilacion y extraccion de capas.
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /build
COPY --from=deps /root/.m2 /root/.m2
COPY pom.xml .
COPY src ./src
RUN mvn -B clean package -DskipTests
RUN java -Djarmode=tools -jar target/order-ms-1.0.0.jar extract --layers --launcher --destination extracted

# Etapa 3: ejecucion. Sin Maven, JDK ni codigo fuente.
FROM eclipse-temurin:21-jre-alpine AS runtime

LABEL org.opencontainers.image.title="order-ms" \
      org.opencontainers.image.description="Servicio de gestion de pedidos" \
      org.opencontainers.image.version="1.0.0"

RUN addgroup -S app && adduser -S app -G app
WORKDIR /app

# Capas copiadas de menos a mas volatil: un cambio de codigo solo invalida la ultima.
COPY --from=builder --chown=app:app /build/extracted/dependencies/ ./
COPY --from=builder --chown=app:app /build/extracted/spring-boot-loader/ ./
COPY --from=builder --chown=app:app /build/extracted/snapshot-dependencies/ ./
COPY --from=builder --chown=app:app /build/extracted/application/ ./

USER app
EXPOSE 8080

# UseContainerSupport hace que la JVM respete el cgroup en lugar de leer la memoria del host
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+UseContainerSupport"

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD wget -qO- http://localhost:8080/actuator/health | grep -q '"status":"UP"' || exit 1

ENTRYPOINT ["java", "org.springframework.boot.loader.launch.JarLauncher"]
