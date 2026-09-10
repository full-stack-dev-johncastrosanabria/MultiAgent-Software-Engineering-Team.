package com.prueba.orderms.messaging;

import com.prueba.orderms.observability.CorrelationIdConstants;
import com.prueba.orderms.service.OrderService;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

@Component
public class PaymentProcessedListener {

    private static final Logger log = LoggerFactory.getLogger(PaymentProcessedListener.class);

    private final OrderService servicio;

    public PaymentProcessedListener(OrderService servicio) {
        this.servicio = servicio;
    }

    @KafkaListener(topics = KafkaTopics.PAYMENT_PROCESSED, groupId = "order-ms")
    public void alRecibirResultado(ConsumerRecord<String, PaymentProcessedEvent> registro) {
        var cabecera = registro.headers().lastHeader(CorrelationIdConstants.HEADER);
        String correlationId = cabecera != null
                ? new String(cabecera.value(), StandardCharsets.UTF_8)
                : UUID.randomUUID().toString();

        MDC.put(CorrelationIdConstants.MDC_KEY, correlationId);
        try {
            PaymentProcessedEvent evento = registro.value();
            log.info("Resultado de pago recibido para el pedido {}: {}",
                    evento.orderId(), evento.status());
            servicio.aplicarResultadoDePago(evento);
        } finally {
            MDC.remove(CorrelationIdConstants.MDC_KEY);
        }
    }
}
