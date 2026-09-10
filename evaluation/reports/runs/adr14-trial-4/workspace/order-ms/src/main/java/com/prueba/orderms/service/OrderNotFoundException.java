package com.prueba.orderms.service;

import java.util.UUID;

public class OrderNotFoundException extends RuntimeException {

    public OrderNotFoundException(UUID id) {
        super("No existe un pedido con identificador %s".formatted(id));
    }
}
