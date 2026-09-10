package com.prueba.orderms.web.dto;

import org.springframework.data.domain.Page;

import java.util.List;
import java.util.function.Function;

// Forma propia en lugar de serializar PageImpl directamente, cuya forma no es estable entre versiones
public record PagedResponse<T>(
        List<T> content,
        int page,
        int size,
        long totalElements,
        int totalPages,
        boolean last
) {

    public static <E, T> PagedResponse<T> desde(Page<E> pagina, Function<E, T> mapeador) {
        return new PagedResponse<>(
                pagina.getContent().stream().map(mapeador).toList(),
                pagina.getNumber(),
                pagina.getSize(),
                pagina.getTotalElements(),
                pagina.getTotalPages(),
                pagina.isLast());
    }
}
