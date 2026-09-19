package com.spectraledger.ledger.service;

import com.spectraledger.ledger.dto.TradeExecutedEvent;
import com.spectraledger.ledger.dto.Views.SettlementResult;
import com.spectraledger.ledger.repository.TradeRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

/**
 * Front door for webhook trades. Deliberately NOT transactional itself: it sequences three separate
 * transactions (provision accounts -> settle -> recover from a duplicate race) so each failure mode has one clear owner.
 */
@Service
public class TradeIngestService {
    private final AccountProvisioningService provisioning;
    private final SettlementService settlement;
    private final TradeRepository trades;

    public TradeIngestService(AccountProvisioningService provisioning, SettlementService settlement, TradeRepository trades) {
        this.provisioning = provisioning;
        this.settlement = settlement;
        this.trades = trades;
    }

    public SettlementResult ingest(TradeExecutedEvent e) {
        ensureAccount(e.buyerSliceId(), e.buyerEnterprise());
        ensureAccount(e.sellerSliceId(), e.sellerEnterprise());
        try {
            return settlement.settle(e);
        } catch (DataIntegrityViolationException dup) {
            // Belt and braces: if the UNIQUE(trade_id) constraint ever fires, the whole settlement rolled back
            // (nothing double-counted) and we simply report the already-settled trade.
            return trades.findByTradeId(e.tradeId())
                    .map(t -> new SettlementResult(t.getTradeId(), t.getStatus(), true, t.getGrossAmount(),
                            t.getPlatformFee(), t.getNetToSeller(), null, null, t.getSettledAt()))
                    .orElseThrow(() -> dup);
        }
    }

    private void ensureAccount(String sliceId, String enterprise) {
        try {
            provisioning.ensure(sliceId, enterprise);
        } catch (DataIntegrityViolationException raced) {
            provisioning.ensure(sliceId, enterprise);   // someone else created it a millisecond earlier: it exists now
        }
    }
}
