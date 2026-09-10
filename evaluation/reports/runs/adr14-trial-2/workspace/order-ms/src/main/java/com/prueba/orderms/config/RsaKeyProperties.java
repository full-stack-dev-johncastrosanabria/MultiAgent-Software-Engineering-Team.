package com.prueba.orderms.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.rsa")
public record RsaKeyProperties(String privateKeyPath, String publicKeyPath) {
}
