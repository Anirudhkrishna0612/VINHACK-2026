package com.spectraledger.ledger.entity;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "enterprise")
public class Enterprise {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(nullable = false, unique = true)
    private String name;
    @Column(name = "api_key", nullable = false, unique = true)
    private String apiKey;
    @Column(name = "created_at", nullable = false)
    private Instant createdAt = Instant.now();

    protected Enterprise() { }
    public Enterprise(String name, String apiKey) { this.name = name; this.apiKey = apiKey; }

    public Long getId() { return id; }
    public String getName() { return name; }
    public String getApiKey() { return apiKey; }
    public Instant getCreatedAt() { return createdAt; }
}
