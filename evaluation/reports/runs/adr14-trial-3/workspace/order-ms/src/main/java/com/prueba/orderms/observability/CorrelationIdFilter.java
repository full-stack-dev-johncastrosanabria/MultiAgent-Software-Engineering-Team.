package com.prueba.orderms.observability;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class CorrelationIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest solicitud,
                                    HttpServletResponse respuesta,
                                    FilterChain cadena) throws ServletException, IOException {
        String identificador = solicitud.getHeader(CorrelationIdConstants.HEADER);
        if (!StringUtils.hasText(identificador)) {
            identificador = UUID.randomUUID().toString();
        }
        MDC.put(CorrelationIdConstants.MDC_KEY, identificador);
        respuesta.setHeader(CorrelationIdConstants.HEADER, identificador);
        try {
            cadena.doFilter(solicitud, respuesta);
        } finally {
            // Los contenedores reutilizan hilos: sin esta limpieza el siguiente pedido heredaria el identificador anterior
            MDC.remove(CorrelationIdConstants.MDC_KEY);
        }
    }
}
