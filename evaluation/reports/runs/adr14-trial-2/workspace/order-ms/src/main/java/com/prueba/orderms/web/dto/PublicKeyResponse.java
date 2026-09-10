package com.prueba.orderms.web.dto;

public record PublicKeyResponse(
        String algorithm,
        int keySize,
        String format,
        String hash,
        String publicKey
) {
}
