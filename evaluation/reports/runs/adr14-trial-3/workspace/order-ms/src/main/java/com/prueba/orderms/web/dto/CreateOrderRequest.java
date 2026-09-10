package com.prueba.orderms.web.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;

public record CreateOrderRequest(

        @NotBlank(message = "El nombre del cliente es obligatorio")
        @Size(max = 120)
        String customerName,

        @NotBlank(message = "El correo del cliente es obligatorio")
        @Email(message = "El correo del cliente no tiene un formato valido")
        @Size(max = 180)
        String customerEmail,

        @NotBlank(message = "El SKU del producto es obligatorio")
        @Size(max = 60)
        String productSku,

        @NotBlank(message = "El nombre del producto es obligatorio")
        @Size(max = 160)
        String productName,

        @NotNull(message = "La cantidad es obligatoria")
        @Min(value = 1, message = "La cantidad debe ser al menos 1")
        Integer quantity,

        @NotNull(message = "El precio unitario es obligatorio")
        @DecimalMin(value = "0.01", message = "El precio unitario debe ser mayor que cero")
        BigDecimal unitPrice,

        @NotBlank(message = "La moneda es obligatoria")
        @Pattern(regexp = "[A-Z]{3}", message = "La moneda debe seguir el formato ISO 4217")
        String currency,

        @NotBlank(message = "Los datos de tarjeta cifrados son obligatorios")
        String encryptedCard
) {
}
