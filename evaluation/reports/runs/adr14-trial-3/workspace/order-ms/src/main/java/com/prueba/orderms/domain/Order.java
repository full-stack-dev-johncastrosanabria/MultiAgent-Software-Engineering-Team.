package com.prueba.orderms.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "orders")
public class Order {

    @Id
    private UUID id;

    @Column(name = "customer_name", nullable = false)
    private String customerName;

    @Column(name = "customer_email", nullable = false)
    private String customerEmail;

    @Column(name = "product_sku", nullable = false)
    private String productSku;

    @Column(name = "product_name", nullable = false)
    private String productName;

    @Column(nullable = false)
    private Integer quantity;

    @Column(name = "unit_price", nullable = false)
    private BigDecimal unitPrice;

    @Column(name = "total_amount", nullable = false)
    private BigDecimal totalAmount;

    @Column(nullable = false, length = 3)
    private String currency;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private OrderStatus status;

    @Column(name = "card_holder", nullable = false)
    private String cardHolder;

    @Column(name = "card_brand", nullable = false)
    private String cardBrand;

    @Column(name = "card_last_four", nullable = false, length = 4)
    private String cardLastFour;

    @Column(name = "encrypted_card_payload", nullable = false, columnDefinition = "TEXT")
    private String encryptedCardPayload;

    @Column(name = "payment_reference")
    private String paymentReference;

    @Column(name = "failure_reason")
    private String failureReason;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Version
    private Long version;

    protected Order() {
        // Requerido por JPA
    }

    public static Order nuevo(String customerName, String customerEmail,
                              String productSku, String productName,
                              int quantity, BigDecimal unitPrice, String currency,
                              String cardHolder, String cardBrand, String cardLastFour,
                              String encryptedCardPayload) {
        Order pedido = new Order();
        pedido.id = UUID.randomUUID();
        pedido.customerName = customerName;
        pedido.customerEmail = customerEmail;
        pedido.productSku = productSku;
        pedido.productName = productName;
        pedido.quantity = quantity;
        pedido.unitPrice = unitPrice;
        pedido.totalAmount = unitPrice.multiply(BigDecimal.valueOf(quantity))
                .setScale(2, RoundingMode.HALF_UP);
        pedido.currency = currency;
        pedido.status = OrderStatus.PENDIENTE;
        pedido.cardHolder = cardHolder;
        pedido.cardBrand = cardBrand;
        pedido.cardLastFour = cardLastFour;
        pedido.encryptedCardPayload = encryptedCardPayload;
        pedido.createdAt = Instant.now();
        pedido.updatedAt = pedido.createdAt;
        return pedido;
    }

    public void marcarPagado(String referenciaDePago) {
        exigirPendiente();
        this.status = OrderStatus.PAGADO;
        this.paymentReference = referenciaDePago;
        this.updatedAt = Instant.now();
    }

    public void marcarFallido(String motivo) {
        exigirPendiente();
        this.status = OrderStatus.FALLO_PAGO;
        this.failureReason = motivo;
        this.updatedAt = Instant.now();
    }

    public boolean estaPendiente() {
        return status == OrderStatus.PENDIENTE;
    }

    private void exigirPendiente() {
        if (status != OrderStatus.PENDIENTE) {
            throw new IllegalStateException(
                    "El pedido %s ya se encuentra en estado %s".formatted(id, status));
        }
    }

    public UUID getId() { return id; }
    public String getCustomerName() { return customerName; }
    public String getCustomerEmail() { return customerEmail; }
    public String getProductSku() { return productSku; }
    public String getProductName() { return productName; }
    public Integer getQuantity() { return quantity; }
    public BigDecimal getUnitPrice() { return unitPrice; }
    public BigDecimal getTotalAmount() { return totalAmount; }
    public String getCurrency() { return currency; }
    public OrderStatus getStatus() { return status; }
    public String getCardHolder() { return cardHolder; }
    public String getCardBrand() { return cardBrand; }
    public String getCardLastFour() { return cardLastFour; }
    public String getEncryptedCardPayload() { return encryptedCardPayload; }
    public String getPaymentReference() { return paymentReference; }
    public String getFailureReason() { return failureReason; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
}
