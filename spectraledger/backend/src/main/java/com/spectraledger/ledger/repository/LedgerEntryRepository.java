package com.spectraledger.ledger.repository;

import com.spectraledger.ledger.entity.EntryType;
import com.spectraledger.ledger.entity.LedgerEntry;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface LedgerEntryRepository extends JpaRepository<LedgerEntry, Long> {

    List<LedgerEntry> findByTradeTradeIdOrderByIdAsc(String tradeId);

    List<LedgerEntry> findBySliceAccountSliceIdOrderByCreatedAtDescIdDesc(String sliceId, Pageable pageable);

    @Query("select sum(e.amount) from LedgerEntry e where e.sliceAccount.id = :accountId and e.entryType = :type")
    BigDecimal rawSumForAccount(@Param("accountId") Long accountId, @Param("type") EntryType type);

    @Query("select sum(e.amount) from LedgerEntry e where e.entryType = :type")
    BigDecimal rawSumByType(@Param("type") EntryType type);

    default BigDecimal sumForAccount(Long accountId, EntryType type) {
        BigDecimal v = rawSumForAccount(accountId, type);
        return v == null ? BigDecimal.ZERO : v;
    }

    default BigDecimal sumByType(EntryType type) {
        BigDecimal v = rawSumByType(type);
        return v == null ? BigDecimal.ZERO : v;
    }

    long countByTradeTradeId(String tradeId);
}
