package com.prueba.orderms.card;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class LuhnValidatorTest {

    @ParameterizedTest
    @ValueSource(strings = {
            "4242424242424242",
            "5555555555554444",
            "378282246310005",
            "4111111111111111"
    })
    void aceptaNumerosConDigitoVerificadorCorrecto(String pan) {
        assertThat(LuhnValidator.isValid(pan)).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "4242424242424243",
            "1234567812345678",
            "0000000000000001"
    })
    void rechazaNumerosConDigitoVerificadorIncorrecto(String pan) {
        assertThat(LuhnValidator.isValid(pan)).isFalse();
    }

    @ParameterizedTest
    @ValueSource(strings = {"424242424242424a", "4242 4242 4242 4242", "", "   "})
    void rechazaValoresQueNoSonSecuenciasDeDigitos(String pan) {
        assertThat(LuhnValidator.isValid(pan)).isFalse();
    }

    @Test
    void rechazaValorNulo() {
        assertThat(LuhnValidator.isValid(null)).isFalse();
    }

    @ParameterizedTest
    @ValueSource(strings = {"400000000000", "40000000000000000000"})
    void rechazaLongitudesFueraDelRangoDeTrecaADiecinueve(String pan) {
        assertThat(LuhnValidator.isValid(pan)).isFalse();
    }
}
