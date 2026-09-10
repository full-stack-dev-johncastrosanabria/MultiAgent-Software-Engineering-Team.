package com.prueba.orderms.service;

import com.prueba.orderms.domain.Order;

/** Evento interno de Spring; no sale del proceso. */
public record OrderCreatedDomainEvent(Order pedido, String correlationId) {
}
