package com.spectraledger.ledger.controller;

import com.spectraledger.ledger.dto.Views.*;
import com.spectraledger.ledger.service.QueryService;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

/** Health check, revenue source-of-truth, and the ledger self-audit. */
@RestController
@RequestMapping("/api")
public class SystemController {
    private final QueryService queries;

    public SystemController(QueryService queries) { this.queries = queries; }

    @GetMapping("/health")
    public Map<String, String> health() { return Map.of("status", "ok", "service", "spectraledger-ledger"); }

    @GetMapping("/revenue/summary")
    public RevenueSummary revenue() { return queries.revenue(); }

    @GetMapping("/ledger/verify")
    public IntegrityReport verify() { return queries.verify(); }
}
