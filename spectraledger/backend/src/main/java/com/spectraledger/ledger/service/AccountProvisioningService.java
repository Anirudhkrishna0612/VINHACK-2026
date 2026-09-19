package com.spectraledger.ledger.service;

import com.spectraledger.ledger.config.LedgerProperties;
import com.spectraledger.ledger.entity.Enterprise;
import com.spectraledger.ledger.entity.SliceAccount;
import com.spectraledger.ledger.repository.EnterpriseRepository;
import com.spectraledger.ledger.repository.SliceAccountRepository;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Creates the Enterprise + SliceAccount the first time a slice appears in a trade. Runs in its OWN small
 * transaction so that an account-creation race between two concurrent webhooks can be retried cleanly
 * without touching the settlement transaction.
 */
@Service
public class AccountProvisioningService {
    private final EnterpriseRepository enterprises;
    private final SliceAccountRepository accounts;
    private final LedgerProperties props;

    public AccountProvisioningService(EnterpriseRepository enterprises, SliceAccountRepository accounts, LedgerProperties props) {
        this.enterprises = enterprises;
        this.accounts = accounts;
        this.props = props;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public SliceAccount ensure(String sliceId, String enterpriseName) {
        return accounts.findBySliceId(sliceId).orElseGet(() -> {
            String name = (enterpriseName == null || enterpriseName.isBlank()) ? "Enterprise of " + sliceId : enterpriseName;
            Enterprise e = enterprises.findByName(name)
                    .orElseGet(() -> enterprises.save(new Enterprise(name, "sl_" + UUID.randomUUID().toString().replace("-", ""))));
            return accounts.save(new SliceAccount(e, sliceId, props.initialSliceBalance()));
        });
    }
}
