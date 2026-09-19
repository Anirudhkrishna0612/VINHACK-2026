package com.spectraledger.ledger.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;

@Entity
@Table(name = "trade", indexes = @Index(name = "idx_trade_executed_at", columnList = "executed_at"))
public class Trade {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    /** Same id the AI engine minted. UNIQUE constraint = last line of defence for idempotency. */
    @Column(name = "trade_id", nullable = false, unique = true)
    private String tradeId;
    @Column(name = "buyer_slice_id", nullable = false)
    private String buyerSliceId;
    @Column(name = "seller_slice_id", nullable = false)
    private String sellerSliceId;
    @Column(nullable = false, precision = 19, scale = 4)
    private BigDecimal price;
    @Column(name = "quantity_mbps", nullable = false, precision = 19, scale = 2)
    private BigDecimal quantityMbps;
    @Column(name = "gross_amount", nullable = false, precision = 19, scale = 4)
    private BigDecimal grossAmount;
    @Column(name = "platform_fee", nullable = false, precision = 19, scale = 4)
    private BigDecimal platformFee;
    @Column(name = "net_to_seller", nullable = false, precision = 19, scale = 4)
    private BigDecimal netToSeller;
    @Column(name = "executed_at", nullable = false)
    private Instant executedAt;
    @Column(name = "settled_at", nullable = false)
    private Instant settledAt;
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TradeStatus status;

    protected Trade() { }
    public Trade(String tradeId, String buyerSliceId, String sellerSliceId, BigDecimal price, BigDecimal quantityMbps,
                 BigDecimal grossAmount, BigDecimal platformFee, BigDecimal netToSeller,
                 Instant executedAt, Instant settledAt, TradeStatus status) {
        this.tradeId = tradeId; this.buyerSliceId = buyerSliceId; this.sellerSliceId = sellerSliceId;
        this.price = price; this.quantityMbps = quantityMbps; this.grossAmount = grossAmount;
        this.platformFee = platformFee; this.netToSeller = netToSeller;
        this.executedAt = executedAt; this.settledAt = settledAt; this.status = status;
    }

    public Long getId() { return id; }
    public String getTradeId() { return tradeId; }
    public String getBuyerSliceId() { return buyerSliceId; }
    public String getSellerSliceId() { return sellerSliceId; }
    public BigDecimal getPrice() { return price; }
    public BigDecimal getQuantityMbps() { return quantityMbps; }
    public BigDecimal getGrossAmount() { return grossAmount; }
    public BigDecimal getPlatformFee() { return platformFee; }
    public BigDecimal getNetToSeller() { return netToSeller; }
    public Instant getExecutedAt() { return executedAt; }
    public Instant getSettledAt() { return settledAt; }
    public TradeStatus getStatus() { return status; }
}
