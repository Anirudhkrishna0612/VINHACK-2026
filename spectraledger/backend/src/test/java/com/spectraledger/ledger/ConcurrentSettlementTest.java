package com.spectraledger.ledger;

import static org.junit.jupiter.api.Assertions.*;

import com.spectraledger.ledger.config.LedgerProperties;
import com.spectraledger.ledger.dto.TradeExecutedEvent;
import com.spectraledger.ledger.dto.Views.IntegrityReport;
import com.spectraledger.ledger.entity.SliceAccount;
import com.spectraledger.ledger.repository.LedgerEntryRepository;
import com.spectraledger.ledger.repository.SliceAccountRepository;
import com.spectraledger.ledger.repository.TradeRepository;
import com.spectraledger.ledger.service.QueryService;
import com.spectraledger.ledger.service.TradeIngestService;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * MANUAL CONCURRENCY-SAFETY PROOF.  Run:  mvn test
 *
 * Many threads settle trades that all touch the same three slice accounts at once. If the balance update were a
 * plain read-modify-write without locking, two threads would read the same old balance and one update would be
 * lost ("lost update"). SettlementService prevents that with a pessimistic row lock taken in ascending-id order
 * (plus an @Version safety net). We assert the final balances equal the single-threaded arithmetic to the cent
 * and that the ledger journal re-derives every balance exactly.
 */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:concurrencytest;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=60000",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class ConcurrentSettlementTest {

    @Autowired TradeIngestService ingest;
    @Autowired SliceAccountRepository accounts;
    @Autowired TradeRepository trades;
    @Autowired LedgerEntryRepository entries;
    @Autowired QueryService queries;
    @Autowired LedgerProperties props;

    private static final String[] SLICES = {"test-slice-A", "test-slice-B", "test-slice-C"};

    private TradeExecutedEvent event(String id, String buyer, String seller, String price, String qty) {
        return new TradeExecutedEvent(id, buyer, seller, "Enterprise " + buyer, "Enterprise " + seller,
                new BigDecimal(price), new BigDecimal(qty), null, null, null, null);
    }

    @Test
    void concurrentTradesOnSharedAccountsNeverCorruptBalances() throws Exception {
        int nTrades = 300, nThreads = 16;
        Random rnd = new Random(42);
        List<TradeExecutedEvent> events = new ArrayList<>();
        Map<String, BigDecimal> expected = new HashMap<>();
        for (String s : SLICES) expected.put(s, props.initialSliceBalance());
        BigDecimal expectedFees = BigDecimal.ZERO;

        for (int i = 0; i < nTrades; i++) {
            String buyer = SLICES[rnd.nextInt(3)];
            String seller;
            do { seller = SLICES[rnd.nextInt(3)]; } while (seller.equals(buyer));
            String price = String.format("0.%04d", 1000 + rnd.nextInt(5000));
            String qty = String.format("%d.%02d", 1 + rnd.nextInt(90), rnd.nextInt(100));
            events.add(event("CONC-" + i, buyer, seller, price, qty));
            BigDecimal gross = new BigDecimal(price).multiply(new BigDecimal(qty)).setScale(4, RoundingMode.HALF_UP);
            BigDecimal fee = gross.multiply(props.platformFeeRate()).setScale(4, RoundingMode.HALF_UP);
            expected.merge(buyer, gross.negate(), BigDecimal::add);
            expected.merge(seller, gross.subtract(fee), BigDecimal::add);
            expectedFees = expectedFees.add(fee);
        }

        ExecutorService pool = Executors.newFixedThreadPool(nThreads);
        CountDownLatch startGun = new CountDownLatch(1);
        List<Future<?>> futures = new ArrayList<>();
        for (TradeExecutedEvent e : events) {
            futures.add(pool.submit(() -> { startGun.await(); ingest.ingest(e); return null; }));
        }
        startGun.countDown();
        for (Future<?> f : futures) f.get(120, TimeUnit.SECONDS);   // rethrows any settlement exception
        pool.shutdown();

        for (String s : SLICES) {
            SliceAccount a = accounts.findBySliceId(s).orElseThrow();
            assertEquals(0, expected.get(s).compareTo(a.getBalance()), "balance of " + s + " must equal sequential arithmetic");
        }
        assertEquals(nTrades, trades.count());
        assertEquals(nTrades * 3L, entries.count(), "exactly DEBIT+CREDIT+FEE per trade");
        assertEquals(0, expectedFees.compareTo(trades.sumPlatformFees()));
        IntegrityReport report = queries.verify();
        assertTrue(report.ok(), "journal must re-derive every balance: " + report.problems());
    }

    @Test
    void retriedWebhookNeverDoubleSettles() throws Exception {
        TradeExecutedEvent e = event("IDEMPOTENT-1", "idem-buyer", "idem-seller", "0.2000", "50.00");
        ExecutorService pool = Executors.newFixedThreadPool(12);
        List<Future<Boolean>> results = new ArrayList<>();
        CountDownLatch startGun = new CountDownLatch(1);
        for (int i = 0; i < 40; i++) {
            results.add(pool.submit(() -> { startGun.await(); return ingest.ingest(e).duplicate(); }));
        }
        startGun.countDown();
        int firstSettlements = 0;
        for (Future<Boolean> f : results) if (!f.get(60, TimeUnit.SECONDS)) firstSettlements++;
        pool.shutdown();

        assertEquals(1, firstSettlements, "exactly one delivery may settle; the other 39 are recognised duplicates");
        assertEquals(1, trades.findAll().stream().filter(t -> t.getTradeId().equals("IDEMPOTENT-1")).count());
        assertEquals(3, entries.countByTradeTradeId("IDEMPOTENT-1"));
        assertEquals(0, props.initialSliceBalance().subtract(new BigDecimal("10.0000"))
                .compareTo(accounts.findBySliceId("idem-buyer").orElseThrow().getBalance()), "buyer debited exactly once");
    }
}
