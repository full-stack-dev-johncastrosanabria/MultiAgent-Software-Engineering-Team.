package com.prueba.orderms.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prueba.orderms.card.CardData;
import com.prueba.orderms.crypto.CryptoException;
import com.prueba.orderms.crypto.RsaCipherService;
import com.prueba.orderms.domain.Order;
import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.domain.ProcessedEvent;
import com.prueba.orderms.messaging.PaymentProcessedEvent;
import com.prueba.orderms.observability.CorrelationIdConstants;
import com.prueba.orderms.repository.OrderRepository;
import com.prueba.orderms.repository.ProcessedEventRepository;
import com.prueba.orderms.web.dto.CreateOrderRequest;
import org.springframework.context.ApplicationEventPublisher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final OrderRepository repositorio;
    private final RsaCipherService cifrador;
    private final ObjectMapper mapeador;
    private final ApplicationEventPublisher publicador;
    private final ProcessedEventRepository repositorioDeEventos;

    public OrderService(OrderRepository repositorio,
                        RsaCipherService cifrador,
                        ObjectMapper mapeador,
                        ApplicationEventPublisher publicador,
                        ProcessedEventRepository repositorioDeEventos) {
        this.repositorio = repositorio;
        this.cifrador = cifrador;
        this.mapeador = mapeador;
        this.publicador = publicador;
        this.repositorioDeEventos = repositorioDeEventos;
    }

    @Transactional
    public Order crear(CreateOrderRequest solicitud) {
        CardData tarjeta = descifrarTarjeta(solicitud.encryptedCard());
        tarjeta.validar();

        Order pedido = Order.nuevo(
                solicitud.customerName(),
                solicitud.customerEmail(),
                solicitud.productSku(),
                solicitud.productName(),
                solicitud.quantity(),
                solicitud.unitPrice(),
                solicitud.currency(),
                tarjeta.holder(),
                tarjeta.brand().name(),
                tarjeta.lastFour(),
                solicitud.encryptedCard());

        // A partir de aqui la referencia a la tarjeta queda fuera de alcance; el CVV nunca se persiste
        Order guardado = repositorio.save(pedido);
        log.info("Pedido {} registrado en estado PENDIENTE por {} {}",
                guardado.getId(), guardado.getTotalAmount(), guardado.getCurrency());

        publicador.publishEvent(
                new OrderCreatedDomainEvent(guardado, CorrelationIdConstants.actual()));
        return guardado;
    }

    @Transactional(readOnly = true)
    public Order buscarPorId(UUID id) {
        return repositorio.findById(id).orElseThrow(() -> new OrderNotFoundException(id));
    }

    @Transactional(readOnly = true)
    public Page<Order> listar(OrderStatus estado, Pageable paginacion) {
        return estado == null
                ? repositorio.findAll(paginacion)
                : repositorio.findAllByStatus(estado, paginacion);
    }

    @Transactional
    public void aplicarResultadoDePago(PaymentProcessedEvent evento) {
        if (repositorioDeEventos.existsById(evento.eventId())) {
            log.debug("Evento {} ya procesado, se ignora", evento.eventId());
            return;
        }

        Order pedido = repositorio.findById(evento.orderId()).orElse(null);
        if (pedido == null) {
            log.warn("Se recibio un resultado de pago para el pedido inexistente {}", evento.orderId());
            return;
        }
        if (!pedido.estaPendiente()) {
            log.warn("El pedido {} ya esta en estado {}, se descarta el resultado tardio",
                    pedido.getId(), pedido.getStatus());
            return;
        }

        if (evento.fueAprobado()) {
            pedido.marcarPagado(evento.paymentReference());
        } else {
            pedido.marcarFallido(evento.failureReason());
        }
        repositorio.save(pedido);
        repositorioDeEventos.save(new ProcessedEvent(evento.eventId(), "order-ms"));

        log.info("Pedido {} actualizado a {}", pedido.getId(), pedido.getStatus());
    }

    private CardData descifrarTarjeta(String criptogramaBase64) {
        String json = cifrador.decrypt(criptogramaBase64);
        try {
            return mapeador.readValue(json, CardData.class);
        } catch (Exception e) {
            throw new CryptoException(
                    "El contenido descifrado no corresponde a datos de tarjeta validos", e);
        }
    }
}
