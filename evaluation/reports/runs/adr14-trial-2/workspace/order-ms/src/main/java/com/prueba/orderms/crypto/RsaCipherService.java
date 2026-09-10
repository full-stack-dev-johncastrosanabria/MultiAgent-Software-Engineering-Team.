package com.prueba.orderms.crypto;

import javax.crypto.Cipher;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.interfaces.RSAKey;
import java.security.spec.MGF1ParameterSpec;
import java.util.Base64;

public class RsaCipherService {

    private static final String TRANSFORMACION = "RSA/ECB/OAEPWithSHA-256AndMGF1Padding";

    private final PublicKey llavePublica;
    private final PrivateKey llavePrivada;
    private final int capacidadMaximaEnBytes;

    public RsaCipherService(PublicKey llavePublica, PrivateKey llavePrivada) {
        this.llavePublica = llavePublica;
        this.llavePrivada = llavePrivada;
        this.capacidadMaximaEnBytes = calcularCapacidadMaxima(llavePublica);
    }

    public String encrypt(String textoPlano) {
        byte[] datos = textoPlano.getBytes(StandardCharsets.UTF_8);
        if (datos.length > capacidadMaximaEnBytes) {
            throw new CryptoException(
                    "El texto de %d bytes excede la capacidad de %d bytes de la llave"
                            .formatted(datos.length, capacidadMaximaEnBytes));
        }
        try {
            Cipher cifrador = Cipher.getInstance(TRANSFORMACION);
            cifrador.init(Cipher.ENCRYPT_MODE, llavePublica, parametrosOaep());
            return Base64.getEncoder().encodeToString(cifrador.doFinal(datos));
        } catch (Exception e) {
            throw new CryptoException("No fue posible cifrar los datos", e);
        }
    }

    public String decrypt(String criptogramaBase64) {
        byte[] criptograma;
        try {
            criptograma = Base64.getDecoder().decode(criptogramaBase64);
        } catch (IllegalArgumentException e) {
            throw new CryptoException("No fue posible descifrar: el valor no es base64 valido", e);
        }
        try {
            Cipher cifrador = Cipher.getInstance(TRANSFORMACION);
            cifrador.init(Cipher.DECRYPT_MODE, llavePrivada, parametrosOaep());
            return new String(cifrador.doFinal(criptograma), StandardCharsets.UTF_8);
        } catch (Exception e) {
            // El detalle no se propaga al cliente para no habilitar un oraculo de descifrado
            throw new CryptoException("No fue posible descifrar los datos de tarjeta", e);
        }
    }

    public String publicKeyBase64() {
        return Base64.getEncoder().encodeToString(llavePublica.getEncoded());
    }

    public int keySize() {
        return ((RSAKey) llavePublica).getModulus().bitLength();
    }

    // OAEPParameterSpec explicito: Java aplica SHA-1 a MGF1 por defecto; Web Crypto usa SHA-256
    private static OAEPParameterSpec parametrosOaep() {
        return new OAEPParameterSpec(
                "SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT);
    }

    private static int calcularCapacidadMaxima(PublicKey llavePublica) {
        int bytesDelModulo = ((RSAKey) llavePublica).getModulus().bitLength() / 8;
        int longitudDelResumen;
        try {
            longitudDelResumen = MessageDigest.getInstance("SHA-256").getDigestLength();
        } catch (Exception e) {
            throw new CryptoException("SHA-256 no esta disponible en esta JVM", e);
        }
        return bytesDelModulo - 2 * longitudDelResumen - 2;
    }
}
