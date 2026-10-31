# Choosing a cache backend

alice:
We need a cache for the API responses. I suggest Redis.

---

**bob**
Redis adds a server to run. An in-process LRU cache is simpler, and switching later is one line:

```yaml
cache: memory
---
cache: redis
```

***

@carol
Simpler is better here. We will use the in-process cache and revisit Redis later.

___

This post has no author line, so its author is unknown.
