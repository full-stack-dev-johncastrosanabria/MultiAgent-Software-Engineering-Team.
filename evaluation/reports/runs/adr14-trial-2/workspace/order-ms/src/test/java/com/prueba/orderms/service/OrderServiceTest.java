package com.prueba.orderms.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.prueba.orderms.card.InvalidCardException;
import com.prueba.orderms.crypto.CryptoException;
import com.prueba.orderms.crypto.RsaCipherService;
import com.prueba.orderms.domain.Order;
import com.prueba.orderms.domain.OrderStatus;
import com.prueba.orderms.repository.OrderRepository;
import com.prueba.orderms.web.dto.CreateOrderRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class OrderServiceTest {

    private RsaCipherService cifrador;
    private OrderRepository repositorio;
    private OrderService servicio;

    @BeforeEach
    void preparar() throws Exception {
        KeyPairGenerator generador = KeyPairGenerator.getInstance("RSA");
        generador.initialize(2048);
        KeyPair par = generador.generateKeyPair();
        cifrador = new RsaCipherService(par.getPublic(), par.getPrivate());
        repositorio = mock(OrderRepository.class);
        when(repositorio.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));
        servicio = new OrderService(repositorio, cifrador, new ObjectMapper(),
                mock(org.springframework.context.ApplicationEventPublisher.class),
                mock(com.prueba.orderms.repository.ProcessedEventRepository.class));
    }

    private String tarjetaCifrada(String pan, int anio) {
        String json = """
                {"pan":"%s","cvv":"123","expiryMonth":12,"expiryYear":%d,"holder":"ANA TORRES"}
                """.formatted(pan, anio).strip();
        return cifrador.encrypt(json);
    }

    private CreateOrderRequest solicitud(String encryptedCard) {
        return new CreateOrderRequest(
                "Ana Torres", "ana@ejemplo.com",
                "SKU-1", "Teclado mecanico", 2,
                new BigDecimal("49.95"), "USD", encryptedCard);
    }

    @Test
    void creaUnPedidoPendienteConLaTarjetaEnmascarada() {
        Order pedido = servicio.crear(solicitud(tarjetaCifrada("4242424242424242", 2030)));

        assertThat(pedido.getStatus()).isEqualTo(OrderStatus.PENDIENTE);
        assertThat(pedido.getCardLastFour()).isEqualTo("4242");
        assertThat(pedido.getCardBrand()).isEqualTo("VISA");
        assertThat(pedido.getTotalAmount()).isEqualByComparingTo("99.90");
    }

    @Test
    void conservaElCriptogramaOriginalYNuncaElPanEnClaro() {
        String criptograma = tarjetaCifrada("4242424242424242", 2030);

        Order pedido = servicio.crear(solicitud(criptograma));

        assertThat(pedido.getEncryptedCardPayload()).isEqualTo(criptograma);
        assertThat(pedido.getEncryptedCardPayload()).doesNotContain("4242424242424242");
    }

    @Test
    void rechazaUnaTarjetaQueNoPasaLuhn() {
        assertThatThrownBy(() -> servicio.crear(solicitud(tarjetaCifrada("4242424242424243", 2030))))
                .isInstanceOf(InvalidCardException.class);
    }

    @Test
    void rechazaUnaTarjetaVencida() {
        assertThatThrownBy(() -> servicio.crear(solicitud(tarjetaCifrada("4242424242424242", 2020))))
                .isInstanceOf(InvalidCardException.class)
                .hasMessageContaining("vencida");
    }

    @Test
    void rechazaUnCriptogramaIlegible() {
        assertThatThrownBy(() -> servicio.crear(solicitud("Y3JpcHRvZ3JhbWEtaW52YWxpZG8=")))
                .isInstanceOf(CryptoException.class);
    }

    @Test
    void buscarPorIdLanzaCuandoElPedidoNoExiste() {
        UUID id = UUID.randomUUID();
        when(repositorio.findById(id)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> servicio.buscarPorId(id))
                .isInstanceOf(OrderNotFoundException.class)
                .hasMessageContaining(id.toString());
    }
}
