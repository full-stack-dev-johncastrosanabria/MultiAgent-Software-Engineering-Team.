package com.prueba.orderms.web;

import com.prueba.orderms.domain.Order;
import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.service.OrderNotFoundException;
import com.prueba.orderms.service.OrderService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(OrderController.class)
class OrderControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private OrderService servicio;

    private Order pedidoDeEjemplo() {
        return Order.nuevo("Ana Torres", "ana@ejemplo.com", "SKU-1", "Teclado", 2,
                new BigDecimal("49.95"), "USD", "ANA TORRES", "VISA", "4242", "criptograma");
    }

    @Test
    void devuelveElPedidoSolicitado() throws Exception {
        Order pedido = pedidoDeEjemplo();
        when(servicio.buscarPorId(pedido.getId())).thenReturn(pedido);

        mockMvc.perform(get("/api/v1/orders/{id}", pedido.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(pedido.getId().toString()))
                .andExpect(jsonPath("$.status").value("PENDIENTE"))
                .andExpect(jsonPath("$.cardLastFour").value("4242"));
    }

    @Test
    void nuncaExponeElCriptogramaDeLaTarjeta() throws Exception {
        Order pedido = pedidoDeEjemplo();
        when(servicio.buscarPorId(pedido.getId())).thenReturn(pedido);

        mockMvc.perform(get("/api/v1/orders/{id}", pedido.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.encryptedCardPayload").doesNotExist());
    }

    @Test
    void devuelveUnaPaginaDePedidos() throws Exception {
        Page<Order> pagina = new PageImpl<>(List.of(pedidoDeEjemplo()), PageRequest.of(0, 20), 1);
        when(servicio.listar(eq(null), any(Pageable.class))).thenReturn(pagina);

        mockMvc.perform(get("/api/v1/orders"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content").isArray())
                .andExpect(jsonPath("$.totalElements").value(1))
                .andExpect(jsonPath("$.page").value(0));
    }

    @Test
    void filtraPorEstadoCuandoSeIndica() throws Exception {
        Page<Order> pagina = new PageImpl<>(List.of(), PageRequest.of(0, 20), 0);
        when(servicio.listar(eq(OrderStatus.PAGADO), any(Pageable.class))).thenReturn(pagina);

        mockMvc.perform(get("/api/v1/orders").param("status", "PAGADO"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalElements").value(0));
    }

    @Test
    void devuelveNotFoundCuandoElPedidoNoExiste() throws Exception {
        UUID id = UUID.randomUUID();
        when(servicio.buscarPorId(id)).thenThrow(new OrderNotFoundException(id));

        mockMvc.perform(get("/api/v1/orders/{id}", id))
                .andExpect(status().isNotFound());
    }
}
