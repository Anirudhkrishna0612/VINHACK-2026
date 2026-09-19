package com.spectraledger.ledger.repository;

import com.spectraledger.ledger.entity.Trade;
import java.math.BigDecimal;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface TradeRepository extends JpaRepository<Trade, Long> {
    Optional<Trade> findByTradeId(String tradeId);

    Page<Trade> findAllByOrderByExecutedAtDescIdDesc(Pageable pageable);

    // SUM() over zero rows is NULL in SQL; the default methods below turn that into ZERO.
    @Query("select sum(t.platformFee) from Trade t")
    BigDecimal rawSumPlatformFees();

    @Query("select sum(t.grossAmount) from Trade t")
    BigDecimal rawSumGrossVolume();

    @Query("select sum(t.quantityMbps) from Trade t")
    BigDecimal rawSumQuantityMbps();

    default BigDecimal sumPlatformFees() { return orZero(rawSumPlatformFees()); }
    default BigDecimal sumGrossVolume() { return orZero(rawSumGrossVolume()); }
    default BigDecimal sumQuantityMbps() { return orZero(rawSumQuantityMbps()); }

    private static BigDecimal orZero(BigDecimal v) { return v == null ? BigDecimal.ZERO : v; }
}
