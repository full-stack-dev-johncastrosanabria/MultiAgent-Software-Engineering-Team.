package com.prueba.orderms;

import com.prueba.orderms.crypto.RsaCipherService;
import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.messaging.KafkaTopics;
import com.prueba.orderms.messaging.OrderPlacedEvent;
import com.prueba.orderms.messaging.PaymentProcessedEvent;
import com.prueba.orderms.repository.OrderRepository;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.kafka.test.utils.KafkaTestUtils;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

class OrderFlowIntegrationTest extends IntegrationTestBase {

    @Autowired private TestRestTemplate cliente;
    @Autowired private RsaCipherService cifrador;
    @Autowired private OrderRepository repositorio;
    @Autowired private KafkaTemplate<String, Object> plantilla;

    private String cuerpoDePedido(String monto) {
        String tarjeta = cifrador.encrypt(
                "{\"pan\":\"4242424242424242\",\"cvv\":\"123\",\"expiryMonth\":12,\"expiryYear\":2030,\"holder\":\"ANA TORRES\"}");
        return """
                {"customerName":"Ana Torres","customerEmail":"ana@ejemplo.com",
                 "productSku":"SKU-1","productName":"Teclado","quantity":1,
                 "unitPrice":%s,"currency":"USD","encryptedCard":"%s"}
                """.formatted(monto, tarjeta);
    }

    private UUID crearPedido(String monto) {
        HttpHeaders cabeceras = new HttpHeaders();
        cabeceras.setContentType(MediaType.APPLICATION_JSON);

        ResponseEntity<Map> respuesta = cliente.postForEntity(
                "/api/v1/orders",
                new HttpEntity<>(cuerpoDePedido(monto), cabeceras),
                Map.class);

        assertThat(respuesta.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(respuesta.getHeaders().getLocation()).isNotNull();
        return UUID.fromString((String) respuesta.getBody().get("id"));
    }

    @Test
    void elPedidoNaceEnPendienteYSePublicaElEvento() {
        try (Consumer<String, OrderPlacedEvent> consumidor = consumidorDe(KafkaTopics.ORDER_PLACED)) {
            // Forzar asignacion de particion antes de publicar, para no ver eventos previos de otros tests
            consumidor.poll(java.time.Duration.ofMillis(500));

            UUID id = crearPedido("49.95");

            assertThat(repositorio.findById(id)).isPresent()
                    .get().extracting("status").isEqualTo(OrderStatus.PENDIENTE);

            ConsumerRecord<String, OrderPlacedEvent> registro =
                    KafkaTestUtils.getSingleRecord(consumidor, KafkaTopics.ORDER_PLACED,
                            Duration.ofSeconds(15));

            assertThat(registro.key()).isEqualTo(id.toString());
            assertThat(registro.value().orderId()).isEqualTo(id);
            assertThat(registro.value().card().lastFour()).isEqualTo("4242");
        }
    }

    @Test
    void elEventoPublicadoNoTransportaDatosSensibles() throws Exception {
        try (Consumer<String, OrderPlacedEvent> consumidor = consumidorDe(KafkaTopics.ORDER_PLACED)) {
            // Forzar asignacion de particion antes de publicar
            consumidor.poll(java.time.Duration.ofMillis(500));

            crearPedido("49.95");

            ConsumerRecord<String, OrderPlacedEvent> registro =
                    KafkaTestUtils.getSingleRecord(consumidor, KafkaTopics.ORDER_PLACED,
                            Duration.ofSeconds(15));

            OrderPlacedEvent evento = registro.value();
            // El evento contiene solo los ultimos cuatro y la marca; el PAN completo y el CVV no existen como campos
            assertThat(evento.card().lastFour()).hasSize(4);
            assertThat(evento.card().lastFour()).isEqualTo("4242");
            assertThat(evento.card().brand()).isEqualTo("VISA");
            // Verificar via JSON que el PAN completo no esta serializado
            String json = new com.fasterxml.jackson.databind.ObjectMapper()
                    .registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule())
                    .writeValueAsString(evento);
            assertThat(json).doesNotContain("4242424242424242");
            assertThat(json).doesNotContain("cvv");
            assertThat(json).doesNotContain("pan");
        }
    }

