package com.spectraledger.ledger.config;

import java.math.BigDecimal;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** Typed view of the "spectraledger:" block in application.yml. */
@ConfigurationProperties(prefix = "spectraledger")
public record LedgerProperties(
        String webhookSecret,
        BigDecimal platformFeeRate,
        BigDecimal initialSliceBalance,
        String corsAllowedOriginPatterns) {
}
