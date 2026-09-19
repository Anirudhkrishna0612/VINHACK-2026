package com.spectraledger.ledger.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.web.filter.OncePerRequestFilter;

/** Rejects POST /api/trades/execute unless X-Webhook-Secret matches the configured secret. */
public class WebhookSecretFilter extends OncePerRequestFilter {

    private final byte[] expected;

    public WebhookSecretFilter(String secret) {
        this.expected = secret.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !("POST".equals(request.getMethod()) && request.getRequestURI().equals("/api/trades/execute"));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String supplied = req.getHeader("X-Webhook-Secret");
        // constant-time comparison so response timing does not leak the secret
        boolean ok = supplied != null && MessageDigest.isEqual(expected, supplied.getBytes(StandardCharsets.UTF_8));
        if (!ok) {
            res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            res.setContentType("application/json");
            res.getWriter().write("{\"error\":\"unauthorized\",\"message\":\"Missing or invalid X-Webhook-Secret header\"}");
            return;
        }
        chain.doFilter(req, res);
    }
}