    @Test
    void unResultadoAprobadoLlevaElPedidoAPagado() {
        UUID id = crearPedido("49.95");

        plantilla.send(KafkaTopics.PAYMENT_PROCESSED, id.toString(),
                new PaymentProcessedEvent(UUID.randomUUID(), id, Instant.now(),
                        "APROBADO", "PAY-ABC123", null));

        await().atMost(Duration.ofSeconds(20)).untilAsserted(() ->
                assertThat(repositorio.findById(id)).get()
                        .extracting("status").isEqualTo(OrderStatus.PAGADO));
    }

    @Test
    void unResultadoRechazadoLlevaElPedidoAFalloDePago() {
        UUID id = crearPedido("49.95");

        plantilla.send(KafkaTopics.PAYMENT_PROCESSED, id.toString(),
                new PaymentProcessedEvent(UUID.randomUUID(), id, Instant.now(),
                        "RECHAZADO", null, "Fondos insuficientes"));

        await().atMost(Duration.ofSeconds(20)).untilAsserted(() ->
                assertThat(repositorio.findById(id)).get()
                        .extracting("status").isEqualTo(OrderStatus.FALLO_PAGO));
    }

    @Test
    void reenviarElMismoEventoNoAlteraElResultado() {
        UUID id = crearPedido("49.95");
        UUID idDeEvento = UUID.randomUUID();

        PaymentProcessedEvent evento = new PaymentProcessedEvent(
                idDeEvento, id, Instant.now(), "APROBADO", "PAY-ABC123", null);

        plantilla.send(KafkaTopics.PAYMENT_PROCESSED, id.toString(), evento);
        await().atMost(Duration.ofSeconds(20)).untilAsserted(() ->
                assertThat(repositorio.findById(id)).get()
                        .extracting("status").isEqualTo(OrderStatus.PAGADO));

        // Reentrega del mismo evento: la referencia no debe cambiar
        plantilla.send(KafkaTopics.PAYMENT_PROCESSED, id.toString(), evento);

        await().during(Duration.ofSeconds(3)).atMost(Duration.ofSeconds(10)).untilAsserted(() ->
                assertThat(repositorio.findById(id)).get()
                        .extracting("paymentReference").isEqualTo("PAY-ABC123"));
    }

    @Test
    void unCriptogramaInvalidoDevuelveCuatrocientosYNoCreaPedido() {
        long antes = repositorio.count();

        HttpHeaders cabeceras = new HttpHeaders();
        cabeceras.setContentType(MediaType.APPLICATION_JSON);
        String cuerpo = "{\"customerName\":\"Ana\",\"customerEmail\":\"ana@ejemplo.com\"," +
                "\"productSku\":\"SKU-1\",\"productName\":\"Teclado\",\"quantity\":1," +
                "\"unitPrice\":10.00,\"currency\":\"USD\",\"encryptedCard\":\"bm8tZXMtdW4tY3JpcHRvZ3JhbWE=\"}";

        ResponseEntity<String> respuesta = cliente.postForEntity("/api/v1/orders",
                new HttpEntity<>(cuerpo, cabeceras), String.class);

        assertThat(respuesta.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(repositorio.count()).isEqualTo(antes);
    }

    private Consumer<String, OrderPlacedEvent> consumidorDe(String topic) {
        Map<String, Object> propiedades = KafkaTestUtils.consumerProps(
                KAFKA.getBootstrapServers(), "prueba-" + UUID.randomUUID(), "true");
        propiedades.put("key.deserializer", StringDeserializer.class);
        propiedades.put("value.deserializer", JsonDeserializer.class);
        propiedades.put("spring.json.trusted.packages", "com.prueba.orderms.messaging");
        propiedades.put("spring.json.value.default.type",
                "com.prueba.orderms.messaging.OrderPlacedEvent");
        propiedades.put("spring.json.use.type.headers", false);
        // latest: solo ver mensajes publicados despues de que el consumidor se asigne a la particion
        propiedades.put("auto.offset.reset", "latest");

        Consumer<String, OrderPlacedEvent> consumidor =
                new DefaultKafkaConsumerFactory<String, OrderPlacedEvent>(propiedades)
                        .createConsumer();
        consumidor.subscribe(List.of(topic));
        return consumidor;
    }
}
