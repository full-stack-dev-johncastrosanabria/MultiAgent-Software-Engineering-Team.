package com.prueba.orderms.crypto;

public class CryptoException extends RuntimeException {

    public CryptoException(String mensaje) {
        super(mensaje);
    }

    public CryptoException(String mensaje, Throwable causa) {
        super(mensaje, causa);
    }
}
