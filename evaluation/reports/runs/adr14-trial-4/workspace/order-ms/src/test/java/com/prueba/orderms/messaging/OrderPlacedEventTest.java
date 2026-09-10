package com.prueba.orderms.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.prueba.orderms.domain.Order;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

class OrderPlacedEventTest {

    private final ObjectMapper mapeador = new ObjectMapper().registerModule(new JavaTimeModule());

    private Order pedido() {
        return Order.nuevo("Ana Torres", "ana@ejemplo.com", "SKU-1", "Teclado", 2,
                new BigDecimal("49.95"), "USD", "ANA TORRES", "VISA", "4242",
                "Y3JpcHRvZ3JhbWEtY29uLXBhbi1jb21wbGV0bw==");
    }

    @Test
    void construyeElEventoDesdeElPedido() {
        Order pedido = pedido();

        OrderPlacedEvent evento = OrderPlacedEvent.desde(pedido);

        assertThat(evento.orderId()).isEqualTo(pedido.getId());
        assertThat(evento.amount()).isEqualByComparingTo("99.90");
        assertThat(evento.currency()).isEqualTo("USD");
        assertThat(evento.card().lastFour()).isEqualTo("4242");
        assertThat(evento.card().brand()).isEqualTo("VISA");
        assertThat(evento.eventId()).isNotNull();
    }

    @Test
    void elEventoSerializadoNoContieneElCriptogramaNiDatosSensibles() throws Exception {
        Order pedido = pedido();

        String json = mapeador.writeValueAsString(OrderPlacedEvent.desde(pedido));

        assertThat(json).doesNotContain(pedido.getEncryptedCardPayload());
        assertThat(json).doesNotContain("cvv");
        assertThat(json).doesNotContain("pan");
        assertThat(json).contains("4242");
    }
}
