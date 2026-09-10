package com.prueba.orderms.card;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.assertj.core.api.Assertions.assertThat;

class CardBrandResolverTest {

    @ParameterizedTest
    @CsvSource({
            "4242424242424242, VISA",
            "4111111111111111, VISA",
            "5555555555554444, MASTERCARD",
            "5105105105105100, MASTERCARD",
            "2221000000000009, MASTERCARD",
            "2720999999999996, MASTERCARD",
            "378282246310005,  AMEX",
            "371449635398431,  AMEX",
            "6011111111111117, DESCONOCIDA",
            "9999999999999999, DESCONOCIDA"
    })
    void identificaLaMarcaSegunElRangoDelBin(String pan, CardBrand esperada) {
        assertThat(CardBrandResolver.resolve(pan)).isEqualTo(esperada);
    }

    @ParameterizedTest
    @CsvSource({"'', DESCONOCIDA", "'1', DESCONOCIDA"})
    void devuelveDesconocidaParaEntradasDemasiadoCortas(String pan, CardBrand esperada) {
        assertThat(CardBrandResolver.resolve(pan)).isEqualTo(esperada);
    }
}
