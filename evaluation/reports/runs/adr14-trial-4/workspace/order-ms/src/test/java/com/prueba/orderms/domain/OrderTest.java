package com.prueba.orderms.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OrderTest {

    private Order pedidoPendiente() {
        return Order.nuevo(
                "Ana Torres", "ana@ejemplo.com",
                "SKU-1", "Teclado", 2,
                new java.math.BigDecimal("49.95"), "USD",
                "ANA TORRES", "VISA", "4242", "criptograma");
    }

    @Test
    void unPedidoNuevoNaceEnPendienteConElTotalCalculado() {
        Order pedido = pedidoPendiente();

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PENDIENTE);
        assertThat(pedido.getTotalAmount()).isEqualByComparingTo("99.90");
        assertThat(pedido.getId()).isNotNull();
    }

    @Test
    void marcarPagadoTransicionaDesdePendiente() {
        Order pedido = pedidoPendiente();

        pedido.marcarPagado("PAY-123");

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PAGADO);
        assertThat(pedido.getPaymentReference()).isEqualTo("PAY-123");
        assertThat(pedido.getFailureReason()).isNull();
    }

    @Test
    void marcarFallidoTransicionaDesdePendiente() {
        Order pedido = pedidoPendiente();

        pedido.marcarFallido("Fondos insuficientes");

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.FALLO_PAGO);
        assertThat(pedido.getFailureReason()).isEqualTo("Fondos insuficientes");
    }

    @Test
    void unPedidoYaResueltoNoAceptaOtraTransicion() {
        Order pedido = pedidoPendiente();
        pedido.marcarPagado("PAY-123");

        assertThatThrownBy(() -> pedido.marcarFallido("tardio"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("PAGADO");
    }

    @Test
    void elTotalSeRedondeaADosDecimales() {
        Order pedido = Order.nuevo(
                "Ana", "ana@ejemplo.com", "SKU-2", "Cable", 3,
                new java.math.BigDecimal("10.333"), "USD",
                "ANA", "VISA", "4242", "criptograma");

        assertThat(pedido.getTotalAmount()).isEqualByComparingTo("31.00");
    }
}
