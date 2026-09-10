package com.prueba.orderms.web;

import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.service.OrderService;
import com.prueba.orderms.web.dto.CreateOrderRequest;
import com.prueba.orderms.web.dto.OrderResponse;
import com.prueba.orderms.web.dto.PagedResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/orders")
@Tag(name = "Pedidos", description = "Creacion y consulta de pedidos")
public class OrderController {

    private final OrderService servicio;

    public OrderController(OrderService servicio) {
        this.servicio = servicio;
    }

    @PostMapping
    @Operation(summary = "Crear un pedido",
            description = "Los datos de tarjeta deben llegar cifrados con la llave publica "
                    + "que expone /api/v1/crypto/public-key.")
    public ResponseEntity<OrderResponse> crear(@Valid @RequestBody CreateOrderRequest solicitud,
                                               UriComponentsBuilder constructorDeUri) {
        OrderResponse respuesta = OrderResponse.desde(servicio.crear(solicitud));
        URI ubicacion = constructorDeUri.path("/api/v1/orders/{id}")
                .buildAndExpand(respuesta.id())
                .toUri();
        return ResponseEntity.created(ubicacion).body(respuesta);
    }

    @GetMapping("/{id}")
    @Operation(summary = "Consultar un pedido por su identificador")
    public OrderResponse porId(@PathVariable UUID id) {
        return OrderResponse.desde(servicio.buscarPorId(id));
    }

    @GetMapping
    @Operation(summary = "Listar pedidos",
            description = "Ordenados por fecha de creacion descendente. "
                    + "El parametro status permite filtrar por estado.")
    public PagedResponse<OrderResponse> listar(
            @RequestParam(required = false) OrderStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {

        int tamanoAcotado = Math.min(Math.max(size, 1), 100);
        PageRequest paginacion = PageRequest.of(
                Math.max(page, 0), tamanoAcotado, Sort.by(Sort.Direction.DESC, "createdAt"));

        return PagedResponse.desde(servicio.listar(status, paginacion), OrderResponse::desde);
    }
}
