package com.spectraledger.ledger.service;

import com.spectraledger.ledger.config.LedgerProperties;
import com.spectraledger.ledger.dto.Views.*;
import com.spectraledger.ledger.entity.*;
import com.spectraledger.ledger.exception.ApiException;
import com.spectraledger.ledger.repository.*;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Read-only queries for the dashboard, plus the ledger self-audit. */
@Service
@Transactional(readOnly = true)
public class QueryService {
    private final TradeRepository trades;
    private final LedgerEntryRepository entries;
    private final SliceAccountRepository accounts;
    private final LedgerProperties props;

    public QueryService(TradeRepository trades, LedgerEntryRepository entries, SliceAccountRepository accounts, LedgerProperties props) {
        this.trades = trades;
        this.entries = entries;
        this.accounts = accounts;
        this.props = props;
    }

    public PageView<TradeView> listTrades(int page, int size) {
        Page<Trade> p = trades.findAllByOrderByExecutedAtDescIdDesc(PageRequest.of(Math.max(page, 0), Math.min(Math.max(size, 1), 200)));
        return new PageView<>(p.getContent().stream().map(QueryService::toView).toList(),
                p.getNumber(), p.getSize(), p.getTotalElements(), p.getTotalPages());
    }

    public TradeDetailView tradeDetail(String tradeId) {
        Trade t = trades.findByTradeId(tradeId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "No trade with trade_id " + tradeId));
        return new TradeDetailView(toView(t), entries.findByTradeTradeIdOrderByIdAsc(tradeId).stream().map(QueryService::toView).toList());
    }

    public AccountView balance(String sliceId) {
        SliceAccount a = accounts.findBySliceId(sliceId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "No account for slice " + sliceId + " (it appears after its first settled trade)"));
        return toView(a);
    }

    public List<AccountView> allAccounts() {
        return accounts.findAllByOrderBySliceIdAsc().stream().map(QueryService::toView).toList();
    }

    public List<LedgerEntryView> history(String sliceId, int limit) {
        balance(sliceId);   // 404 if unknown
        return entries.findBySliceAccountSliceIdOrderByCreatedAtDescIdDesc(sliceId, PageRequest.of(0, Math.min(Math.max(limit, 1), 500)))
                .stream().map(QueryService::toView).toList();
    }

    public RevenueSummary revenue() {
        return new RevenueSummary(trades.sumPlatformFees(), trades.sumGrossVolume(), trades.count(),
                trades.sumQuantityMbps(), props.platformFeeRate());
    }

    /** Recomputes every balance from the immutable journal and compares it with the stored balance. */
    public IntegrityReport verify() {
        List<String> problems = new ArrayList<>();
        List<SliceAccount> all = accounts.findAll();
        for (SliceAccount a : all) {
            BigDecimal expected = props.initialSliceBalance()
                    .add(entries.sumForAccount(a.getId(), EntryType.CREDIT))
                    .subtract(entries.sumForAccount(a.getId(), EntryType.DEBIT))
                    .subtract(entries.sumForAccount(a.getId(), EntryType.FEE));
            if (expected.compareTo(a.getBalance()) != 0) {
                problems.add("Account " + a.getSliceId() + ": stored balance " + a.getBalance() + " != journal-derived " + expected);
            }
        }
        if (trades.sumPlatformFees().compareTo(entries.sumByType(EntryType.FEE)) != 0) {
            problems.add("Sum of trade fees differs from sum of FEE ledger entries");
        }
        BigDecimal net = entries.sumByType(EntryType.CREDIT).subtract(entries.sumByType(EntryType.DEBIT)).subtract(entries.sumByType(EntryType.FEE));
        if (net.compareTo(trades.sumPlatformFees().negate()) != 0) {   // credits - debits - fees must equal -(platform fees)
            problems.add("Journal does not balance");
        }
        return new IntegrityReport(problems.isEmpty(), all.size(), trades.count(), problems);
    }

    private static TradeView toView(Trade t) {
        return new TradeView(t.getTradeId(), t.getBuyerSliceId(), t.getSellerSliceId(), t.getPrice(), t.getQuantityMbps(),
                t.getGrossAmount(), t.getPlatformFee(), t.getNetToSeller(), t.getExecutedAt(), t.getSettledAt(), t.getStatus());
    }

    private static LedgerEntryView toView(LedgerEntry e) {
        return new LedgerEntryView(e.getId(), e.getTrade().getTradeId(), e.getSliceAccount().getSliceId(),
                e.getEntryType(), e.getAmount(), e.getCreatedAt());
    }

    private static AccountView toView(SliceAccount a) {
        return new AccountView(a.getSliceId(), a.getEnterprise().getName(), a.getBalance(), a.getCreatedAt());
    }
}
