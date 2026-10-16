def is_expired(inserted_at, ttl, now):
    return now > inserted_at + ttl
