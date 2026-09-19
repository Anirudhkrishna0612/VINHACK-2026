package com.spectraledger.ledger.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;

@Entity
@Table(name = "slice_account")
public class SliceAccount {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "enterprise_id", nullable = false)
    private Enterprise enterprise;
    @Column(name = "slice_id", nullable = false, unique = true)
    private String sliceId;
    @Column(nullable = false, precision = 19, scale = 4)
    private BigDecimal balance;
    @Column(name = "created_at", nullable = false)
    private Instant createdAt = Instant.now();
    /** Optimistic-lock safety net on top of the pessimistic row lock (see SettlementService). */
    @Version
    private long version;

    protected SliceAccount() { }
    public SliceAccount(Enterprise enterprise, String sliceId, BigDecimal balance) {
        this.enterprise = enterprise; this.sliceId = sliceId; this.balance = balance;
    }

    public void debit(BigDecimal amount) { this.balance = this.balance.subtract(amount); }
    public void credit(BigDecimal amount) { this.balance = this.balance.add(amount); }

    public Long getId() { return id; }
    public Enterprise getEnterprise() { return enterprise; }
    public String getSliceId() { return sliceId; }
    public BigDecimal getBalance() { return balance; }
    public Instant getCreatedAt() { return createdAt; }
    public long getVersion() { return version; }
}
