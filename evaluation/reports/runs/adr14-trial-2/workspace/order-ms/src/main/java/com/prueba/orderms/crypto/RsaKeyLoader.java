package com.prueba.orderms.crypto;

import com.prueba.orderms.config.RsaKeyProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

@Configuration
@EnableConfigurationProperties(RsaKeyProperties.class)
public class RsaKeyLoader {

    private static final Logger log = LoggerFactory.getLogger(RsaKeyLoader.class);
    private static final int TAMANO_DE_LLAVE = 2048;

    @Bean
    public RsaCipherService rsaCipherService(RsaKeyProperties propiedades) {
        if (!StringUtils.hasText(propiedades.privateKeyPath())
                || !StringUtils.hasText(propiedades.publicKeyPath())) {
            return conParEfimero("no se configuraron rutas de llaves");
        }
        Path rutaPrivada = Path.of(propiedades.privateKeyPath());
        Path rutaPublica = Path.of(propiedades.publicKeyPath());
        if (!Files.exists(rutaPrivada) || !Files.exists(rutaPublica)) {
            return conParEfimero("las rutas configuradas no existen en el sistema de archivos");
        }
        try {
            PrivateKey privada = leerLlavePrivada(rutaPrivada);
            PublicKey publica = leerLlavePublica(rutaPublica);
            log.info("Llaves RSA cargadas desde disco");
            return new RsaCipherService(publica, privada);
        } catch (Exception e) {
            throw new CryptoException("No fue posible cargar las llaves RSA configuradas", e);
        }
    }

    private RsaCipherService conParEfimero(String motivo) {
        log.warn("Generando un par RSA efimero porque {}. Los pedidos creados en este arranque "
                + "no seran descifrables tras un reinicio. Ejecute scripts/generate-keys.sh "
                + "y monte las llaves para un uso serio.", motivo);
        try {
            KeyPairGenerator generador = KeyPairGenerator.getInstance("RSA");
            generador.initialize(TAMANO_DE_LLAVE);
            KeyPair par = generador.generateKeyPair();
            return new RsaCipherService(par.getPublic(), par.getPrivate());
        } catch (Exception e) {
            throw new CryptoException("No fue posible generar un par RSA efimero", e);
        }
    }

    private PrivateKey leerLlavePrivada(Path ruta) throws Exception {
        byte[] der = decodificarPem(Files.readString(ruta));
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
    }

    private PublicKey leerLlavePublica(Path ruta) throws Exception {
        byte[] der = decodificarPem(Files.readString(ruta));
        return KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));
    }

    private byte[] decodificarPem(String contenido) {
        String cuerpo = contenido
                .replaceAll("-----BEGIN [A-Z ]+-----", "")
                .replaceAll("-----END [A-Z ]+-----", "")
                .replaceAll("\\s", "");
        return Base64.getDecoder().decode(cuerpo);
    }
}
