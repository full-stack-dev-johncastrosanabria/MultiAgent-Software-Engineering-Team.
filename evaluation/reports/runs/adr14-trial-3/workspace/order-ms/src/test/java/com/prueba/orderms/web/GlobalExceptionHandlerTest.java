package com.prueba.orderms.web;

import com.prueba.orderms.card.InvalidCardException;
import com.prueba.orderms.crypto.CryptoException;
import com.prueba.orderms.service.OrderNotFoundException;
import com.prueba.orderms.service.OrderService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest({OrderController.class})
@Import(GlobalExceptionHandler.class)
class GlobalExceptionHandlerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private OrderService servicio;

    private static final String CUERPO_VALIDO = """
            {"customerName":"Ana","customerEmail":"ana@ejemplo.com","productSku":"SKU-1",
             "productName":"Teclado","quantity":1,"unitPrice":10.00,"currency":"USD",
             "encryptedCard":"Y2lmcmFkbw=="}
            """;

    @Test
    void devuelveProblemDetailConCuatrocientosCuatroCuandoNoExisteElPedido() throws Exception {
        UUID id = UUID.randomUUID();
        when(servicio.buscarPorId(id)).thenThrow(new OrderNotFoundException(id));

        mockMvc.perform(get("/api/v1/orders/{id}", id))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.title").value("Pedido no encontrado"))
                .andExpect(jsonPath("$.status").value(404));
    }

    @Test
    void devuelveCuatrocientosCuandoLaTarjetaEsInvalida() throws Exception {
        when(servicio.crear(any())).thenThrow(new InvalidCardException("La tarjeta esta vencida"));

        mockMvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO_VALIDO))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Datos de tarjeta invalidos"))
                .andExpect(jsonPath("$.detail").value("La tarjeta esta vencida"));
    }

    @Test
    void devuelveCuatrocientosCuandoElCriptogramaEsIlegible() throws Exception {
        when(servicio.crear(any())).thenThrow(new CryptoException("No fue posible descifrar"));

        mockMvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON).content(CUERPO_VALIDO))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Datos cifrados invalidos"));
    }

    @Test
    void detallaLosCamposInvalidosEnErroresDeValidacion() throws Exception {
        String cuerpoInvalido = """
                {"customerName":"","customerEmail":"no-es-correo","productSku":"SKU-1",
                 "productName":"Teclado","quantity":0,"unitPrice":10.00,"currency":"USD",
                 "encryptedCard":"Y2lmcmFkbw=="}
                """;

        mockMvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON).content(cuerpoInvalido))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Solicitud invalida"))
                .andExpect(jsonPath("$.errors").isMap());
    }

    // Las excepciones estandar de Spring MVC salian como 500 porque el handler de Exception
    // se adelantaba a DefaultHandlerExceptionResolver. Estos casos fijan su estado real.

    @Test
    void devuelveCuatrocientosCuatroCuandoLaRutaNoExiste() throws Exception {
        mockMvc.perform(get("/api/v1/no-existe"))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.title").value("Recurso no encontrado"))
                .andExpect(jsonPath("$.detail").value("No existe el recurso 'api/v1/no-existe' en esta API"));
    }

    @Test
    void devuelveCuatrocientosCincoConCabeceraAllowCuandoElMetodoNoEstaSoportado() throws Exception {
        mockMvc.perform(delete("/api/v1/orders/{id}", UUID.randomUUID()))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(header().string("Allow", "GET"))
                .andExpect(jsonPath("$.title").value("Metodo no permitido"))
                .andExpect(jsonPath("$.status").value(405));
    }

    @Test
    void devuelveCuatrocientosQuinceCuandoElTipoDeContenidoNoEstaSoportado() throws Exception {
        mockMvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.TEXT_PLAIN).content("hola"))
                .andExpect(status().isUnsupportedMediaType())
                .andExpect(jsonPath("$.title").value("Tipo de contenido no soportado"));
    }

    @Test
    void devuelveCuatrocientosCuandoElCuerpoNoEsJsonValido() throws Exception {
        mockMvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON).content("{roto"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Solicitud invalida"))
                .andExpect(jsonPath("$.detail").value("El cuerpo de la peticion esta ausente o no es un JSON valido"));
    }

    @Test
    void devuelveCuatrocientosCuandoFaltaElCuerpo() throws Exception {
        mockMvc.perform(post("/api/v1/orders").contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.title").value("Solicitud invalida"));
    }
}
