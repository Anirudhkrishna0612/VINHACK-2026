package com.spectraledger.ledger.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

/**
 * Wire format of the AI engine's TradeExecutedEvent (snake_case JSON). Unknown extra fields
 * (event_type, fee_rate, workload_type ...) are ignored. gross_amount / platform_fee / net_to_seller are
 * accepted for reconciliation but the LEDGER recomputes them itself - it never trusts sender arithmetic.
 */
public record TradeExecutedEvent(
        @NotBlank @Size(max = 64) String tradeId,
        @NotBlank @Size(max = 64) String buyerSliceId,
        @NotBlank @Size(max = 64) String sellerSliceId,
        @Size(max = 120) String buyerEnterprise,
        @Size(max = 120) String sellerEnterprise,
        @NotNull @DecimalMin("0.0001") @Digits(integer = 9, fraction = 8) BigDecimal price,
        @NotNull @DecimalMin("0.01") @Digits(integer = 9, fraction = 8) BigDecimal quantityMbps,
        BigDecimal grossAmount,
        BigDecimal platformFee,
        BigDecimal netToSeller,
        String timestamp) {
}
