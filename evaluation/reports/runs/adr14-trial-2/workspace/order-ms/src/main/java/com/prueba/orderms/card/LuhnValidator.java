package com.prueba.orderms.card;

public final class LuhnValidator {

    private static final int LONGITUD_MINIMA = 13;
    private static final int LONGITUD_MAXIMA = 19;

    private LuhnValidator() {
    }

    public static boolean isValid(String pan) {
        if (pan == null || pan.length() < LONGITUD_MINIMA || pan.length() > LONGITUD_MAXIMA) {
            return false;
        }
        int suma = 0;
        boolean seDuplica = false;
        for (int i = pan.length() - 1; i >= 0; i--) {
            char caracter = pan.charAt(i);
            if (caracter < '0' || caracter > '9') {
                return false;
            }
            int digito = caracter - '0';
            if (seDuplica) {
                digito *= 2;
                if (digito > 9) {
                    digito -= 9;
                }
            }
            suma += digito;
            seDuplica = !seDuplica;
        }
        return suma % 10 == 0;
    }
}
