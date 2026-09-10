package com.prueba.orderms.repository;

import com.prueba.orderms.domain.Order;
import com.prueba.orderms.domain.OrderStatus;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface OrderRepository extends JpaRepository<Order, UUID> {

    Page<Order> findAllByStatus(OrderStatus status, Pageable pageable);
}
