package com.spectraledger.ledger.controller;

import com.spectraledger.ledger.dto.Views.*;
import com.spectraledger.ledger.service.QueryService;
import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/accounts")
public class AccountController {
    private final QueryService queries;

    public AccountController(QueryService queries) { this.queries = queries; }

    @GetMapping
    public List<AccountView> all() { return queries.allAccounts(); }

    @GetMapping("/{sliceId}/balance")
    public AccountView balance(@PathVariable String sliceId) { return queries.balance(sliceId); }

    @GetMapping("/{sliceId}/history")
    public List<LedgerEntryView> history(@PathVariable String sliceId, @RequestParam(defaultValue = "50") int limit) {
        return queries.history(sliceId, limit);
    }
}
