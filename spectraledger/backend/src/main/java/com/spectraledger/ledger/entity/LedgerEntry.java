package com.spectraledger.ledger.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;

/** One immutable line of the double-entry journal. Rows are only ever inserted, never updated. */
@Entity
@Table(name = "ledger_entry")
public class LedgerEntry {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "trade_id", nullable = false)
    private Trade trade;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "slice_account_id", nullable = false)
    private SliceAccount sliceAccount;
    @Enumerated(EnumType.STRING)
    @Column(name = "entry_type", nullable = false)
    private EntryType entryType;
    @Column(nullable = false, precision = 19, scale = 4)
    private BigDecimal amount;
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    protected LedgerEntry() { }
    public LedgerEntry(Trade trade, SliceAccount sliceAccount, EntryType entryType, BigDecimal amount) {
        this.trade = trade; this.sliceAccount = sliceAccount; this.entryType = entryType; this.amount = amount;
    }

    public Long getId() { return id; }
    public Trade getTrade() { return trade; }
    public SliceAccount getSliceAccount() { return sliceAccount; }
    public EntryType getEntryType() { return entryType; }
    public BigDecimal getAmount() { return amount; }
    public Instant getCreatedAt() { return createdAt; }
}
