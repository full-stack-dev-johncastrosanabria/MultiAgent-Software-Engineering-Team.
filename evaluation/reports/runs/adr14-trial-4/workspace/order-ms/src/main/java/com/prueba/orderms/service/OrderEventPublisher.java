package com.prueba.orderms.service;

import com.prueba.orderms.messaging.KafkaTopics;
import com.prueba.orderms.messaging.OrderPlacedEvent;
import com.prueba.orderms.observability.CorrelationIdConstants;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.nio.charset.StandardCharsets;

@Component
public class OrderEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(OrderEventPublisher.class);

    private final KafkaTemplate<String, Object> plantilla;

    public OrderEventPublisher(KafkaTemplate<String, Object> plantilla) {
        this.plantilla = plantilla;
    }

    // AFTER_COMMIT: si se publicara dentro de la transaccion, PaymentMS podria recibir un pedido que luego no se persistio
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void publicar(OrderCreatedDomainEvent evento) {
        OrderPlacedEvent mensaje = OrderPlacedEvent.desde(evento.pedido());
        String clave = evento.pedido().getId().toString();

        String correlationId = evento.correlationId();

        ProducerRecord<String, Object> registro =
                new ProducerRecord<>(KafkaTopics.ORDER_PLACED, clave, mensaje);
        registro.headers().add(CorrelationIdConstants.HEADER,
                correlationId.getBytes(StandardCharsets.UTF_8));

        // La confirmacion llega en el hilo de E/S del productor, que no hereda el MDC de la
        // peticion. Sin reponerlo, esta traza saldria sin correlacion y romperia el hilo de
        // seguimiento entre los dos microservicios.
        plantilla.send(registro).whenComplete((resultado, error) -> {
            MDC.put(CorrelationIdConstants.MDC_KEY, correlationId);
            try {
                if (error != null) {
                    log.error("No fue posible publicar order-placed para el pedido {}", clave, error);
                } else {
                    log.info("Evento order-placed publicado para el pedido {} en la particion {}",
                            clave, resultado.getRecordMetadata().partition());
                }
            } finally {
                MDC.remove(CorrelationIdConstants.MDC_KEY);
            }
        });
    }
}
