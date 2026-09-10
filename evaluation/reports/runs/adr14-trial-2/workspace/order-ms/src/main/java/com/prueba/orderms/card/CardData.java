package com.prueba.orderms.card;

import java.time.YearMonth;

public record CardData(String pan, String cvv, int expiryMonth, int expiryYear, String holder) {

    public void validar() {
        if (!LuhnValidator.isValid(pan)) {
            throw new InvalidCardException("El numero de tarjeta no es valido");
        }
        if (cvv == null || !cvv.matches("\\d{3,4}")) {
            throw new InvalidCardException("El codigo de seguridad debe tener 3 o 4 digitos");
        }
        if (expiryMonth < 1 || expiryMonth > 12) {
            throw new InvalidCardException("El mes de expiracion debe estar entre 1 y 12");
        }
        if (YearMonth.of(expiryYear, expiryMonth).isBefore(YearMonth.now())) {
            throw new InvalidCardException("La tarjeta esta vencida");
        }
        if (holder == null || holder.isBlank()) {
            throw new InvalidCardException("El titular de la tarjeta es obligatorio");
        }
    }

    public String lastFour() {
        return pan.substring(pan.length() - 4);
    }

    public CardBrand brand() {
        return CardBrandResolver.resolve(pan);
    }

    @Override
    public String toString() {
        // Nunca exponer el PAN ni el CVV a traves de logs o mensajes de error
        return "CardData[brand=%s, lastFour=%s]".formatted(brand(), lastFour());
    }
}
