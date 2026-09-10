package com.prueba.orderms.card;

public final class CardBrandResolver {

    private CardBrandResolver() {
    }

    public static CardBrand resolve(String pan) {
        if (pan == null || pan.length() < 2) {
            return CardBrand.DESCONOCIDA;
        }
        if (pan.startsWith("4")) {
            return CardBrand.VISA;
        }
        if (pan.startsWith("34") || pan.startsWith("37")) {
            return CardBrand.AMEX;
        }
        if (esMastercard(pan)) {
            return CardBrand.MASTERCARD;
        }
        return CardBrand.DESCONOCIDA;
    }

    private static boolean esMastercard(String pan) {
        int dosPrimeros = enteroDePrefijo(pan, 2);
        if (dosPrimeros >= 51 && dosPrimeros <= 55) {
            return true;
        }
        if (pan.length() < 4) {
            return false;
        }
        int cuatroPrimeros = enteroDePrefijo(pan, 4);
        return cuatroPrimeros >= 2221 && cuatroPrimeros <= 2720;
    }

    private static int enteroDePrefijo(String pan, int longitud) {
        try {
            return Integer.parseInt(pan.substring(0, longitud));
        } catch (NumberFormatException e) {
            return -1;
        }
    }
}
