package com.prueba.orderms.web;

import com.prueba.orderms.crypto.RsaCipherService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

import java.security.KeyPair;
import java.security.KeyPairGenerator;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CryptoController.class)
@Import(CryptoControllerTest.CifradorDePrueba.class)
class CryptoControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @TestConfiguration
    static class CifradorDePrueba {
        @Bean
        RsaCipherService rsaCipherService() throws Exception {
            KeyPairGenerator generador = KeyPairGenerator.getInstance("RSA");
            generador.initialize(2048);
            KeyPair par = generador.generateKeyPair();
            return new RsaCipherService(par.getPublic(), par.getPrivate());
        }
    }

    @Test
    void devuelveLaLlavePublicaEnFormatoSpki() throws Exception {
        mockMvc.perform(get("/api/v1/crypto/public-key"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.algorithm").value("RSA-OAEP"))
                .andExpect(jsonPath("$.keySize").value(2048))
                .andExpect(jsonPath("$.format").value("SPKI"))
                .andExpect(jsonPath("$.hash").value("SHA-256"))
                .andExpect(jsonPath("$.publicKey").isNotEmpty());
    }
}
