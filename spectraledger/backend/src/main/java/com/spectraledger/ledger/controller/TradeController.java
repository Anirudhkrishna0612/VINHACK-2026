package com.spectraledger.ledger.controller;

import com.spectraledger.ledger.dto.TradeExecutedEvent;
import com.spectraledger.ledger.dto.Views.*;
import com.spectraledger.ledger.service.QueryService;
import com.spectraledger.ledger.service.TradeIngestService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/trades")
public class TradeController {
    private final TradeIngestService ingest;
    private final QueryService queries;

    public TradeController(TradeIngestService ingest, QueryService queries) {
        this.ingest = ingest;
        this.queries = queries;
    }

    /** Webhook receiver for the AI engine. Idempotent on trade_id. */
    @PostMapping("/execute")
    public ResponseEntity<SettlementResult> execute(@Valid @RequestBody TradeExecutedEvent event) {
        return ResponseEntity.ok(ingest.ingest(event));
    }

    @GetMapping
    public PageView<TradeView> list(@RequestParam(defaultValue = "0") int page, @RequestParam(defaultValue = "20") int size) {
        return queries.listTrades(page, size);
    }

    @GetMapping("/{tradeId}")
    public TradeDetailView detail(@PathVariable String tradeId) {
        return queries.tradeDetail(tradeId);
    }
}
