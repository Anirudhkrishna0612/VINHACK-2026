package com.spectraledger.ledger.dto;

import com.spectraledger.ledger.entity.EntryType;
import com.spectraledger.ledger.entity.TradeStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

/** Small response records (Java 21 records = immutable DTOs with zero boilerplate). */
public final class Views {
    private Views() { }

    public record SettlementResult(String tradeId, TradeStatus status, boolean duplicate,
                                   BigDecimal grossAmount, BigDecimal platformFee, BigDecimal netToSeller,
                                   BigDecimal buyerBalance, BigDecimal sellerBalance, Instant settledAt) { }

    public record TradeView(String tradeId, String buyerSliceId, String sellerSliceId, BigDecimal price,
                            BigDecimal quantityMbps, BigDecimal grossAmount, BigDecimal platformFee,
                            BigDecimal netToSeller, Instant executedAt, Instant settledAt, TradeStatus status) { }

    public record LedgerEntryView(Long id, String tradeId, String sliceId, EntryType entryType,
                                  BigDecimal amount, Instant createdAt) { }

    public record TradeDetailView(TradeView trade, List<LedgerEntryView> ledgerEntries) { }

    public record PageView<T>(List<T> content, int page, int size, long totalElements, int totalPages) { }

    public record AccountView(String sliceId, String enterprise, BigDecimal balance, Instant createdAt) { }

    public record RevenueSummary(BigDecimal totalPlatformFees, BigDecimal totalVolume, long tradeCount,
                                 BigDecimal totalQuantityMbps, BigDecimal feeRate) { }

    public record IntegrityReport(boolean ok, int accountsChecked, long tradesChecked, List<String> problems) { }

    public record ErrorResponse(String error, String message) { }
}
