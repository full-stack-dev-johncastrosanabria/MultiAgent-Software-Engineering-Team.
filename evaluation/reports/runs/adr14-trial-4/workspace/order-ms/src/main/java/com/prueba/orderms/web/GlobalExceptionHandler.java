package com.prueba.orderms.web;

import com.prueba.orderms.card.InvalidCardException;
import com.prueba.orderms.crypto.CryptoException;
import com.prueba.orderms.service.OrderNotFoundException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.kafka.KafkaException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Traduce las excepciones a respuestas RFC 7807.
 *
 * <p>Extiende {@link ResponseEntityExceptionHandler} para heredar el tratamiento de las
 * excepciones estandar de Spring MVC (ruta inexistente, metodo no soportado, media type
 * no soportado, cuerpo ilegible). Sin esa herencia el handler de {@link Exception} de mas
 * abajo las capturaba antes de que DefaultHandlerExceptionResolver pudiera darles su
 * estado real, y todas salian como 500.
 */
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException e,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {

        Map<String, String> errores = new HashMap<>();
        e.getBindingResult().getFieldErrors()
                .forEach(error -> errores.put(error.getField(), error.getDefaultMessage()));

        ProblemDetail problema = crear(HttpStatus.BAD_REQUEST, "Solicitud invalida",
                "Uno o mas campos no superaron la validacion");
        problema.setProperty("errors", errores);
        return handleExceptionInternal(e, problema, headers, HttpStatus.BAD_REQUEST, request);
    }

    @Override
    protected ResponseEntity<Object> handleNoResourceFoundException(NoResourceFoundException e,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {

        // El detalle por defecto habla de "static resource", que no le dice nada a quien
        // consume una API REST
        ProblemDetail problema = crear(HttpStatus.NOT_FOUND, "Recurso no encontrado",
                "No existe el recurso '%s' en esta API".formatted(e.getResourcePath()));
        return handleExceptionInternal(e, problema, headers, HttpStatus.NOT_FOUND, request);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ProblemDetail parametroInvalido(MethodArgumentTypeMismatchException e) {
        // Un identificador mal formado es un error del cliente, no una falla del servidor
        String tipoRequerido = e.getRequiredType() != null
                ? e.getRequiredType().getSimpleName()
                : "valor";
        return crear(HttpStatus.BAD_REQUEST, "Parametro invalido",
                "El valor '%s' no es un %s valido para el parametro '%s'"
                        .formatted(e.getValue(), tipoRequerido, e.getName()));
    }

    @ExceptionHandler(InvalidCardException.class)
    public ProblemDetail tarjetaInvalida(InvalidCardException e) {
        return crear(HttpStatus.BAD_REQUEST, "Datos de tarjeta invalidos", e.getMessage());
    }

    @ExceptionHandler(CryptoException.class)
    public ProblemDetail criptogramaInvalido(CryptoException e) {
        // Se registra la causa en el servidor pero al cliente se devuelve un mensaje generico
        log.warn("Fallo al procesar datos cifrados: {}", e.getMessage());
        return crear(HttpStatus.BAD_REQUEST, "Datos cifrados invalidos",
                "No fue posible procesar los datos de tarjeta cifrados");
    }

    @ExceptionHandler(OrderNotFoundException.class)
    public ProblemDetail pedidoNoEncontrado(OrderNotFoundException e) {
        return crear(HttpStatus.NOT_FOUND, "Pedido no encontrado", e.getMessage());
    }

    @ExceptionHandler(OptimisticLockingFailureException.class)
    public ProblemDetail conflictoDeConcurrencia(OptimisticLockingFailureException e) {
        return crear(HttpStatus.CONFLICT, "Conflicto de concurrencia",
                "El pedido fue modificado por otra operacion. Intente de nuevo.");
    }

    @ExceptionHandler(KafkaException.class)
    public ProblemDetail mensajeriaNoDisponible(KafkaException e) {
        log.error("Kafka no esta disponible", e);
        return crear(HttpStatus.SERVICE_UNAVAILABLE, "Servicio de mensajeria no disponible",
                "El pedido no pudo encolarse para su procesamiento. Intente mas tarde.");
    }

    @ExceptionHandler(Exception.class)
    public ProblemDetail errorNoControlado(Exception e) {
        log.error("Error no controlado", e);
        return crear(HttpStatus.INTERNAL_SERVER_ERROR, "Error interno",
                "Ocurrio un error inesperado al procesar la solicitud");
    }

    /**
     * Punto unico por donde pasan las respuestas construidas por la clase base, para que
     * las excepciones de Spring salgan con el mismo formato que las propias.
     */
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception e, Object cuerpo,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {

        ResponseEntity<Object> respuesta = super.handleExceptionInternal(e, cuerpo, headers, status, request);

        // Se modifica solo el cuerpo: la clase base ya resolvio el estado y las cabeceras
        // que exige cada caso, como el Allow de un 405.
        if (respuesta != null && respuesta.getBody() instanceof ProblemDetail problema) {
            if (esTituloPorDefecto(problema, status)) {
                problema.setTitle(tituloPara(status));
            }
            String detalle = detallePara(e);
            if (detalle != null) {
                problema.setDetail(detalle);
            }
            problema.setProperty("timestamp", Instant.now());
        }
        return respuesta;
    }

    /** Spring rellena el titulo con el reason phrase en ingles; ese es el que se reemplaza. */
    private boolean esTituloPorDefecto(ProblemDetail problema, HttpStatusCode estado) {
        HttpStatus estandar = HttpStatus.resolve(estado.value());
        return problema.getTitle() == null
                || (estandar != null && estandar.getReasonPhrase().equals(problema.getTitle()));
    }

    private String detallePara(Exception e) {
        return switch (e) {
            case HttpRequestMethodNotSupportedException ex ->
                    "El metodo %s no esta permitido para este recurso".formatted(ex.getMethod());
            case HttpMediaTypeNotSupportedException ex ->
                    "El tipo de contenido '%s' no esta soportado".formatted(ex.getContentType());
            case HttpMessageNotReadableException ex ->
                    "El cuerpo de la peticion esta ausente o no es un JSON valido";
            default -> null;
        };
    }

    private String tituloPara(HttpStatusCode estado) {
        return switch (estado.value()) {
            case 400 -> "Solicitud invalida";
            case 404 -> "Recurso no encontrado";
            case 405 -> "Metodo no permitido";
            case 406 -> "Formato no aceptable";
            case 415 -> "Tipo de contenido no soportado";
            default -> estado.is5xxServerError() ? "Error interno" : "Solicitud rechazada";
        };
    }

    private ProblemDetail crear(HttpStatus estado, String titulo, String detalle) {
        ProblemDetail problema = ProblemDetail.forStatusAndDetail(estado, detalle);
        problema.setTitle(titulo);
        problema.setProperty("timestamp", Instant.now());
        return problema;
    }
}
