package com.spectraledger.ledger.service;

import com.spectraledger.ledger.config.LedgerProperties;
import com.spectraledger.ledger.dto.TradeExecutedEvent;
import com.spectraledger.ledger.dto.Views.SettlementResult;
import com.spectraledger.ledger.entity.*;
import com.spectraledger.ledger.exception.ApiException;
import com.spectraledger.ledger.repository.LedgerEntryRepository;
import com.spectraledger.ledger.repository.SliceAccountRepository;
import com.spectraledger.ledger.repository.TradeRepository;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeSet;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * THE VAULT. One @Transactional method settles a trade atomically: either the Trade row, all three
 * LedgerEntry rows AND both balance updates commit together, or nothing does (ACID, no partial commit).
 *
 * Double-entry convention used here:
 *   DEBIT  buyer  account  gross          (buyer pays the full price)
 *   CREDIT seller account  gross          (seller is credited the full price)
 *   FEE    seller account  platform_fee   (platform skims its cut out of the seller's proceeds)
 * => buyer balance -= gross ; seller balance += gross - fee ; platform revenue = sum of FEE entries.
 */
@Service
public class SettlementService {
    private static final Logger log = LoggerFactory.getLogger(SettlementService.class);
    private static final BigDecimal RECONCILE_TOLERANCE = new BigDecimal("0.0002");

    private final SliceAccountRepository accounts;
    private final TradeRepository trades;
    private final LedgerEntryRepository entries;
    private final LedgerProperties props;

    public SettlementService(SliceAccountRepository accounts, TradeRepository trades,
                             LedgerEntryRepository entries, LedgerProperties props) {
        this.accounts = accounts;
        this.trades = trades;
        this.entries = entries;
        this.props = props;
    }

    @Transactional
    public SettlementResult settle(TradeExecutedEvent e) {
        if (e.buyerSliceId().equals(e.sellerSliceId())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "buyer_slice_id and seller_slice_id must differ");
        }
        Instant executedAt = parseTimestamp(e.timestamp());

        // 1. Lock both accounts (ascending id order => deadlock-free). Concurrent trades on the same slice queue here.
        Long buyerId = accountId(e.buyerSliceId());
        Long sellerId = accountId(e.sellerSliceId());
        Map<Long, SliceAccount> locked = new HashMap<>();
        for (Long id : new TreeSet<>(List.of(buyerId, sellerId))) {          // TreeSet = ascending id order
            locked.put(id, accounts.lockById(id).orElseThrow(
                    () -> new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "Account vanished during settlement")));
        }
        SliceAccount buyer = locked.get(buyerId);
        SliceAccount seller = locked.get(sellerId);

        // 2. Idempotency check AFTER taking the locks: a retried webhook that raced us has already committed by now.
        Optional<Trade> existing = trades.findByTradeId(e.tradeId());
        if (existing.isPresent()) {
            Trade t = existing.get();
            return new SettlementResult(t.getTradeId(), t.getStatus(), true, t.getGrossAmount(), t.getPlatformFee(),
                    t.getNetToSeller(), buyer.getBalance(), seller.getBalance(), t.getSettledAt());
        }

        // 3. The ledger computes the money itself; the sender's arithmetic is only reconciled, never trusted.
        BigDecimal price = e.price().setScale(4, RoundingMode.HALF_UP);
        BigDecimal qty = e.quantityMbps().setScale(2, RoundingMode.HALF_UP);
        BigDecimal gross = price.multiply(qty).setScale(4, RoundingMode.HALF_UP);
        BigDecimal fee = gross.multiply(props.platformFeeRate()).setScale(4, RoundingMode.HALF_UP);
        BigDecimal net = gross.subtract(fee);
        if (e.grossAmount() != null && e.grossAmount().subtract(gross).abs().compareTo(RECONCILE_TOLERANCE) > 0) {
            log.warn("Trade {}: sender gross {} differs from ledger-computed {}; using ledger value", e.tradeId(), e.grossAmount(), gross);
        }

        // 4. Move the money + write the immutable journal.
        buyer.debit(gross);
        seller.credit(net);
        Instant now = Instant.now();
        Trade trade = trades.save(new Trade(e.tradeId(), e.buyerSliceId(), e.sellerSliceId(), price, qty,
                gross, fee, net, executedAt, now, TradeStatus.SETTLED));
        entries.save(new LedgerEntry(trade, buyer, EntryType.DEBIT, gross));
        entries.save(new LedgerEntry(trade, seller, EntryType.CREDIT, gross));
        entries.save(new LedgerEntry(trade, seller, EntryType.FEE, fee));
        accounts.saveAll(List.of(buyer, seller));
        log.info("Settled {} : {} pays {} , {} nets {} , fee {}", e.tradeId(), buyer.getSliceId(), gross, seller.getSliceId(), net, fee);
        return new SettlementResult(trade.getTradeId(), trade.getStatus(), false, gross, fee, net,
                buyer.getBalance(), seller.getBalance(), now);
    }

    private Long accountId(String sliceId) {
        return accounts.findIdBySliceId(sliceId)
                .orElseThrow(() -> new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "No account for slice " + sliceId));
    }

    private static Instant parseTimestamp(String ts) {
        if (ts == null || ts.isBlank()) return Instant.now();
        try {
            return OffsetDateTime.parse(ts).toInstant();
        } catch (DateTimeParseException ex) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "timestamp must be ISO-8601, e.g. 2026-09-19T06:27:37Z");
        }
    }
}
