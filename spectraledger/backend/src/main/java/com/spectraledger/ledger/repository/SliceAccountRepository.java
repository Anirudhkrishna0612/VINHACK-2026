package com.spectraledger.ledger.repository;

import com.spectraledger.ledger.entity.SliceAccount;
import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface SliceAccountRepository extends JpaRepository<SliceAccount, Long> {

    Optional<SliceAccount> findBySliceId(String sliceId);

    /** Scalar lookup: returns just the id, so the account row is NOT loaded (and cannot go stale) before we lock it. */
    @Query("select a.id from SliceAccount a where a.sliceId = :sliceId")
    Optional<Long> findIdBySliceId(@Param("sliceId") String sliceId);

    /**
     * SELECT ... FOR UPDATE on one account row. SettlementService calls this once per account in ASCENDING id order,
     * so two concurrent trades can never each hold one account while waiting for the other (no deadlock cycle),
     * and trades touching the same slice queue up instead of overwriting each other's balance.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from SliceAccount a where a.id = :id")
    Optional<SliceAccount> lockById(@Param("id") Long id);

    List<SliceAccount> findAllByOrderBySliceIdAsc();
}
