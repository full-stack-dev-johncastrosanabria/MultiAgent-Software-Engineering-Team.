package com.prueba.orderms.observability;

import org.slf4j.MDC;

import java.util.UUID;

public final class CorrelationIdConstants {

    public static final String HEADER = "X-Correlation-Id";
    public static final String MDC_KEY = "correlationId";

    private CorrelationIdConstants() {
    }

    public static String actual() {
        String valor = MDC.get(MDC_KEY);
        return valor != null ? valor : UUID.randomUUID().toString();
    }
}
