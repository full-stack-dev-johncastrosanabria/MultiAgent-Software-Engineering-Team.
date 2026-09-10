package com.prueba.orderms.web.dto;

import com.prueba.orderms.domain.Order;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

// encryptedCardPayload deliberadamente excluido: nunca se expone en respuestas
public record OrderResponse(
        UUID id,
        String customerName,
        String customerEmail,
        String productSku,
        String productName,
        Integer quantity,
        BigDecimal unitPrice,
        BigDecimal totalAmount,
        String currency,
        String status,
        String cardBrand,
        String cardLastFour,
        String paymentReference,
        String failureReason,
        Instant createdAt,
        Instant updatedAt
) {

    public static OrderResponse desde(Order pedido) {
        return new OrderResponse(
                pedido.getId(),
                pedido.getCustomerName(),
                pedido.getCustomerEmail(),
                pedido.getProductSku(),
                pedido.getProductName(),
                pedido.getQuantity(),
                pedido.getUnitPrice(),
                pedido.getTotalAmount(),
                pedido.getCurrency(),
                pedido.getStatus().name(),
                pedido.getCardBrand(),
                pedido.getCardLastFour(),
                pedido.getPaymentReference(),
                pedido.getFailureReason(),
                pedido.getCreatedAt(),
                pedido.getUpdatedAt());
    }
}
