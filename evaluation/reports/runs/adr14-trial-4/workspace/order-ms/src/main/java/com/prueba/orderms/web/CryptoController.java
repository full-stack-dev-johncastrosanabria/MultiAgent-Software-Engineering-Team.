package com.prueba.orderms.web;

import com.prueba.orderms.crypto.RsaCipherService;
import com.prueba.orderms.web.dto.PublicKeyResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/crypto")
@Tag(name = "Criptografia", description = "Material publico para cifrar datos sensibles")
public class CryptoController {

    private final RsaCipherService cifrador;

    public CryptoController(RsaCipherService cifrador) {
        this.cifrador = cifrador;
    }

    @GetMapping("/public-key")
    @Operation(summary = "Obtener la llave publica",
            description = "Devuelve la llave en formato SPKI codificada en base64, lista para "
                    + "importarse con crypto.subtle.importKey en el navegador.")
    public PublicKeyResponse llavePublica() {
        return new PublicKeyResponse(
                "RSA-OAEP",
                cifrador.keySize(),
                "SPKI",
                "SHA-256",
                cifrador.publicKeyBase64());
    }
}
