package com.prueba.orderms.card;

public class InvalidCardException extends RuntimeException {

    public InvalidCardException(String mensaje) {
        super(mensaje);
    }
}
