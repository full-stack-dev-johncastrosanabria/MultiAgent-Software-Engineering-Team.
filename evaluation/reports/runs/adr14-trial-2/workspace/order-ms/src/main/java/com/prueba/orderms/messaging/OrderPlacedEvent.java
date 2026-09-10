package com.prueba.orderms.messaging;

import com.prueba.orderms.domain.Order;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

// El evento transporta solo datos enmascarados; PAN, CVV y criptograma nunca salen de OrderMS
public record OrderPlacedEvent(
        UUID eventId,
        UUID orderId,
        Instant occurredAt,
        BigDecimal amount,
        String currency,
        Customer customer,
        Card card
) {

    public record Customer(String name, String email) {
    }

    public record Card(String brand, String lastFour, String holder) {
    }

    public static OrderPlacedEvent desde(Order pedido) {
        return new OrderPlacedEvent(
                UUID.randomUUID(),
                pedido.getId(),
                Instant.now(),
                pedido.getTotalAmount(),
                pedido.getCurrency(),
                new Customer(pedido.getCustomerName(), pedido.getCustomerEmail()),
                new Card(pedido.getCardBrand(), pedido.getCardLastFour(), pedido.getCardHolder()));
    }
}
