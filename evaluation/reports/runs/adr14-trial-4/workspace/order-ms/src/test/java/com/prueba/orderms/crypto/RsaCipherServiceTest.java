package com.prueba.orderms.crypto;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.security.KeyPair;
import java.security.KeyPairGenerator;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class RsaCipherServiceTest {

    private static RsaCipherService servicio;

    @BeforeAll
    static void generarParDePruebas() throws Exception {
        KeyPairGenerator generador = KeyPairGenerator.getInstance("RSA");
        generador.initialize(2048);
        KeyPair par = generador.generateKeyPair();
        servicio = new RsaCipherService(par.getPublic(), par.getPrivate());
    }

    @Test
    void cifraYDescifraElMismoTexto() {
        String original = "{\"pan\":\"4242424242424242\",\"cvv\":\"123\"}";

        String cifrado = servicio.encrypt(original);
        String descifrado = servicio.decrypt(cifrado);

        assertThat(cifrado).isNotEqualTo(original);
        assertThat(descifrado).isEqualTo(original);
    }

    @Test
    void produceCriptogramasDistintosParaElMismoTexto() {
        // OAEP incluye relleno aleatorio: dos cifrados del mismo texto no deben coincidir
        String original = "dato sensible";

        assertThat(servicio.encrypt(original)).isNotEqualTo(servicio.encrypt(original));
    }

    @Test
    void rechazaUnCriptogramaCorrupto() {
        assertThatThrownBy(() -> servicio.decrypt("bm8tZXMtdW4tY3JpcHRvZ3JhbWE="))
                .isInstanceOf(CryptoException.class)
                .hasMessageContaining("No fue posible descifrar");
    }

    @Test
    void rechazaUnaCadenaQueNoEsBase64() {
        assertThatThrownBy(() -> servicio.decrypt("$$$ no es base64 $$$"))
                .isInstanceOf(CryptoException.class);
    }

    @Test
    void rechazaTextoQueExcedeLaCapacidadDeLaLlave() {
        // RSA-2048 con OAEP-SHA256 admite 190 bytes como maximo
        String excesivo = "x".repeat(191);

        assertThatThrownBy(() -> servicio.encrypt(excesivo))
                .isInstanceOf(CryptoException.class)
                .hasMessageContaining("excede");
    }

    @Test
    void exponeLaLlavePublicaEnFormatoSpki() {
        String publica = servicio.publicKeyBase64();

        assertThat(publica).isNotBlank();
        assertThat(java.util.Base64.getDecoder().decode(publica)).isNotEmpty();
    }
}
