package com.prueba.orderms.observability;

import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;

class CorrelationIdFilterTest {

    private final CorrelationIdFilter filtro = new CorrelationIdFilter();

    @Test
    void conservaElIdentificadorEnviadoPorElCliente() throws Exception {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.addHeader(CorrelationIdConstants.HEADER, "abc-123");
        MockHttpServletResponse respuesta = new MockHttpServletResponse();

        String[] visto = new String[1];
        FilterChain cadena = mock(FilterChain.class);
        doAnswer(inv -> {
            visto[0] = MDC.get(CorrelationIdConstants.MDC_KEY);
            return null;
        }).when(cadena).doFilter(solicitud, respuesta);

        filtro.doFilter(solicitud, respuesta, cadena);

        assertThat(visto[0]).isEqualTo("abc-123");
        assertThat(respuesta.getHeader(CorrelationIdConstants.HEADER)).isEqualTo("abc-123");
    }

    @Test
    void generaUnIdentificadorCuandoElClienteNoLoEnvia() throws Exception {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        MockHttpServletResponse respuesta = new MockHttpServletResponse();
        FilterChain cadena = mock(FilterChain.class);

        filtro.doFilter(solicitud, respuesta, cadena);

        assertThat(respuesta.getHeader(CorrelationIdConstants.HEADER)).isNotBlank();
    }

    @Test
    void limpiaElContextoDeDiagnosticoAlTerminar() throws Exception {
        MockHttpServletRequest solicitud = new MockHttpServletRequest();
        solicitud.addHeader(CorrelationIdConstants.HEADER, "abc-123");
        FilterChain cadena = mock(FilterChain.class);

        filtro.doFilter(solicitud, new MockHttpServletResponse(), cadena);

        // Sin limpieza, el hilo reutilizado arrastraria el identificador del pedido anterior
        assertThat(MDC.get(CorrelationIdConstants.MDC_KEY)).isNull();
    }
}
