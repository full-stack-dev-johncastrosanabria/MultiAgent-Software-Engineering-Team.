package com.prueba.orderms.config;

import org.apache.kafka.common.TopicPartition;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.annotation.EnableKafka;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.KafkaOperations;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.support.serializer.DeserializationException;
import org.springframework.util.backoff.ExponentialBackOff;

@Configuration
@EnableKafka
public class KafkaConfig {

    @Bean
    public ConcurrentKafkaListenerContainerFactory<String, Object> kafkaListenerContainerFactory(
            ConsumerFactory<String, Object> consumerFactory,
            DefaultErrorHandler manejadorDeErrores) {

        ConcurrentKafkaListenerContainerFactory<String, Object> fabrica =
                new ConcurrentKafkaListenerContainerFactory<>();
        fabrica.setConsumerFactory(consumerFactory);
        fabrica.setConcurrency(3);
        fabrica.setCommonErrorHandler(manejadorDeErrores);
        return fabrica;
    }

    @Bean
    public DefaultErrorHandler manejadorDeErrores(KafkaOperations<String, Object> operaciones) {
        // Envia al topic <original>.DLT conservando la particion de origen
        DeadLetterPublishingRecoverer recuperador = new DeadLetterPublishingRecoverer(
                operaciones,
                (registro, excepcion) ->
                        new TopicPartition(registro.topic() + ".DLT", registro.partition()));

        ExponentialBackOff espera = new ExponentialBackOff(1000L, 2.0);
        espera.setMaxAttempts(3);

        DefaultErrorHandler manejador = new DefaultErrorHandler(recuperador, espera);

        // Un mensaje mal formado no mejora reintentandolo: va directo al DLT
        manejador.addNotRetryableExceptions(DeserializationException.class);
        manejador.setCommitRecovered(true);
        return manejador;
    }
}
