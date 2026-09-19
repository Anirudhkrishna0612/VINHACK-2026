package com.spectraledger.ledger.exception;

import org.springframework.http.HttpStatus;

/** A deliberate, client-caused failure (bad payload, unknown id ...) that maps to a clean 4xx. */
public class ApiException extends RuntimeException {
    private final HttpStatus status;

    public ApiException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public HttpStatus getStatus() { return status; }
}
