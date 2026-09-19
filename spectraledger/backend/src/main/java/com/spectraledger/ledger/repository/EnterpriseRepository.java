package com.spectraledger.ledger.repository;

import com.spectraledger.ledger.entity.Enterprise;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface EnterpriseRepository extends JpaRepository<Enterprise, Long> {
    Optional<Enterprise> findByName(String name);
}
