package com.prueba.orderms.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prueba.orderms.crypto.RsaCipherService;
import com.prueba.orderms.domain.Order;
import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.domain.ProcessedEvent;
import com.prueba.orderms.messaging.PaymentProcessedEvent;
import com.prueba.orderms.repository.OrderRepository;
import com.prueba.orderms.repository.ProcessedEventRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderServiceStatusTest {

    private OrderRepository repositorio;
    private ProcessedEventRepository repositorioDeEventos;
    private OrderService servicio;
    private Order pedido;

    @BeforeEach
    void preparar() {
        repositorio = mock(OrderRepository.class);
        repositorioDeEventos = mock(ProcessedEventRepository.class);
        when(repositorio.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));
        when(repositorioDeEventos.existsById(any(UUID.class))).thenReturn(false);

        servicio = new OrderService(repositorio, mock(RsaCipherService.class),
                new ObjectMapper(), mock(ApplicationEventPublisher.class), repositorioDeEventos);

        pedido = Order.nuevo("Ana", "ana@ejemplo.com", "SKU-1", "Teclado", 1,
                new BigDecimal("10.00"), "USD", "ANA", "VISA", "4242", "criptograma");
        when(repositorio.findById(pedido.getId())).thenReturn(Optional.of(pedido));
    }

    private PaymentProcessedEvent evento(String estado, String referencia, String motivo) {
        return new PaymentProcessedEvent(UUID.randomUUID(), pedido.getId(), Instant.now(),
                estado, referencia, motivo);
    }

    @Test
    void unResultadoAprobadoDejaElPedidoPagado() {
        servicio.aplicarResultadoDePago(evento("APROBADO", "PAY-1", null));

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PAGADO);
        assertThat(pedido.getPaymentReference()).isEqualTo("PAY-1");
    }

    @Test
    void unResultadoRechazadoDejaElPedidoEnFalloDePago() {
        servicio.aplicarResultadoDePago(evento("RECHAZADO", null, "Fondos insuficientes"));

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.FALLO_PAGO);
        assertThat(pedido.getFailureReason()).isEqualTo("Fondos insuficientes");
    }

    @Test
    void unEventoYaProcesadoNoSeVuelveAAplicar() {
        PaymentProcessedEvent repetido = evento("APROBADO", "PAY-1", null);
        when(repositorioDeEventos.existsById(repetido.eventId())).thenReturn(true);

        servicio.aplicarResultadoDePago(repetido);

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PENDIENTE);
        verify(repositorio, never()).save(any(Order.class));
    }

    @Test
    void unEventoTardioSobreUnPedidoResueltoSeDescartaSinError() {
        servicio.aplicarResultadoDePago(evento("APROBADO", "PAY-1", null));

        // Un segundo evento con otro identificador llega tarde sobre un pedido ya cerrado
        servicio.aplicarResultadoDePago(evento("RECHAZADO", null, "tardio"));

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PAGADO);
    }

    @Test
    void unEventoSobreUnPedidoInexistenteSeDescartaSinError() {
        UUID desconocido = UUID.randomUUID();
        when(repositorio.findById(desconocido)).thenReturn(Optional.empty());

        servicio.aplicarResultadoDePago(new PaymentProcessedEvent(
                UUID.randomUUID(), desconocido, Instant.now(), "APROBADO", "PAY-9", null));

        verify(repositorioDeEventos, never()).save(any(ProcessedEvent.class));
    }
}
