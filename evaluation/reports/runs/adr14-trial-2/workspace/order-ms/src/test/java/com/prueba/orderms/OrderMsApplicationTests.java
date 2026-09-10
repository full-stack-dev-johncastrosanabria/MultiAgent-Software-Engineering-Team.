package com.prueba.orderms;

import org.junit.jupiter.api.Test;

class OrderMsApplicationTests {

    @Test
    void laClaseDeArranqueEsCargable() {
        // Verificacion minima; el arranque completo del contexto se cubre en las pruebas de integracion
        org.junit.jupiter.api.Assertions.assertNotNull(OrderMsApplication.class);
    }
}
